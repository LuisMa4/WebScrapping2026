"""Tests de repositorio de plantillas."""
import os
import pytest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

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


def _sample_data(**overrides) -> dict:
    base = {
        "name": "Salud Publica Lima",
        "academic_program": "Maestria en Salud Publica",
        "keywords": ["salud publica", "epidemiologia"],
        "cities": ["Lima", "Arequipa"],
        "portals": ["computrabajo", "bumeran"],
        "max_pages": 10,
        "delay_min": 2.0,
        "delay_max": 5.0,
        "headless": True,
        "notes": "Busqueda trimestral",
    }
    base.update(overrides)
    return base


class TestCreateTemplate:
    def test_creates_and_persists(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.id is not None
        assert t.name == "Salud Publica Lima"
        assert t.run_count == 0
        assert t.last_run_at is None

    def test_keywords_serialized_correctly(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.keywords == ["salud publica", "epidemiologia"]

    def test_cities_serialized_correctly(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.cities == ["Lima", "Arequipa"]

    def test_portals_serialized_correctly(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.portals == ["computrabajo", "bumeran"]

    def test_created_at_set(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.created_at is not None

    def test_notes_stored(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.notes == "Busqueda trimestral"

    def test_notes_optional(self, session):
        data = _sample_data()
        data.pop("notes")
        t = repo.create_template(session, data)
        assert t.notes is None


class TestListTemplates:
    def test_returns_all(self, session):
        repo.create_template(session, _sample_data(name="A"))
        repo.create_template(session, _sample_data(name="B"))
        result = repo.list_templates(session)
        assert len(result) == 2

    def test_empty_when_none(self, session):
        assert repo.list_templates(session) == []

    def test_most_recently_used_first(self, session):
        from datetime import datetime, timedelta
        t1 = repo.create_template(session, _sample_data(name="Antigua"))
        t2 = repo.create_template(session, _sample_data(name="Reciente"))
        # Simular que t2 se uso mas recientemente
        t2.last_run_at = datetime.utcnow()
        t1.last_run_at = datetime.utcnow() - timedelta(days=10)
        session.commit()
        result = repo.list_templates(session)
        assert result[0].name == "Reciente"


class TestGetTemplate:
    def test_returns_existing(self, session):
        t = repo.create_template(session, _sample_data())
        found = repo.get_template(session, t.id)
        assert found is not None
        assert found.id == t.id

    def test_returns_none_for_missing(self, session):
        assert repo.get_template(session, 9999) is None


class TestUpdateTemplate:
    def test_updates_name(self, session):
        t = repo.create_template(session, _sample_data())
        repo.update_template(session, t.id, {"name": "Nuevo Nombre"})
        updated = repo.get_template(session, t.id)
        assert updated.name == "Nuevo Nombre"

    def test_updates_keywords(self, session):
        t = repo.create_template(session, _sample_data())
        repo.update_template(session, t.id, {"keywords": ["sistemas", "software"]})
        updated = repo.get_template(session, t.id)
        assert updated.keywords == ["sistemas", "software"]

    def test_returns_none_for_missing(self, session):
        result = repo.update_template(session, 9999, {"name": "X"})
        assert result is None

    def test_partial_update_preserves_other_fields(self, session):
        t = repo.create_template(session, _sample_data())
        original_portals = t.portals
        repo.update_template(session, t.id, {"name": "Solo Nombre"})
        updated = repo.get_template(session, t.id)
        assert updated.portals == original_portals


class TestDeleteTemplate:
    def test_deletes_existing(self, session):
        t = repo.create_template(session, _sample_data())
        result = repo.delete_template(session, t.id)
        assert result is True
        assert repo.get_template(session, t.id) is None

    def test_returns_false_for_missing(self, session):
        assert repo.delete_template(session, 9999) is False

    def test_does_not_affect_other_templates(self, session):
        t1 = repo.create_template(session, _sample_data(name="A"))
        t2 = repo.create_template(session, _sample_data(name="B"))
        repo.delete_template(session, t1.id)
        assert repo.get_template(session, t2.id) is not None


class TestMarkTemplateUsed:
    def test_increments_run_count(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.run_count == 0
        repo.mark_template_used(session, t.id)
        repo.mark_template_used(session, t.id)
        updated = repo.get_template(session, t.id)
        assert updated.run_count == 2

    def test_sets_last_run_at(self, session):
        t = repo.create_template(session, _sample_data())
        assert t.last_run_at is None
        repo.mark_template_used(session, t.id)
        updated = repo.get_template(session, t.id)
        assert updated.last_run_at is not None

    def test_no_error_for_missing_id(self, session):
        repo.mark_template_used(session, 9999)  # no debe lanzar excepcion
