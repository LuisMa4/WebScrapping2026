"""
Multiples estudios corriendo a la vez: al enviar un estudio nuevo, si ya hay
MAX_CONCURRENT_STUDIES corriendo, se guarda 'queued' en vez de arrancar de
inmediato. Cuando un estudio termina, se promueve automaticamente el
siguiente en cola (el mismo hilo que termina revisa la cola, sin necesitar
un scheduler aparte).

Los tests reemplazan study_runner.SessionLocal por una sesion de prueba
(mismo engine en memoria que la fixture `session`) para poder verificar el
estado en la BD sin depender de threads reales, y monkeypatchean _spawn /
run_scraping para no lanzar hilos ni tocar la red.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from dataclasses import replace
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import study_runner
from database.session import Base
from database import repository as repo
from config.settings import StudyConfig, ScraperConfig
from scrapers.base import ScrapedJob


@pytest.fixture()
def engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture()
def TestSessionLocal(engine):
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def session(TestSessionLocal):
    s = TestSessionLocal()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def patch_session_local(monkeypatch, TestSessionLocal):
    # study_runner abre su PROPIA session (SessionLocal()) dentro de cada
    # hilo -- para que apunte a la misma BD en memoria que usa el test.
    monkeypatch.setattr(study_runner, "SessionLocal", TestSessionLocal)


@pytest.fixture()
def cfg():
    return StudyConfig(
        study_id="runner-test-001",
        study_name="Runner Test",
        academic_program="Test",
        keywords=["contador"],
        cities=["Lima"],
        portals=["fake"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(delay_range=(0.0, 0.0)),
    )


def _fake_run_scraping_with_result(session, cfg, study_id, dry_run=False, on_progress=None):
    job = ScrapedJob(
        source_id="1", portal="fake", url="https://x.com/1",
        scraped_at=datetime.utcnow(), title="Contador", company="ACME",
        city="Lima", study_id=study_id,
    )
    repo.upsert_raw_job(session, job)


def _fake_run_scraping_no_results(session, cfg, study_id, dry_run=False, on_progress=None):
    pass


def _fake_run_scraping_raises(session, cfg, study_id, dry_run=False, on_progress=None):
    raise RuntimeError("boom")


class TestStartOrQueueStudy:
    def test_starts_immediately_when_under_capacity(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        study = study_runner.start_or_queue_study(session, cfg, dry_run=False)
        assert study.status == "running"
        assert spawned == [study.id]

    def test_queues_when_at_capacity(self, session, cfg, monkeypatch):
        monkeypatch.setattr(study_runner, "_spawn", lambda *a: None)
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 1)
        study_runner.start_or_queue_study(session, replace(cfg, study_id="first"), dry_run=False)
        second = study_runner.start_or_queue_study(session, replace(cfg, study_id="second"), dry_run=False)
        assert second.status == "queued"

    def test_does_not_spawn_thread_when_queued(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 1)
        study_runner.start_or_queue_study(session, replace(cfg, study_id="first"), dry_run=False)
        study_runner.start_or_queue_study(session, replace(cfg, study_id="second"), dry_run=False)
        assert spawned == ["first"]

    def test_third_study_also_queues_behind_second(self, session, cfg, monkeypatch):
        monkeypatch.setattr(study_runner, "_spawn", lambda *a: None)
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 1)
        study_runner.start_or_queue_study(session, replace(cfg, study_id="first"), dry_run=False)
        study_runner.start_or_queue_study(session, replace(cfg, study_id="second"), dry_run=False)
        third = study_runner.start_or_queue_study(session, replace(cfg, study_id="third"), dry_run=False)
        assert third.status == "queued"


class TestExecuteStudy:
    def test_excel_is_exported_before_status_becomes_completed(self, session, cfg, monkeypatch, tmp_path):
        # Regresion: finish_study() (que pone status='completed') se llamaba
        # ANTES de exportar el Excel. Un observador externo (el fragment de
        # Mis Estudios en otra pestana/hilo, sondeando la BD) podia ver el
        # estudio ya 'completed' en una ventana en la que el archivo
        # todavia no existia -- el banner de descarga mostraba "sin
        # ofertas" pese a que si habia resultados. El orden de llamadas
        # real (no solo el resultado final) es lo que importa aqui.
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_with_result)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()

        call_order = []
        real_export = study_runner.export_study_to_excel
        real_finish = repo.finish_study

        def tracking_export(*args, **kwargs):
            call_order.append("export")
            return real_export(*args, **kwargs)

        def tracking_finish(*args, **kwargs):
            call_order.append("finish")
            return real_finish(*args, **kwargs)

        monkeypatch.setattr(study_runner, "export_study_to_excel", tracking_export)
        monkeypatch.setattr(repo, "finish_study", tracking_finish)

        study_runner.execute_study(cfg, study_id, dry_run=False)

        assert call_order == ["export", "finish"]

    def test_marks_completed_and_exports_excel_when_jobs_found(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_with_result)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()  # execute_study abre su propia session (patcheada arriba)

        study_runner.execute_study(cfg, study_id, dry_run=False)

        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, study_id)
        assert updated.status == "completed"
        assert updated.finished_at is not None
        jobs = repo.get_jobs_for_study(check_session, study_id)
        assert len(jobs) == 1
        assert list(tmp_path.glob("*.xlsx")), "debio generarse un Excel"
        check_session.close()

    def test_marks_completed_without_excel_when_no_jobs(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_no_results)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()

        study_runner.execute_study(cfg, study_id, dry_run=False)

        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, study_id)
        assert updated.status == "completed"
        assert list(tmp_path.glob("*.xlsx")) == []
        check_session.close()

    def test_marks_failed_on_exception(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_raises)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()

        study_runner.execute_study(cfg, study_id, dry_run=False)  # no debe propagar la excepcion

        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, study_id)
        assert updated.status == "failed"
        check_session.close()

    def test_marks_stopped_when_stop_was_requested(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_no_results)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        repo.request_stop(session, study_id)
        session.close()

        study_runner.execute_study(cfg, study_id, dry_run=False)

        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, study_id)
        assert updated.status == "stopped"
        check_session.close()


class TestPromoteNextQueued:
    def test_promotes_oldest_queued_when_slot_free(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 1)
        queued = repo.create_study(session, replace(cfg, study_id="queued-1"), status="queued")
        queued_id = queued.id
        session.close()

        study_runner.promote_next_queued()

        assert spawned == [queued_id]
        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, queued_id)
        assert updated.status == "running"
        check_session.close()

    def test_noop_when_no_capacity(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 1)
        repo.create_study(session, replace(cfg, study_id="already-running"))  # ocupa el unico cupo
        repo.create_study(session, replace(cfg, study_id="queued-1"), status="queued")
        session.close()

        study_runner.promote_next_queued()

        assert spawned == []

    def test_noop_when_queue_empty(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        session.close()

        study_runner.promote_next_queued()  # no debe lanzar ni hacer nada

        assert spawned == []

    def test_cancelled_queued_study_is_marked_stopped_without_spawning(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        queued = repo.create_study(session, replace(cfg, study_id="queued-cancel"), status="queued")
        queued_id = queued.id
        repo.request_stop(session, queued_id)
        session.close()

        study_runner.promote_next_queued()

        assert spawned == []
        check_session = study_runner.SessionLocal()
        updated = repo.get_study(check_session, queued_id)
        assert updated.status == "stopped"
        check_session.close()

    def test_promotes_multiple_when_multiple_slots_free(self, session, cfg, monkeypatch):
        spawned = []
        monkeypatch.setattr(study_runner, "_spawn", lambda c, sid, dr: spawned.append(sid))
        monkeypatch.setattr(study_runner, "MAX_CONCURRENT_STUDIES", 2)
        q1 = repo.create_study(session, replace(cfg, study_id="q1"), status="queued")
        q2 = repo.create_study(session, replace(cfg, study_id="q2"), status="queued")
        q1_id, q2_id = q1.id, q2.id
        session.close()

        study_runner.promote_next_queued()

        assert sorted(spawned) == sorted([q1_id, q2_id])
