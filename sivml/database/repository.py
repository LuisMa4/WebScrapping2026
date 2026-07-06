from __future__ import annotations

import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from config.settings import StudyConfig, study_config_from_dict, study_config_to_dict
from database.models import Job, RawJob, ScrapingRun, Study, StudyTemplate
from scrapers.base import ScrapedJob


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------

def create_study(
    session: Session,
    config: StudyConfig,
    config_path: str | None = None,
    status: str = "running",
    dry_run: bool = False,
) -> Study:
    if config_path:
        config_yaml = Path(config_path).read_text(encoding="utf-8")
    else:
        # Snapshot JSON de la config completa (no solo YAML de archivo): un
        # estudio 'queued' puede promoverse minutos/horas despues en OTRO
        # hilo, que necesita reconstruir el StudyConfig exacto con el que
        # se creo -- ver get_study_config().
        config_yaml = json.dumps({"config": study_config_to_dict(config), "dry_run": dry_run})

    study = Study(
        id=config.study_id,
        name=config.study_name,
        academic_program=config.academic_program,
        config_yaml=config_yaml,
        started_at=datetime.utcnow(),
        status=status,
    )
    session.add(study)
    session.commit()
    return study


def count_running_studies(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(Study).where(Study.status == "running")
    ) or 0


def next_queued_study(session: Session) -> Study | None:
    return session.scalars(
        select(Study).where(Study.status == "queued").order_by(Study.started_at)
    ).first()


def claim_queued_study(session: Session, study_id: str) -> bool:
    """
    Intenta pasar un estudio de 'queued' a 'running' de forma atomica.
    Devuelve False si el estudio ya no esta en 'queued' (otro hilo lo
    reclamo primero, o no existe) -- evita que dos hilos que terminan casi
    al mismo tiempo arranquen el mismo estudio en cola por duplicado.
    """
    result = session.execute(
        update(Study)
        .where(Study.id == study_id, Study.status == "queued")
        .values(status="running", started_at=datetime.utcnow())
    )
    session.commit()
    return result.rowcount == 1


