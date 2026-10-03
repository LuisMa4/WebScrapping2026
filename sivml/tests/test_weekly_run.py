"""Tests del orquestador de la automatizacion semanal (weekly_run.py)."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import json
import time
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import weekly_run
from database.session import Base
from database import repository as repo
from database.models import StudyTemplate
from integrations.google_drive import UploadResult


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
    monkeypatch.setattr(weekly_run, "SessionLocal", TestSessionLocal)


@pytest.fixture(autouse=True)
def patch_lock_path(monkeypatch, tmp_path):
    # Nunca tocar el lock file real del proyecto desde un test -- usa uno
    # aislado en tmp_path, distinto por test.
    monkeypatch.setattr(weekly_run, "_LOCK_PATH", tmp_path / ".weekly_run.lock")


def _seed_template(session, tid: int, name: str) -> None:
    tpl = StudyTemplate(
        id=tid, name=name, academic_program="Test",
        keywords_json=json.dumps(["derecho"]), cities_json=json.dumps(["Lima"]),
        portals_json=json.dumps(["computrabajo"]), max_pages=5,
        delay_min=0.0, delay_max=0.0, headless=True, created_at=datetime.utcnow(),
    )
    session.add(tpl)
    session.commit()


def _seed_default_templates(session) -> None:
    for tid, name in [
        (8, "Ingenieria Civil"), (9, "Derecho Civil"),
        (10, "Derecho Constitucional"), (11, "Derecho Administrativo"),
    ]:
        _seed_template(session, tid, name)


class TestRunWeeklyAutomationDisabled:
    def test_does_nothing_when_disabled(self, session, monkeypatch):
        repo.set_automation_enabled(session, False)
        called = []
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: called.append(a))

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is False
        assert called == []


class TestRunWeeklyAutomationEnabled:
    def test_runs_all_four_configured_templates_with_a_7_day_range(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")

        run_calls = []

        def fake_execute_study(cfg, study_id, dry_run):
            run_calls.append(cfg)
            return None

        monkeypatch.setattr(weekly_run.study_runner, "execute_study", fake_execute_study)

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is True
        assert len(run_calls) == 4
        expected_from = date.today() - timedelta(days=7)
        expected_to = date.today()
        for cfg in run_calls:
            assert cfg.date_from == expected_from
            assert cfg.date_to == expected_to

    def test_isolates_a_failing_template_and_still_runs_the_others(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")

        def flaky_execute_study(cfg, study_id, dry_run):
            if "Derecho Civil" in cfg.study_name:
                raise RuntimeError("portal caido")
            return None

        monkeypatch.setattr(weekly_run.study_runner, "execute_study", flaky_execute_study)

        summary = weekly_run.run_weekly_automation()

        assert len(summary["results"]) == 4
        errors = [r[3] for r in summary["results"] if r[3] is not None]
        assert len(errors) == 1
        assert "portal caido" in errors[0]

    def test_skips_a_template_id_that_no_longer_exists(self, session, monkeypatch, tmp_path):
        _seed_template(session, 8, "Ingenieria Civil")  # solo sembramos 1 de las 4
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        summary = weekly_run.run_weekly_automation()

        missing = [r for r in summary["results"] if r[3] == "plantilla eliminada"]
        assert len(missing) == 3

    def test_uploads_generated_excels_when_credentials_file_exists(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)

        creds_path = tmp_path / "creds.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", creds_path)

        excel = tmp_path / "SIVML_fake.xlsx"
        excel.write_text("fake")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: excel)

        upload_calls = []

        def fake_upload(credentials_path, parent_folder_id, date_str, file_paths):
            upload_calls.append((credentials_path, parent_folder_id, date_str, file_paths))
            return UploadResult(folder_id="f1", folder_url="https://drive/f1", uploaded=["id1"] * len(file_paths), failed=[])

        monkeypatch.setattr(weekly_run.google_drive, "upload_files_to_dated_folder", fake_upload)

        summary = weekly_run.run_weekly_automation()

        assert len(upload_calls) == 1
        _, parent_id, date_str, paths = upload_calls[0]
        assert parent_id == repo.DEFAULT_AUTOMATION_DRIVE_FOLDER_ID
        assert date_str == date.today().isoformat()
        assert len(paths) == 4
        assert summary["upload"].uploaded == ["id1"] * 4

    def test_skips_upload_when_credentials_file_missing(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "does_not_exist.json")

        excel = tmp_path / "SIVML_fake.xlsx"
        excel.write_text("fake")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: excel)

        called = []
        monkeypatch.setattr(
            weekly_run.google_drive, "upload_files_to_dated_folder",
            lambda **kw: called.append(kw),
        )

        summary = weekly_run.run_weekly_automation()

        assert called == []
        assert summary["upload"] is None
        assert "credenciales" in summary["message"].lower()

    def test_a_failing_create_study_does_not_abort_the_remaining_templates(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")

        real_create_study = repo.create_study
        call_count = {"n": 0}

        def flaky_create_study(session, config, config_path=None, status="running", dry_run=False):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("commit fallido")
            return real_create_study(session, config, config_path=config_path, status=status, dry_run=dry_run)

        monkeypatch.setattr(weekly_run.repo, "create_study", flaky_create_study)

        execute_calls = []
        monkeypatch.setattr(
            weekly_run.study_runner, "execute_study",
            lambda cfg, study_id, dry_run: execute_calls.append(cfg.study_name) or None,
        )

        record_statuses = []
        real_record = repo.record_automation_run

        def spy_record(session, status, message):
            record_statuses.append(status)
            return real_record(session, status=status, message=message)

        monkeypatch.setattr(weekly_run.repo, "record_automation_run", spy_record)

        summary = weekly_run.run_weekly_automation()

        # (1) all 4 templates got an entry in results, despite the 2nd one's
        # create_study raising.
        assert len(summary["results"]) == 4

        # (2) the templates AFTER the failing one still had execute_study
        # called -- the loop did not abort mid-way.
        assert len(execute_calls) == 3

        # (3) record_automation_run was still called with a non-None status.
        assert record_statuses
        assert record_statuses[0] is not None

    def test_records_the_run_result_in_automation_settings(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        weekly_run.run_weekly_automation()

        settings = repo.get_automation_settings(session)
        assert settings.last_run_at is not None
        assert settings.last_run_status in ("success", "partial", "failed")
        assert "4/4" in settings.last_run_message


class TestNeedsCatchupRun:
    """
    _needs_catchup_run() decide si el disparador de respaldo "al iniciar
    sesion" debe correr -- True si no ha corrido nada esta semana (desde el
    lunes mas reciente), False si ya corrio.
    """

    def test_true_when_never_run(self):
        settings = type("S", (), {"last_run_at": None})()
        assert weekly_run._needs_catchup_run(settings) is True

    def test_false_when_already_ran_this_week(self):
        today = date.today()
        most_recent_monday = today - timedelta(days=today.weekday())
        settings = type("S", (), {"last_run_at": datetime.combine(most_recent_monday, datetime.min.time())})()
        assert weekly_run._needs_catchup_run(settings) is False

    def test_true_when_last_run_was_before_this_week(self):
        today = date.today()
        most_recent_monday = today - timedelta(days=today.weekday())
        last_week = most_recent_monday - timedelta(days=1)
        settings = type("S", (), {"last_run_at": datetime.combine(last_week, datetime.min.time())})()
        assert weekly_run._needs_catchup_run(settings) is True


class TestMainCatchupSkip:
    def test_main_skips_run_weekly_automation_when_already_ran_this_week(self, session, monkeypatch, tmp_path):
        repo.set_automation_enabled(session, True)
        repo.record_automation_run(session, status="success", message="ya corrio")

        called = []
        monkeypatch.setattr(weekly_run, "run_weekly_automation", lambda: called.append(1))
        monkeypatch.setattr(weekly_run, "ROOT", tmp_path)

        weekly_run.main()

        assert called == []

    def test_main_runs_when_not_yet_run_this_week(self, session, monkeypatch, tmp_path):
        repo.set_automation_enabled(session, True)
        today = date.today()
        most_recent_monday = today - timedelta(days=today.weekday())
        last_week = most_recent_monday - timedelta(days=7)
        settings = repo.get_automation_settings(session)
        settings.last_run_at = datetime.combine(last_week, datetime.min.time())
        session.commit()

        called = []
        monkeypatch.setattr(weekly_run, "run_weekly_automation", lambda: called.append(1) or {"message": "ok"})
        monkeypatch.setattr(weekly_run, "ROOT", tmp_path)

        weekly_run.main()

        assert called == [1]


class TestOverlapLock:
    """
    run_weekly_automation() usa un lock de archivo para que el disparador
    de respaldo (cada 30 min) no lance una segunda corrida mientras una
    anterior (que puede tardar horas) todavia esta en curso.
    """

    def test_skips_run_when_lock_is_fresh(self, session, monkeypatch):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        weekly_run._LOCK_PATH.write_text("12345", encoding="utf-8")

        called = []
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: called.append(1))

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is False
        assert called == []
        assert "progreso" in summary["message"].lower()

    def test_runs_when_lock_is_stale(self, session, monkeypatch):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", weekly_run._LOCK_PATH.parent / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        weekly_run._LOCK_PATH.write_text("12345", encoding="utf-8")
        stale_time = time.time() - weekly_run._LOCK_STALE_SECONDS - 60
        os.utime(weekly_run._LOCK_PATH, (stale_time, stale_time))

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is True

    def test_releases_lock_after_a_normal_run(self, session, monkeypatch):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", weekly_run._LOCK_PATH.parent / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        weekly_run.run_weekly_automation()

        assert not weekly_run._LOCK_PATH.exists()

    def test_releases_lock_even_when_disabled(self, session):
        repo.set_automation_enabled(session, False)

        weekly_run.run_weekly_automation()

        assert not weekly_run._LOCK_PATH.exists()

    def test_second_call_can_run_after_first_releases_the_lock(self, session, monkeypatch):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", weekly_run._LOCK_PATH.parent / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        first = weekly_run.run_weekly_automation()
        second = weekly_run.run_weekly_automation()

        assert first["ran"] is True
        assert second["ran"] is True
