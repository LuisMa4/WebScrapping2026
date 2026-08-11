"""Tests de la configuracion de la automatizacion semanal (AutomationSettings)."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database import repository as repo


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


class TestGetAutomationSettings:
    def test_creates_default_row_when_missing(self, session):
        settings = repo.get_automation_settings(session)
        assert settings.id == 1
        assert settings.enabled is False
        assert settings.drive_folder_id == repo.DEFAULT_AUTOMATION_DRIVE_FOLDER_ID
        assert settings.template_ids == repo.DEFAULT_AUTOMATION_TEMPLATE_IDS

    def test_returns_same_row_on_second_call(self, session):
        first = repo.get_automation_settings(session)
        repo.set_automation_enabled(session, True)
        second = repo.get_automation_settings(session)
        assert second.id == first.id
        assert second.enabled is True


class TestSetAutomationEnabled:
    def test_toggles_on(self, session):
        settings = repo.set_automation_enabled(session, True)
        assert settings.enabled is True

    def test_toggles_off(self, session):
        repo.set_automation_enabled(session, True)
        settings = repo.set_automation_enabled(session, False)
        assert settings.enabled is False


class TestRecordAutomationRun:
    def test_updates_status_fields(self, session):
        settings = repo.record_automation_run(session, status="success", message="4/4 OK")
        assert settings.last_run_status == "success"
        assert settings.last_run_message == "4/4 OK"
        assert settings.last_run_at is not None

    def test_overwrites_previous_run(self, session):
        repo.record_automation_run(session, status="failed", message="boom")
        settings = repo.record_automation_run(session, status="success", message="ok now")
        assert settings.last_run_status == "success"
        assert settings.last_run_message == "ok now"
