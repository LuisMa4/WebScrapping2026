from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from database.models import Job, RawJob
from database import repository as repo
from processing.cleaner import clean_text
from processing.normalizer import normalize_city, normalize_company, normalize_title

logger = logging.getLogger("sivml.deduplicator")

# Umbral de similitud Levenshtein para considerar dos ofertas duplicadas
_FUZZY_THRESHOLD = 85


def _make_dedup_key(title: str | None, company: str | None, city: str | None) -> str:
    parts = [
        _slugify(normalize_title(title) or title or ""),
        _slugify(normalize_company(company) or company or ""),
        _slugify(normalize_city(city) or city or ""),
    ]
    return "|".join(parts)


def _slugify(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def run_exact_dedup(session: Session, study_id: str) -> dict[str, int]:
    """
    Agrupa raw_jobs por clave exacta (title + company + city normalizados).
    Para cada grupo, deja el más antiguo como canónico e inserta en jobs.
    Marca los demás como is_duplicate=True.
    Devuelve stats: {'groups': N, 'duplicates_marked': M, 'jobs_created': K}
    """
    raw_jobs = repo.get_non_duplicate_raw_jobs(session, study_id)
    groups: dict[str, list[RawJob]] = defaultdict(list)

    for rj in raw_jobs:
        key = _make_dedup_key(rj.title, rj.company, rj.city)
        groups[key].append(rj)

    duplicates_marked = 0
    jobs_created = 0

    for key, group in groups.items():
        # Ordenar: primero el más antiguo posted_date, luego el primer scrapeado
        group.sort(key=lambda x: (x.posted_date or x.scraped_at.date(), x.id))
        canonical_raw = group[0]

        job = _create_job_from_raw(session, canonical_raw, [rj.id for rj in group])
        jobs_created += 1

        # Marcar duplicados
        for rj in group[1:]:
            repo.mark_as_duplicate(session, rj.id, job.id)
            duplicates_marked += 1

        # Actualizar el canónico también para que apunte al job
        repo.mark_as_duplicate(session, canonical_raw.id, job.id)
        canonical_raw.is_duplicate = False  # revertir — no es duplicado, es canónico
        session.commit()

    logger.info(
        f"Dedup exacto: {len(groups)} grupos, {duplicates_marked} duplicados, {jobs_created} jobs"
    )
    return {"groups": len(groups), "duplicates_marked": duplicates_marked, "jobs_created": jobs_created}


def run_fuzzy_dedup(session: Session, study_id: str, threshold: int = _FUZZY_THRESHOLD) -> dict[str, int]:
    """
    Segundo pase fuzzy sobre los jobs ya creados.
    Fusiona jobs cuyo título es ≥ threshold% similar y misma empresa+ciudad.
    """
    from sqlalchemy import select
    jobs = session.scalars(select(Job).where(Job.study_id == study_id)).all()

    merged = 0
    checked = set()

    for i, job_a in enumerate(jobs):
        if job_a.id in checked:
            continue
        for job_b in jobs[i + 1:]:
            if job_b.id in checked:
                continue
            if _slugify(job_a.company_normalized or "") != _slugify(job_b.company_normalized or ""):
                continue
            if _slugify(job_a.city_normalized or "") != _slugify(job_b.city_normalized or ""):
                continue
            score = fuzz.token_sort_ratio(
                job_a.title_normalized or "",
                job_b.title_normalized or "",
            )
            if score >= threshold:
                # Fusionar job_b en job_a
                merged_ids = job_a.raw_job_ids + job_b.raw_job_ids
                job_a.raw_job_ids = merged_ids
                session.delete(job_b)
                checked.add(job_b.id)
                merged += 1

    session.commit()
    logger.info(f"Dedup fuzzy: {merged} jobs fusionados")
    return {"merged": merged}


# ---------------------------------------------------------------------------
# Crear Job desde RawJob
# ---------------------------------------------------------------------------

def _create_job_from_raw(session: Session, raw: RawJob, raw_ids: list[int]) -> Job:
    from processing.normalizer import (
        normalize_city,
        normalize_company,
        normalize_education,
        normalize_experience,
        normalize_modality,
        normalize_salary,
        normalize_title,
    )
    from processing.cleaner import clean_description

    sal_min, sal_max, currency, period = normalize_salary(raw.salary_raw)
    exp_min, exp_max = normalize_experience(raw.experience_raw)

    job_data = {
        "study_id": raw.study_id,
        "title_normalized": normalize_title(raw.title),
        "company_normalized": normalize_company(raw.company),
        "city_normalized": normalize_city(raw.city),
        "country": raw.country,
        "portal": raw.portal,
        "url": raw.url,
        "posted_date": raw.posted_date,
        "salary_min": sal_min,
        "salary_max": sal_max,
        "salary_currency": currency,
        "salary_period": period,
        "modality": normalize_modality(raw.modality_raw),
        "contract_type": raw.contract_raw,
        "experience_years_min": exp_min,
        "experience_years_max": exp_max,
        "education_level": normalize_education(raw.education_raw),
        "description_clean": clean_description(raw.description_raw),
    }

    job = repo.create_job(session, job_data)
    job.raw_job_ids = raw_ids
    session.commit()
    return job
