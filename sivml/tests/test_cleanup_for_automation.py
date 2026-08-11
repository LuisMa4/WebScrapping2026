"""
Tests del script de limpieza unica (scripts/cleanup_for_automation.py)
contra una BD de PRUEBA sintetica -- nunca toca sivml.db real. Imita el
patron real encontrado en la BD del usuario: duplicados con/sin "Puno" y
plantillas de prueba viejas.
"""
import json
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database import repository as repo
from database.models import Study, StudyTemplate
from config.settings import StudyConfig, ScraperConfig
from scripts import cleanup_for_automation


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _make_template(session, tid: int, name: str) -> None:
    tpl = StudyTemplate(
        id=tid, name=name, academic_program="Test",
        keywords_json=json.dumps(["x"]), cities_json=json.dumps(["Lima"]),
        portals_json=json.dumps(["computrabajo"]), created_at=datetime.utcnow(),
    )
    session.add(tpl)
    session.commit()


def _make_study(session, study_id: str, name: str) -> None:
    from datetime import date
    cfg = StudyConfig(
        study_id=study_id, study_name=name, academic_program="Test",
        keywords=["x"], cities=["Lima"], portals=["computrabajo"],
        date_from=date(2026, 1, 1), date_to=date(2026, 1, 7),
        scraper=ScraperConfig(),
    )
    repo.create_study(session, cfg, status="completed")


class TestSummarize:
    def test_identifies_templates_to_keep_and_delete(self, session):
        _make_template(session, 4, "Derecho Civil (viejo, con Puno)")
        _make_template(session, 9, "Derecho Civil")
        _make_template(session, 8, "Ingenieria Civil")
        _make_template(session, 10, "Derecho Constitucional")
        _make_template(session, 11, "Derecho Administrativo")
        _make_template(session, 1, "Prueba 1")

        summary = cleanup_for_automation.summarize(session)

        kept_ids = sorted(t.id for t in summary["templates_to_keep"])
        deleted_ids = sorted(t.id for t in summary["templates_to_delete"])
        assert kept_ids == [8, 9, 10, 11]
        assert deleted_ids == [1, 4]

    def test_all_studies_are_marked_for_deletion(self, session):
        _make_template(session, 8, "Ingenieria Civil")
        _make_study(session, "study-1", "Corrida vieja 1")
        _make_study(session, "study-2", "Corrida vieja 2")

        summary = cleanup_for_automation.summarize(session)

        study_ids = sorted(s.id for s in summary["studies_to_delete"])
        assert study_ids == ["study-1", "study-2"]


class TestRunCleanup:
    def test_deletes_everything_not_in_keep_list(self, session):
        _make_template(session, 4, "Derecho Civil (viejo)")
        _make_template(session, 9, "Derecho Civil")
        _make_study(session, "study-1", "Corrida vieja")

        summary = cleanup_for_automation.summarize(session)
        cleanup_for_automation.run_cleanup(session, summary)

        remaining_templates = session.scalars(select(StudyTemplate)).all()
        remaining_studies = session.scalars(select(Study)).all()
        assert [t.id for t in remaining_templates] == [9]
        assert remaining_studies == []


class TestBackupDb:
    def test_creates_a_dated_backup_copy(self, tmp_path):
        db_path = tmp_path / "sivml.db"
        db_path.write_bytes(b"fake sqlite content")

        backup_path = cleanup_for_automation.backup_db(tmp_path)

        assert backup_path.exists()
        assert backup_path.read_bytes() == b"fake sqlite content"
        assert "bak_pre_weekly_automation" in backup_path.name