def get_study_config(session: Session, study_id: str) -> tuple[StudyConfig, bool] | None:
    """
    Reconstruye el StudyConfig (y el flag dry_run) guardado por create_study().
    Devuelve None si el estudio no existe o su config_yaml no tiene el
    formato JSON esperado (ej. estudios creados por el CLI con config_path,
    que guardan el YAML crudo del archivo en vez del snapshot JSON).
    """
    study = session.get(Study, study_id)
    if not study or not study.config_yaml:
        return None
    try:
        data = json.loads(study.config_yaml)
        cfg = study_config_from_dict(data["config"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return cfg, bool(data.get("dry_run", False))


def finish_study(session: Session, study_id: str, success: bool = True) -> None:
    study = session.get(Study, study_id)
    if study:
        try:
            study.finished_at = datetime.utcnow()
            # No usar study.stop_requested aqui: si esta session ya tenia el
            # Study cargado en su identity map desde antes (ej. create_study(),
            # al inicio de una corrida larga), session.get() devuelve el objeto
            # CACHEADO sin releerlo -- y no veria un stop_requested=True escrito
            # por otra session/pestana (el boton "Detener" corre en una session
            # de Streamlit distinta a la que ejecuta el scraping). is_stop_requested()
            # hace un select de solo esa columna, que si siempre lee el valor
            # actual de la BD.
            if is_stop_requested(session, study_id):
                study.status = "stopped"
            else:
                study.status = "completed" if success else "failed"
            session.commit()
        except StaleDataError:
            # El estudio fue eliminado (boton "Eliminar" en otra pestana)
            # mientras esta session -- que lo trae cacheado en su identity
            # map desde create_study() -- todavia estaba corriendo el
            # scraping. Ya no hay nada que actualizar. El autoflush de
            # is_stop_requested() (un select dispara flush de cambios
            # pendientes) puede ser el que dispare esto, no solo el commit
            # final -- por eso el try envuelve todo el bloque, no solo el
            # commit. Sin este rollback la session queda en estado "rolled
            # back" y cualquier uso posterior (incluido el except Exception
            # de _run_new_study) revienta con PendingRollbackError en cascada.
            session.rollback()


def request_stop(session: Session, study_id: str) -> None:
    """
    Marca un estudio 'running' para que se detenga en la proxima
    oportunidad segura (entre una busqueda keyword/ciudad y la siguiente).
    El scraping corre en threads separados del hilo que atiende al boton
    "Detener", asi que esto solo escribe una bandera en la BD -- el propio
    loop de scraping (scraping.py) es quien la revisa periodicamente.
    """
    study = session.get(Study, study_id)
    if study:
        study.stop_requested = True
        session.commit()


def is_stop_requested(session: Session, study_id: str) -> bool:
    return bool(session.scalar(select(Study.stop_requested).where(Study.id == study_id)))


def list_studies(session: Session) -> Sequence[Study]:
    return session.scalars(select(Study).order_by(Study.started_at.desc())).all()


def get_study(session: Session, study_id: str) -> Study | None:
    return session.get(Study, study_id)


def get_last_activity(session: Session, study_id: str) -> datetime | None:
    """
    Momento mas reciente de actividad (inicio o fin de cualquier
    scraping_run) para un estudio. None si el estudio todavia no tiene
    ninguna run registrada.
    """
    runs = session.scalars(select(ScrapingRun).where(ScrapingRun.study_id == study_id)).all()
    timestamps = [t for r in runs for t in (r.started_at, r.finished_at) if t is not None]
    return max(timestamps) if timestamps else None


def is_study_stale(
    study: Study,
    last_activity: datetime | None,
    threshold_minutes: int = 15,
    now: datetime | None = None,
) -> bool:
    """
    True si el estudio sigue 'running' o 'queued' pero no ha habido
    actividad (ninguna scraping_run iniciada o terminada) en los ultimos
    `threshold_minutes`. Detecta estudios "atascados": 'running' cuando el
    proceso de scraping murio a mitad de camino (crash, conflicto de
    puertos, reinicio de Streamlit); 'queued' cuando el dashboard se
    reinicio antes de promoverlo (el hilo que lo habria arrancado ya no
    existe, se queda en cola para siempre sin este chequeo).
    """
    if study.status not in ("running", "queued"):
        return False
    now = now or datetime.utcnow()
    reference = last_activity or study.started_at
    if reference is None:
        return False
    elapsed_minutes = (now - reference).total_seconds() / 60
    return elapsed_minutes > threshold_minutes


def mark_study_failed(session: Session, study_id: str, reason: str = "Marcado como fallido manualmente") -> None:
    """
    Marca un estudio y cualquiera de sus scraping_runs en estado 'running'
    como fallidos. Usado para limpiar estudios atascados sin necesitar
    edicion manual de la base de datos.
    """
    study = session.get(Study, study_id)
    if not study:
        return
    study.status = "failed"
    study.finished_at = datetime.utcnow()
    running_runs = session.scalars(
        select(ScrapingRun).where(ScrapingRun.study_id == study_id, ScrapingRun.status == "running")
    ).all()
    for run in running_runs:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.error_message = reason
    session.commit()


def delete_study(session: Session, study_id: str) -> bool:
    """
    Borra un estudio y todo lo que depende de el (raw_jobs, jobs,
    scraping_runs). Devuelve False si el estudio no existe.

    Orden de borrado: hijos antes que el padre, para no violar las FK.
    RawJob.canonical_id referencia a Job, asi que raw_jobs se borra antes
    que jobs.
    """
    study = session.get(Study, study_id)
    if not study:
        return False

    session.query(RawJob).filter(RawJob.study_id == study_id).delete(synchronize_session=False)
    session.query(Job).filter(Job.study_id == study_id).delete(synchronize_session=False)
    session.query(ScrapingRun).filter(ScrapingRun.study_id == study_id).delete(synchronize_session=False)
    session.delete(study)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# Raw jobs
# ---------------------------------------------------------------------------

def upsert_raw_job(session: Session, job: ScrapedJob) -> tuple[RawJob, bool]:
    """
    Inserta la oferta si no existe ya en ESTE estudio (study_id, portal, source_id).
    La unicidad es por estudio: la misma oferta puede pertenecer a varios estudios
    distintos (ej. al re-ejecutar una plantilla en una fecha posterior), pero no se
    duplica si el mismo estudio se re-scrapea. Devuelve (modelo, is_new).
    """
    existing = session.scalars(
        select(RawJob).where(
            RawJob.study_id == job.study_id,
            RawJob.portal == job.portal,
            RawJob.source_id == job.source_id,
        )
    ).first()

    if existing:
        return existing, False

    raw = RawJob(
        study_id=job.study_id,
        source_id=job.source_id,
        portal=job.portal,
        url=job.url,
        scraped_at=job.scraped_at,
        title=job.title,
        company=job.company,
        city=job.city,
        country=job.country,
        posted_date=job.posted_date,
        description_raw=job.description_raw,
        salary_raw=job.salary_raw,
        modality_raw=job.modality_raw,
        contract_raw=job.contract_raw,
        experience_raw=job.experience_raw,
        education_raw=job.education_raw,
        keyword_matched=job.keyword_matched,
    )
    session.add(raw)
    session.commit()
    return raw, True


def get_raw_jobs_for_study(session: Session, study_id: str) -> Sequence[RawJob]:
    return session.scalars(
        select(RawJob).where(RawJob.study_id == study_id)
    ).all()


def get_non_duplicate_raw_jobs(session: Session, study_id: str) -> Sequence[RawJob]:
    """
    Raw jobs aun no procesados por el deduplicador: ni marcados como duplicado
    ni ya vinculados a un Job canonico (canonical_id is None). Este segundo
    filtro es lo que hace idempotente a run_exact_dedup: llamarlo dos veces
    sobre el mismo estudio no vuelve a crear Jobs para raw_jobs ya procesados.
    """
    return session.scalars(
        select(RawJob).where(
            RawJob.study_id == study_id,
            RawJob.is_duplicate == False,  # noqa: E712
            RawJob.canonical_id.is_(None),
        )
    ).all()


def mark_as_duplicate(session: Session, raw_job_id: int, canonical_id: int) -> None:
    raw = session.get(RawJob, raw_job_id)
    if raw:
        raw.is_duplicate = True
        raw.canonical_id = canonical_id
    session.commit()


# ---------------------------------------------------------------------------
# Canonical jobs
# ---------------------------------------------------------------------------

def create_job(session: Session, job_data: dict) -> Job:
    job = Job(**job_data)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_jobs_for_study(session: Session, study_id: str) -> Sequence[Job]:
    return session.scalars(
        select(Job).where(Job.study_id == study_id).order_by(Job.posted_date.desc())
    ).all()


# ---------------------------------------------------------------------------
# Scraping runs
# ---------------------------------------------------------------------------

def start_scraping_run(
    session: Session,
    study_id: str,
    portal: str,
    keyword: str,
    city: str,
) -> ScrapingRun:
    run = ScrapingRun(
        study_id=study_id,
        portal=portal,
        keyword=keyword,
        city=city,
        started_at=datetime.utcnow(),
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_scraping_run(
    session: Session,
    run_id: int,
    records_found: int,
    records_new: int,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    run = session.get(ScrapingRun, run_id)
    if run:
        run.finished_at = datetime.utcnow()
        run.records_found = records_found
        run.records_new = records_new
        run.status = "completed" if success else "failed"
        run.error_message = error_message
    session.commit()


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------

def create_template(session: Session, data: dict) -> StudyTemplate:
    """Crea una nueva plantilla de scraping."""
    t = StudyTemplate(
        name=data["name"],
        academic_program=data["academic_program"],
        notes=data.get("notes"),
        max_pages=data.get("max_pages", 10),
        delay_min=data.get("delay_min", 2.0),
        delay_max=data.get("delay_max", 5.0),
        headless=data.get("headless", True),
        created_at=datetime.utcnow(),
    )
    t.keywords = data["keywords"]
    t.cities = data["cities"]
    t.portals = data["portals"]
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def list_templates(session: Session) -> Sequence[StudyTemplate]:
    """Lista todas las plantillas, las mas recientes primero."""
    return session.scalars(
        select(StudyTemplate).order_by(
            StudyTemplate.last_run_at.desc().nulls_last(),
            StudyTemplate.created_at.desc(),
        )
    ).all()


def get_template(session: Session, template_id: int) -> StudyTemplate | None:
    return session.get(StudyTemplate, template_id)


def update_template(session: Session, template_id: int, data: dict) -> StudyTemplate | None:
    t = session.get(StudyTemplate, template_id)
    if not t:
        return None
    for field in ("name", "academic_program", "notes", "max_pages",
                  "delay_min", "delay_max", "headless"):
        if field in data:
            setattr(t, field, data[field])
    if "keywords" in data:
        t.keywords = data["keywords"]
    if "cities" in data:
        t.cities = data["cities"]
    if "portals" in data:
        t.portals = data["portals"]
    session.commit()
    return t


def delete_template(session: Session, template_id: int) -> bool:
    t = session.get(StudyTemplate, template_id)
    if not t:
        return False
    session.delete(t)
    session.commit()
    return True


def mark_template_used(session: Session, template_id: int) -> None:
    t = session.get(StudyTemplate, template_id)
    if t:
        t.last_run_at = datetime.utcnow()
        t.run_count = (t.run_count or 0) + 1
        session.commit()
