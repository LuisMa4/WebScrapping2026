import os
import pytest
from datetime import datetime, date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database import repository as repo
from database.models import Job
from config.settings import StudyConfig, ScraperConfig
from scrapers.base import ScrapedJob
from processing.deduplicator import run_exact_dedup


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def cfg():
    return StudyConfig(
        study_id="dedup-test-001",
        study_name="Dedup Test",
        academic_program="Test",
        keywords=["analista"],
        cities=["Lima"],
        portals=["computrabajo"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(),
    )


def _raw_job(source_id, portal="computrabajo", title="Médico", company="MINSA", city="Lima"):
    return ScrapedJob(
        source_id=source_id,
        portal=portal,
        url=f"https://example.com/{source_id}",
        scraped_at=datetime.utcnow(),
        title=title,
        company=company,
        city=city,
        study_id="dedup-test-001",
        keyword_matched="salud",
    )


class TestExactDedup:
    def test_two_identical_become_one_job(self, session, cfg):
        repo.create_study(session, cfg)

        # Misma oferta en dos portales
        repo.upsert_raw_job(session, _raw_job("s1", portal="computrabajo"))
        repo.upsert_raw_job(session, _raw_job("s2", portal="indeed"))

        stats = run_exact_dedup(session, cfg.study_id)
        assert stats["jobs_created"] == 1
        assert stats["duplicates_marked"] == 1

    def test_two_different_become_two_jobs(self, session, cfg):
        repo.create_study(session, cfg)

        repo.upsert_raw_job(session, _raw_job("a1", title="Médico", company="MINSA"))
        repo.upsert_raw_job(session, _raw_job("a2", title="Enfermero", company="EsSalud"))

        stats = run_exact_dedup(session, cfg.study_id)
        assert stats["jobs_created"] == 2
        assert stats["duplicates_marked"] == 0

    def test_idempotent_calling_twice_does_not_duplicate_jobs(self, session, cfg):
        """
        Regresion: llamar run_exact_dedup() dos veces sobre el mismo estudio
        (ej. el usuario presiona 'Procesar' mas de una vez en el dashboard, o
        el flujo automatico de scraping ya lo corrio y luego se vuelve a llamar)
        NO debe duplicar los Jobs creados.
        """
        repo.create_study(session, cfg)
        repo.upsert_raw_job(session, _raw_job("a1", title="Médico", company="MINSA"))
        repo.upsert_raw_job(session, _raw_job("a2", title="Enfermero", company="EsSalud"))

        stats1 = run_exact_dedup(session, cfg.study_id)
        assert stats1["jobs_created"] == 2

        stats2 = run_exact_dedup(session, cfg.study_id)
        assert stats2["jobs_created"] == 0, "La segunda llamada no debe crear Jobs nuevos"

        total_jobs = session.query(Job).filter(Job.study_id == cfg.study_id).count()
        assert total_jobs == 2, f"Debe haber exactamente 2 Jobs, no {total_jobs}"

    def test_idempotent_three_calls_still_two_jobs(self, session, cfg):
        repo.create_study(session, cfg)
        repo.upsert_raw_job(session, _raw_job("a1", title="Médico", company="MINSA"))
        repo.upsert_raw_job(session, _raw_job("a2", title="Enfermero", company="EsSalud"))

        run_exact_dedup(session, cfg.study_id)
        run_exact_dedup(session, cfg.study_id)
        run_exact_dedup(session, cfg.study_id)

        total_jobs = session.query(Job).filter(Job.study_id == cfg.study_id).count()
        assert total_jobs == 2

    def test_new_raw_jobs_after_dedup_are_still_processed(self, session, cfg):
        """Un re-scraping que agrega NUEVOS raw_jobs al mismo estudio si debe procesarse."""
        repo.create_study(session, cfg)
        repo.upsert_raw_job(session, _raw_job("a1", title="Médico", company="MINSA"))

        stats1 = run_exact_dedup(session, cfg.study_id)
        assert stats1["jobs_created"] == 1

        # Simular re-scraping: llega una oferta nueva
        repo.upsert_raw_job(session, _raw_job("a2", title="Enfermero", company="EsSalud"))

        stats2 = run_exact_dedup(session, cfg.study_id)
        assert stats2["jobs_created"] == 1, "Solo el raw_job nuevo debe generar un Job"

        total_jobs = session.query(Job).filter(Job.study_id == cfg.study_id).count()
        assert total_jobs == 2
