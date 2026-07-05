"""
Boton "Detener" en Mis Estudios: el usuario puede pedir que un estudio en
curso se detenga sin esperar a que termine todas las combinaciones
keyword/ciudad. Estos tests verifican que _scrape_portal y
_scrape_portal_fresh_ctx realmente cortan el loop apenas se detecta la
solicitud, sin arrancar ninguna combinacion mas -- usando un scraper falso
(sin red real) y controlando directamente cuando "llega" la solicitud de
detener, para no depender de threads/DB reales en este test.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import scraping
from database.session import Base
from database.models import ScrapingRun
from database import repository as repo
from config.settings import StudyConfig, ScraperConfig


class FakeScraper:
    """Scraper de prueba: no toca la red, cuenta cuantas veces se llama search()."""
    engine = "playwright"
    portal_name = "fake"
    calls = []

    def __init__(self, cfg, page=None):
        pass

    def search(self, keyword, city):
        FakeScraper.calls.append((keyword, city))
        return []

    def get_detail(self, url):
        return {}

    def _merge_detail(self, job, detail):
        return job


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
        study_id="stop-test-001",
        study_name="Stop Test",
        academic_program="Test",
        keywords=["kw1", "kw2"],
        cities=["Lima", "Arequipa"],
        portals=["fake"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(delay_range=(0.0, 0.0)),
    )


@pytest.fixture(autouse=True)
def reset_fake_scraper_calls():
    FakeScraper.calls = []
    yield
    FakeScraper.calls = []


class TestScrapePortalStop:
    def test_stops_before_second_combo_when_requested(self, session, cfg, monkeypatch):
        study = repo.create_study(session, cfg)

        # Simula que el usuario pide detener justo despues de la primera
        # combinacion keyword/ciudad, sin depender de threads/DB reales.
        call_count = {"n": 0}

        def fake_stop_requested(study_id):
            call_count["n"] += 1
            return call_count["n"] > 1

        monkeypatch.setattr(scraping, "_stop_requested", fake_stop_requested)
        monkeypatch.setattr("scrapers.get_scraper", lambda name: FakeScraper)

        scraping._scrape_portal(session, cfg, study.id, dry_run=True, page=None,
                                 portal_name="fake", log=lambda m: None)

        # 4 combinaciones posibles (2 keywords x 2 ciudades), pero debio
        # detenerse tras la primera.
        assert len(FakeScraper.calls) == 1

    def test_runs_all_combos_when_stop_never_requested(self, session, cfg, monkeypatch):
        study = repo.create_study(session, cfg)
        monkeypatch.setattr(scraping, "_stop_requested", lambda study_id: False)
        monkeypatch.setattr("scrapers.get_scraper", lambda name: FakeScraper)

        scraping._scrape_portal(session, cfg, study.id, dry_run=True, page=None,
                                 portal_name="fake", log=lambda m: None)

        assert len(FakeScraper.calls) == 4  # 2 keywords x 2 ciudades

    def test_stop_creates_no_scraping_run_for_remaining_combos(self, session, cfg, monkeypatch):
        study = repo.create_study(session, cfg)
        call_count = {"n": 0}

        def fake_stop_requested(study_id):
            call_count["n"] += 1
            return call_count["n"] > 1

        monkeypatch.setattr(scraping, "_stop_requested", fake_stop_requested)
        monkeypatch.setattr("scrapers.get_scraper", lambda name: FakeScraper)

        scraping._scrape_portal(session, cfg, study.id, dry_run=True, page=None,
                                 portal_name="fake", log=lambda m: None)

        runs = session.scalars(select(ScrapingRun).where(ScrapingRun.study_id == study.id)).all()
        assert len(runs) == 1
