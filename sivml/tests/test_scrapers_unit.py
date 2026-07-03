"""Tests unitarios de lógica de scrapers sin red."""
import pytest
from datetime import date
from config.settings import StudyConfig, ScraperConfig


@pytest.fixture
def cfg():
    return StudyConfig(
        study_id="unit-test-001",
        study_name="Unit Test",
        academic_program="Test",
        keywords=["analista de datos", "salud pública"],
        cities=["Lima"],
        portals=["computrabajo"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        scraper=ScraperConfig(delay_range=(0.0, 0.0)),
    )


class TestComputrabajoURL:
    def test_slug_basic(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("analista de datos", "Lima", 1)
        assert "trabajo-de-analista-de-datos" in url
        assert "+" not in url

    def test_slug_accents(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("gestión de proyectos", "Lima", 1)
        assert "trabajo-de-" in url

    def test_page_2_adds_param(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("analista", "Lima", 2)
        assert "?p=2" in url

    def test_page_1_no_param(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("analista", "Lima", 1)
        assert "?p=" not in url

    def test_city_included_in_url(self, cfg):
        # Regresion: computrabajo.com.pe ignoraba la ciudad por completo --
        # toda "ciudad" generaba la misma URL nacional generica. El filtro
        # real es /trabajo-de-{keyword}-en-{ciudad} (verificado en vivo,
        # julio 2026).
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("ingenieria", "Arequipa", 1)
        assert "trabajo-de-ingenieria-en-arequipa" in url

    def test_different_cities_produce_different_urls(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url_a = s._build_search_url("ingenieria", "Lima", 1)
        url_b = s._build_search_url("ingenieria", "Cusco", 1)
        assert url_a != url_b

    def test_no_city_omits_location_segment(self, cfg):
        from scrapers.computrabajo import ComputrabajoScraper
        s = ComputrabajoScraper(cfg)
        url = s._build_search_url("ingenieria", "", 1)
        assert "-en-" not in url


class TestIndeedAccentStripping:
    def test_strips_tilde(self, cfg):
        from scrapers.indeed import _strip_accents
        assert _strip_accents("salud pública") == "salud publica"
        assert _strip_accents("gestión") == "gestion"
        assert _strip_accents("administración") == "administracion"
        assert _strip_accents("ingeniero") == "ingeniero"

    def test_url_without_accents(self, cfg):
        from scrapers.indeed import IndeedScraper
        s = IndeedScraper(cfg)
        url = s._build_search_url("salud pública", "Lima", 0)
        assert "%C3%BA" not in url   # ú codificado no debe aparecer
        assert "salud+publica" in url or "salud%20publica" in url

    def test_jk_extraction(self, cfg):
        from scrapers.indeed import IndeedScraper
        import re
        href = "/rc/clk?jk=822a7ecca39c0670&bb=abc"
        jk_match = re.search(r"jk=([a-f0-9]+)", href)
        assert jk_match
        assert jk_match.group(1) == "822a7ecca39c0670"


class TestBumeranURL:
    """
    Regresion: bumeran.com.pe ignora el parametro "?q=" sobre la URL
    generica /empleos-publicados-hace-3-meses.html -- devuelve siempre el
    mismo listado de "publicados recientemente" sin importar el keyword.
    La busqueda real navega a /empleos-busqueda-{slug}.html (verificado
    manualmente contra el buscador del sitio, julio 2026).
    """

    def test_slug_basic(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("analista de datos", "", 1)
        assert "empleos-busqueda-analista-de-datos.html" in url

    def test_slug_accents_stripped(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("salud pública", "", 1)
        assert "salud-publica" in url
        assert "%C3" not in url  # bumeran no reconoce tildes url-encoded

    def test_page_2_adds_param(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("analista", "", 2)
        assert "?page=2" in url

    def test_page_1_no_param(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("analista", "", 1)
        assert "?page=" not in url

    def test_no_longer_uses_broken_q_param(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("analista", "", 1)
        assert "?q=" not in url
        assert "empleos-publicados-hace-3-meses" not in url

    def test_different_keywords_produce_different_urls(self, cfg):
        # Guard contra el bug original: antes del fix, distintos keywords
        # generaban resultados identicos porque la URL no dependia del keyword.
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url_a = s._build_search_url("contador", "", 1)
        url_b = s._build_search_url("ingeniero civil", "", 1)
        assert url_a != url_b

    def test_city_included_in_url(self, cfg):
        # Regresion: bumeran.com.pe tambien ignoraba la ciudad por completo
        # -- toda "ciudad" generaba la misma URL nacional. El filtro real es
        # /empleos-busqueda-{keyword}-en-{ciudad}.html (verificado en vivo,
        # julio 2026).
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("ingenieria", "Arequipa", 1)
        assert "empleos-busqueda-ingenieria-en-arequipa.html" in url

    def test_different_cities_produce_different_urls(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url_a = s._build_search_url("ingenieria", "Lima", 1)
        url_b = s._build_search_url("ingenieria", "Cusco", 1)
        assert url_a != url_b

    def test_no_city_omits_location_segment(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        url = s._build_search_url("ingenieria", "", 1)
        assert "-en-" not in url


class TestBumeranParsing:
    """Prueba el parser con HTML real simplificado."""

    # Estructura real de Bumeran: el <a> envuelve los divs header/data
    FAKE_HTML = """
    <html><body>
    <a href="/empleos/analista-de-datos-senior-techcorp-sac-12345.html" class="card-link">
      <div class="card-wrapper">
        <div id="header-col-job-posting-12345">
          <h2>Analista de Datos Senior</h2>
          <h3>Publicado hace 1 hora</h3>
          <h3>TechCorp SAC</h3>
        </div>
        <div id="data-col-job-posting-12345">Lima, Miraflores | Presencial</div>
      </div>
    </a>
    </body></html>
    """

    def test_extracts_title(self, cfg):
        from scrapers.bumeran import BumeranScraper
        from bs4 import BeautifulSoup
        s = BumeranScraper(cfg)
        soup = BeautifulSoup(self.FAKE_HTML, "lxml")
        header_div = soup.find("div", id="header-col-job-posting-12345")
        job = s._parse_card(soup, header_div)
        assert job is not None
        assert job.title == "Analista de Datos Senior"

    def test_extracts_company(self, cfg):
        from scrapers.bumeran import BumeranScraper
        from bs4 import BeautifulSoup
        s = BumeranScraper(cfg)
        soup = BeautifulSoup(self.FAKE_HTML, "lxml")
        header_div = soup.find("div", id="header-col-job-posting-12345")
        job = s._parse_card(soup, header_div)
        assert job.company == "TechCorp SAC"

    def test_extracts_city(self, cfg):
        from scrapers.bumeran import BumeranScraper
        from bs4 import BeautifulSoup
        s = BumeranScraper(cfg)
        soup = BeautifulSoup(self.FAKE_HTML, "lxml")
        header_div = soup.find("div", id="header-col-job-posting-12345")
        job = s._parse_card(soup, header_div)
        assert job.city is not None
        assert "Lima" in job.city or "Miraflores" in job.city

    def test_source_id_from_job_id(self, cfg):
        from scrapers.bumeran import BumeranScraper
        from bs4 import BeautifulSoup
        s = BumeranScraper(cfg)
        soup = BeautifulSoup(self.FAKE_HTML, "lxml")
        header_div = soup.find("div", id="header-col-job-posting-12345")
        job = s._parse_card(soup, header_div)
        assert job.source_id == "12345"


class TestBumeranDetailParsing:
    """
    Regresion: bumeran.com.pe es una app React sin ids/clases semanticas
    estables. <div id="root"> envuelve TODO (nav + descripcion + footer),
    asi que "elegir el bloque de texto mas grande" sin filtrar siempre
    devolvia el wrapper -- nunca la descripcion real -- sin importar cuanto
    se esperara a que cargara la pagina.
    """

    FAKE_DETAIL_HTML = """
    <html><body>
    <div id="root">
      <nav>Buscar empleo por puesto o palabra clave Crear cuenta Ingresar
      Sitios de interes Buscar empresas Salarios Blog Terminos y Condiciones
      Politica de Privacidad Condiciones de contratacion Preguntas frecuentes
      Ofertas de Empleo Peru Copyright</nav>
      <main>
        <div class="sc-realcontent">
          <h1>Contador</h1>
          <p>Somos una importante empresa lider en su rubro, nos encontramos
          en la busqueda de un Contador con experiencia minima de 3 anios en
          NIIF, SAP y cierre contable mensual. Ofrecemos excelente clima
          laboral y linea de carrera.</p>
        </div>
      </main>
    </div>
    </body></html>
    """

    def test_picks_specific_block_not_root_wrapper(self, cfg):
        from scrapers.bumeran import BumeranScraper
        s = BumeranScraper(cfg)
        result = s._parse_detail_page(self.FAKE_DETAIL_HTML)
        desc = result.get("description_raw", "")
        assert "Contador con experiencia" in desc
        assert "Buscar empleo por puesto" not in desc


class TestJoobleNoKey:
    def test_returns_empty_without_key(self, cfg, monkeypatch):
        monkeypatch.delenv("JOOBLE_API_KEY", raising=False)
        from scrapers.jooble import JoobleScraper
        s = JoobleScraper(cfg)
        result = s.search("analista", "Lima")
        assert result == []

    def test_get_detail_always_empty(self, cfg):
        from scrapers.jooble import JoobleScraper
        s = JoobleScraper(cfg)
        assert s.get_detail("https://example.com") == {}


class TestLaborumURL:
    def test_url_without_city(self, cfg):
        from scrapers.laborum import LaborumScraper
        s = LaborumScraper(cfg)
        url = s._build_search_url("analista", "Remoto", 1)
        assert "l=" not in url   # "Remoto" no se pasa como ubicación

    def test_url_page_2(self, cfg):
        from scrapers.laborum import LaborumScraper
        s = LaborumScraper(cfg)
        url = s._build_search_url("analista", "Lima", 2)
        assert "page=2" in url

    def test_url_page_1_no_page_param(self, cfg):
        from scrapers.laborum import LaborumScraper
        s = LaborumScraper(cfg)
        url = s._build_search_url("analista", "Lima", 1)
        assert "page=" not in url


class TestSearchRespectsTimeBudget:
    """
    Regresion: LinkedIn (y otros portales lentos) podian colgar una busqueda
    por muchos minutos si un portal devolvia paginas indefinidamente. Cada
    search() debe cortar la paginacion apenas se supera max_search_seconds,
    sin necesitar que _fetch_html falle ni que el portal se quede sin
    resultados.
    """

    def test_computrabajo_stops_fetching_when_budget_exceeded(self, cfg, monkeypatch):
        from dataclasses import replace
        from scrapers.computrabajo import ComputrabajoScraper

        fast_cfg = replace(cfg, scraper=replace(cfg.scraper, max_pages=50, max_search_seconds=-1.0))
        s = ComputrabajoScraper(fast_cfg, page=object())

        calls = {"n": 0}

        def fake_fetch_html(url):
            calls["n"] += 1
            return "<html><article class='box_offer'></article></html>"

        monkeypatch.setattr(s, "_fetch_html", fake_fetch_html)
        jobs = s.search("analista", "Lima")

        assert calls["n"] == 0, "no deberia llegar a pedir ninguna pagina con presupuesto de tiempo en 0"
        assert jobs == []

    def test_bumeran_stops_fetching_when_budget_exceeded(self, cfg, monkeypatch):
        from dataclasses import replace
        from scrapers.bumeran import BumeranScraper

        fast_cfg = replace(cfg, scraper=replace(cfg.scraper, max_pages=50, max_search_seconds=-1.0))
        s = BumeranScraper(fast_cfg, page=object())

        calls = {"n": 0}

        def fake_fetch_html(url, wait_selector=None):
            calls["n"] += 1
            return "<html></html>"

        monkeypatch.setattr(s, "_fetch_html", fake_fetch_html)
        jobs = s.search("analista", "Lima")

        assert calls["n"] == 0
        assert jobs == []
