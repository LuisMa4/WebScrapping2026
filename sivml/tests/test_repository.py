import os
import pytest
from datetime import datetime, date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database.models import Study, RawJob, Job, ScrapingRun
from database import repository as repo
from config.settings import StudyConfig, ScraperConfig
from scrapers.base import ScrapedJob


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def study_config():
    return StudyConfig(
        study_id="test-study-001",
        study_name="Test Study",
        academic_program="Prueba",
        keywords=["analista"],
        cities=["Lima"],
        portals=["computrabajo"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(),
    )


class TestCreateStudy:
    def test_creates_study(self, session, study_config):
        study = repo.create_study(session, study_config)
        assert study.id == study_config.study_id
        assert study.status == "running"
        assert study.started_at is not None

    def test_finish_study(self, session, study_config):
        study = repo.create_study(session, study_config)
        repo.finish_study(session, study.id, success=True)
        updated = repo.get_study(session, study.id)
        assert updated.status == "completed"
        assert updated.finished_at is not None


class TestUpsertRawJob:
    def _make_job(self, url="https://example.com/1"):
        return ScrapedJob(
            source_id="src-001",
            portal="computrabajo",
            url=url,
            scraped_at=datetime.utcnow(),
            title="Médico Salubrista",
            company="Ministerio de Salud",
            city="Lima",
            study_id="test-study-001",
            keyword_matched="salud pública",
        )

    def test_inserts_new(self, session, study_config):
        repo.create_study(session, study_config)
        job, is_new = repo.upsert_raw_job(session, self._make_job())
        assert is_new is True
        assert job.id is not None

    def test_skips_duplicate(self, session, study_config):
        repo.create_study(session, study_config)
        job1, _ = repo.upsert_raw_job(session, self._make_job())
        job2, is_new = repo.upsert_raw_job(session, self._make_job())
        assert is_new is False
        assert job1.id == job2.id

    def test_get_raw_jobs(self, session, study_config):
        repo.create_study(session, study_config)
        repo.upsert_raw_job(session, self._make_job())
        jobs = repo.get_raw_jobs_for_study(session, study_config.study_id)
        assert len(jobs) == 1

    def test_same_offer_in_two_different_studies_both_get_it(self, session, study_config):
        """
        Regresion: la misma oferta (portal+source_id) debe poder pertenecer a
        ESTUDIOS DISTINTOS (ej. al re-ejecutar una plantilla en una fecha
        posterior y la oferta sigue publicada). Antes del fix, el segundo
        estudio mostraba 0 ofertas porque el unique constraint era global.
        """
        repo.create_study(session, study_config)
        job1, is_new1 = repo.upsert_raw_job(session, self._make_job())
        assert is_new1 is True

        other_config = StudyConfig(
            study_id="test-study-002",
            study_name="Re-ejecucion mensual",
            academic_program="Prueba",
            keywords=["analista"],
            cities=["Lima"],
            portals=["computrabajo"],
            date_from=date(2026, 2, 1),
            date_to=date(2026, 2, 28),
            scraper=ScraperConfig(),
        )
        repo.create_study(session, other_config)

        job_repeated = ScrapedJob(
            source_id="src-001",  # MISMA oferta
            portal="computrabajo",
            url="https://example.com/1",
            scraped_at=datetime.utcnow(),
            title="Médico Salubrista",
            company="Ministerio de Salud",
            city="Lima",
            study_id="test-study-002",  # ESTUDIO DISTINTO
            keyword_matched="salud pública",
        )
        job2, is_new2 = repo.upsert_raw_job(session, job_repeated)

        assert is_new2 is True, "La misma oferta debe registrarse como nueva en un estudio distinto"
        assert job1.id != job2.id, "Cada estudio debe tener su propia fila de RawJob"

        jobs_study1 = repo.get_raw_jobs_for_study(session, "test-study-001")
        jobs_study2 = repo.get_raw_jobs_for_study(session, "test-study-002")
        assert len(jobs_study1) == 1
        assert len(jobs_study2) == 1

    def test_same_offer_same_study_still_deduped(self, session, study_config):
        """El constraint sigue previniendo duplicados DENTRO del mismo estudio."""
        repo.create_study(session, study_config)
        job1, is_new1 = repo.upsert_raw_job(session, self._make_job())
        job2, is_new2 = repo.upsert_raw_job(session, self._make_job())
        assert is_new1 is True
        assert is_new2 is False
        assert job1.id == job2.id


class TestScrapingRuns:
    def test_start_and_finish(self, session, study_config):
        repo.create_study(session, study_config)
        run = repo.start_scraping_run(session, study_config.study_id, "computrabajo", "analista", "Lima")
        assert run.id is not None
        assert run.status == "running"

        repo.finish_scraping_run(session, run.id, records_found=10, records_new=8)
        updated = session.get(ScrapingRun, run.id)
        assert updated.status == "completed"
        assert updated.records_found == 10


class TestGetLastActivity:
    """
    Deteccion de estudios atascados: cuando el proceso de scraping muere a
    mitad de camino (crash, conflicto de puertos, reinicio de Streamlit por
    cambio de codigo), el estudio queda 'running' para siempre en la BD sin
    que nadie lo marque como fallido. get_last_activity + is_study_stale
    permiten detectar esto automaticamente en el dashboard.
    """

    def test_no_runs_returns_none(self, session, study_config):
        study = repo.create_study(session, study_config)
        assert repo.get_last_activity(session, study.id) is None

    def test_returns_most_recent_timestamp(self, session, study_config):
        study = repo.create_study(session, study_config)
        r1 = repo.start_scraping_run(session, study.id, "computrabajo", "kw", "Lima")
        repo.finish_scraping_run(session, r1.id, records_found=1, records_new=1)
        r2 = repo.start_scraping_run(session, study.id, "bumeran", "kw", "Lima")
        last = repo.get_last_activity(session, study.id)
        assert last == r2.started_at


class TestIsStudyStale:
    def test_running_study_with_recent_activity_not_stale(self, session, study_config):
        study = repo.create_study(session, study_config)
        now = datetime.utcnow()
        assert repo.is_study_stale(study, last_activity=now, threshold_minutes=15, now=now) is False

    def test_running_study_with_old_activity_is_stale(self, session, study_config):
        from datetime import timedelta
        study = repo.create_study(session, study_config)
        now = datetime.utcnow()
        old_activity = now - timedelta(minutes=20)
        assert repo.is_study_stale(study, last_activity=old_activity, threshold_minutes=15, now=now) is True

    def test_running_study_just_under_threshold_not_stale(self, session, study_config):
        from datetime import timedelta
        study = repo.create_study(session, study_config)
        now = datetime.utcnow()
        recent_activity = now - timedelta(minutes=10)
        assert repo.is_study_stale(study, last_activity=recent_activity, threshold_minutes=15, now=now) is False

    def test_completed_study_never_stale(self, session, study_config):
        from datetime import timedelta
        study = repo.create_study(session, study_config)
        repo.finish_study(session, study.id, success=True)
        updated = repo.get_study(session, study.id)
        now = datetime.utcnow()
        old_activity = now - timedelta(hours=5)
        assert repo.is_study_stale(updated, last_activity=old_activity, threshold_minutes=15, now=now) is False

    def test_no_activity_falls_back_to_study_started_at(self, session, study_config):
        from datetime import timedelta
        study = repo.create_study(session, study_config)
        now = study.started_at + timedelta(minutes=20)
        assert repo.is_study_stale(study, last_activity=None, threshold_minutes=15, now=now) is True


class TestMarkStudyFailed:
    def test_marks_study_and_running_runs_as_failed(self, session, study_config):
        study = repo.create_study(session, study_config)
        run = repo.start_scraping_run(session, study.id, "computrabajo", "kw", "Lima")
        repo.mark_study_failed(session, study.id, reason="test")
        updated = repo.get_study(session, study.id)
        assert updated.status == "failed"
        assert updated.finished_at is not None
        updated_run = session.get(ScrapingRun, run.id)
        assert updated_run.status == "failed"
        assert updated_run.error_message == "test"

    def test_does_not_affect_completed_runs(self, session, study_config):
        study = repo.create_study(session, study_config)
        run = repo.start_scraping_run(session, study.id, "computrabajo", "kw", "Lima")
        repo.finish_scraping_run(session, run.id, records_found=5, records_new=5, success=True)
        repo.mark_study_failed(session, study.id)
        updated_run = session.get(ScrapingRun, run.id)
        assert updated_run.status == "completed"

    def test_missing_study_does_not_raise(self, session):
        repo.mark_study_failed(session, "does-not-exist")


class TestDeleteStudy:
    def _make_job(self, study_id, source_id="src-001"):
        return ScrapedJob(
            source_id=source_id,
            portal="computrabajo",
            url=f"https://example.com/{source_id}",
            scraped_at=datetime.utcnow(),
            title="Analista",
            company="Empresa",
            city="Lima",
            study_id=study_id,
            keyword_matched="analista",
        )

    def test_deletes_study_and_returns_true(self, session, study_config):
        study = repo.create_study(session, study_config)
        assert repo.delete_study(session, study.id) is True
        assert repo.get_study(session, study.id) is None

    def test_missing_study_returns_false(self, session):
        assert repo.delete_study(session, "does-not-exist") is False

    def test_cascades_to_raw_jobs_and_jobs_and_runs(self, session, study_config):
        from processing.deduplicator import run_exact_dedup

        study = repo.create_study(session, study_config)
        repo.upsert_raw_job(session, self._make_job(study.id))
        repo.start_scraping_run(session, study.id, "computrabajo", "analista", "Lima")
        run_exact_dedup(session, study.id)

        assert len(repo.get_raw_jobs_for_study(session, study.id)) == 1
        assert len(repo.get_jobs_for_study(session, study.id)) == 1

        repo.delete_study(session, study.id)

        assert repo.get_raw_jobs_for_study(session, study.id) == []
        assert repo.get_jobs_for_study(session, study.id) == []
        remaining_runs = session.scalars(
            select(ScrapingRun).where(ScrapingRun.study_id == study.id)
        ).all()
        assert remaining_runs == []

    def test_does_not_affect_other_studies(self, session, study_config):
        study_a = repo.create_study(session, study_config)
        other_config = StudyConfig(
            study_id="test-study-002", study_name="Otro estudio", academic_program="Prueba",
            keywords=["analista"], cities=["Lima"], portals=["computrabajo"],
            date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), scraper=ScraperConfig(),
        )
        study_b = repo.create_study(session, other_config)
        repo.upsert_raw_job(session, self._make_job(study_a.id, "src-a"))
        repo.upsert_raw_job(session, self._make_job(study_b.id, "src-b"))

        repo.delete_study(session, study_a.id)

        assert repo.get_study(session, study_b.id) is not None
        assert len(repo.get_raw_jobs_for_study(session, study_b.id)) == 1
