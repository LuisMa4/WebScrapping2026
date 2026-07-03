import pytest
from datetime import datetime, date

from scrapers.base import ScrapedJob
from config.settings import StudyConfig, ScraperConfig


@pytest.fixture()
def cfg():
    return StudyConfig(
        study_id="scraper-test-001",
        study_name="Scraper Test",
        academic_program="Test",
        keywords=["analista de datos"],
        cities=["Lima"],
        portals=["computrabajo"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(delay_range=(0.0, 0.0)),  # sin espera en tests
    )


class TestScrapedJobDataclass:
    def test_required_fields(self):
        job = ScrapedJob(
            source_id="abc123",
            portal="computrabajo",
            url="https://example.com/job/1",
            scraped_at=datetime.utcnow(),
            title="Analista de Datos",
        )
        assert job.source_id == "abc123"
        assert job.company is None
        assert job.salary_raw is None
        assert job.study_id == ""

    def test_optional_fields_default_none(self):
        job = ScrapedJob(
            source_id="x", portal="x", url="x",
            scraped_at=datetime.utcnow(), title="x"
        )
        for field in ("company", "city", "country", "description_raw",
                      "salary_raw", "modality_raw", "contract_raw",
                      "experience_raw", "education_raw"):
            assert getattr(job, field) is None, f"Campo {field!r} debería ser None"


class TestBuildSourceId:
    def test_consistent_hash(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        url = "https://pe.computrabajo.com/oferta/abc123"
        id1 = scraper._build_source_id(url)
        id2 = scraper._build_source_id(url)
        assert id1 == id2
        assert len(id1) == 32  # MD5 hex

    def test_different_urls_different_ids(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        id1 = scraper._build_source_id("https://example.com/1")
        id2 = scraper._build_source_id("https://example.com/2")
        assert id1 != id2


class FakePage:
    """Simula page.goto() fallando N veces antes de tener exito, sin red real."""

    def __init__(self, fail_times: int, exc_cls=Exception):
        self.fail_times = fail_times
        self.exc_cls = exc_cls
        self.calls = 0

    def goto(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc_cls(f"net::ERR_NETWORK_IO_SUSPENDED at {url}")
        return None


class TestGotoWithRetry:
    """
    scraping.py corre portales en paralelo con hasta 4 navegadores Chromium
    simultaneos; bajo esa carga, page.goto() ocasionalmente falla con un
    error de red transitorio (ERR_NETWORK_IO_SUSPENDED). _goto_with_retry
    debe reintentar una vez antes de rendirse.
    """

    def test_succeeds_first_try_no_retry_needed(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        page = FakePage(fail_times=0)
        scraper._goto_with_retry(page, "https://example.com", timeout=5000, retry_delay=0)
        assert page.calls == 1

    def test_retries_once_after_transient_failure(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        page = FakePage(fail_times=1)
        scraper._goto_with_retry(page, "https://example.com", timeout=5000, retry_delay=0)
        assert page.calls == 2

    def test_raises_after_exhausting_retries(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        page = FakePage(fail_times=5)
        with pytest.raises(Exception, match="ERR_NETWORK_IO_SUSPENDED"):
            scraper._goto_with_retry(page, "https://example.com", timeout=5000, retry_delay=0)
        assert page.calls == 2  # intento original + 1 reintento, luego se rinde


class TestTimeBudget:
    """
    Portales lentos (LinkedIn con su anti-bot) pueden tardar minutos por
    pagina. _time_budget_exceeded() es el corte de seguridad que cada
    search() de portal consulta entre paginas para no colgarse indefinidamente.
    """

    def test_not_exceeded_when_just_started(self, cfg):
        import time
        from scrapers.computrabajo import ComputrabajoScraper
        scraper = ComputrabajoScraper(cfg, page=None)
        assert scraper._time_budget_exceeded(time.time()) is False

    def test_exceeded_when_past_limit(self, cfg):
        import time
        from dataclasses import replace
        from scrapers.computrabajo import ComputrabajoScraper
        fast_cfg = replace(cfg, scraper=replace(cfg.scraper, max_search_seconds=0.01))
        scraper = ComputrabajoScraper(fast_cfg, page=None)
        started = time.time() - 1.0  # hace 1 segundo, ya paso el limite de 0.01s
        assert scraper._time_budget_exceeded(started) is True

    def test_default_budget_is_seven_minutes(self, cfg):
        assert cfg.scraper.max_search_seconds == 420.0


class TestScraperRegistry:
    def test_all_portals_registered(self):
        from scrapers import REGISTRY
        expected = {"computrabajo", "indeed", "bumeran", "laborum", "jooble", "linkedin"}
        assert expected == set(REGISTRY.keys())

    def test_get_scraper_known(self):
        from scrapers import get_scraper
        from scrapers.computrabajo import ComputrabajoScraper
        assert get_scraper("computrabajo") is ComputrabajoScraper

    def test_get_scraper_unknown(self):
        from scrapers import get_scraper
        with pytest.raises(ValueError, match="desconocido"):
            get_scraper("portal_inexistente")
