from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from config.settings import StudyConfig
from scrapers.base import BaseScraper, ScrapedJob

# Selectores validados contra HTML real de bumeran.com.pe (junio 2026):
# Cards se identifican por: div[id^="header-col-job-posting-{id}"]
#   h2 → título del puesto
#   h3[último] → empresa
# Ciudad: div[id^="data-col-job-posting-{id}"] → primer texto
# URL: a[href*="/empleos/"] dentro del card-wrapper


class BumeranScraper(BaseScraper):
    portal_name = "bumeran"
    base_url = "https://www.bumeran.com.pe"
    engine = "playwright"

    def __init__(self, config: StudyConfig, page: Page | None = None):
        super().__init__(config, page)

    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        jobs: list[ScrapedJob] = []

        for page_num in range(1, self.config.scraper.max_pages + 1):
            url = self._build_search_url(keyword, city, page_num)

            try:
                html = self._fetch_html(url, wait_selector="div[id^='header-col-job-posting']")
                page_jobs = self._parse_listing_page(html)

                if not page_jobs:
                    break

                jobs.extend(page_jobs)

                if not self._has_next_page(html):
                    break

            except Exception as exc:
                self.logger.warning(f"Error página {page_num}: {exc}")
                break

        return jobs

    def get_detail(self, url: str) -> dict[str, str]:
        try:
            # bumeran.com.pe renderiza el contenido real (descripcion) via
            # JS despues del load inicial -- domcontentloaded por si solo
            # es demasiado temprano y solo devuelve el shell de navegacion.
            # h1/h2 (titulo del puesto) es un proxy rapido de que el
            # contenido de la oferta ya se renderizo.
            html = self._fetch_html(url, wait_selector="h1, h2")
            return self._parse_detail_page(html)
        except Exception as exc:
            self.logger.warning(f"Error detalle {url}: {exc}")
            return {}

    def _build_search_url(self, keyword: str, city: str, page: int) -> str:
        # bumeran.com.pe no filtra por keyword via query param "?q=" sobre el
        # listado generico -- el buscador real navega a una URL con el keyword
        # "sluggificado" en el path: /empleos-busqueda-{slug}.html
        # (verificado manualmente contra el buscador del sitio, julio 2026).
        # La ciudad tambien se ignoraba por completo -- el filtro real es
        # agregar "-en-{ciudad}" al slug, antes de ".html".
        slug = self._slugify(keyword)
        if city and city.strip():
            slug += f"-en-{self._slugify(city)}"
        url = f"{self.base_url}/empleos-busqueda-{slug}.html"
        if page > 1:
            url += f"?page={page}"
        return url

    @staticmethod
    def _slugify(text: str) -> str:
        # bumeran.com.pe requiere el slug sin tildes/diacriticos: una version
        # con acentos codificados (%C3%BA, etc.) no devuelve resultados.
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
        return text.strip("-")

    def _fetch_html(self, url: str, wait_selector: str | None = None) -> str:
        # wait_selector solo aplica a paginas de listado (cards de resultado).
        # Las paginas de detalle no tienen ese selector -- esperarlo ahi
        # agotaba el timeout completo (12s + 3s de fallback) en cada oferta,
        # sin ninguna ganancia, porque _parse_detail_page no depende de un
        # selector fijo (extrae el bloque de texto mas largo de la pagina).
        if self.page is None:
            raise RuntimeError("Playwright page no inicializado")
        self._goto_with_retry(self.page, url, self.config.scraper.timeout_ms)
        if wait_selector:
            try:
                self.page.wait_for_selector(wait_selector, timeout=12_000)
            except Exception:
                self.page.wait_for_timeout(3000)
        else:
            self.page.wait_for_load_state("domcontentloaded")
        return self.page.content()

    def _parse_listing_page(self, html: str) -> list[ScrapedJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[ScrapedJob] = []

        # Cada card tiene tres divs con IDs: header-col-*, data-col-*, footer-col-*
        header_divs = soup.find_all(
            "div", id=lambda x: x and x.startswith("header-col-job-posting")
        )
        self.logger.debug(f"  Bumeran cards encontradas: {len(header_divs)}")

        for header_div in header_divs:
            try:
                job = self._parse_card(soup, header_div)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.logger.debug(f"Error card: {exc}")

        return jobs

    def _parse_card(self, soup, header_div) -> ScrapedJob | None:
        # Extraer job_id del atributo id del div
        div_id = header_div.get("id", "")
        # id = "header-col-job-posting-{job_id}"
        job_id = div_id.replace("header-col-job-posting-", "")

        # Título: primer h2 dentro del header_div
        title_el = header_div.find("h2")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        # Empresa: último h3 dentro del header_div (el primero es la fecha)
        all_h3 = header_div.find_all("h3")
        company = None
        if len(all_h3) >= 2:
            company = all_h3[-1].get_text(strip=True)
        elif all_h3:
            company = all_h3[0].get_text(strip=True)

        # URL: buscar el <a href="/empleos/"> en la cadena de ancestros.
        # En la estructura real de Bumeran, el <a> es el wrapper de todo el card.
        url = None
        parent = header_div.parent
        for _ in range(8):
            if parent is None or parent.name in ("body", "html"):
                break
            # El <a> puede SER el parent (Bumeran envuelve el card entero)
            if parent.name == "a":
                href = parent.get("href", "")
                if "/empleos/" in href:
                    url = href if href.startswith("http") else f"{self.base_url}{href}"
                    break
            # O puede contener un <a> hijo con la URL
            a_tag = parent.find("a", href=lambda h: h and "/empleos/" in h)
            if a_tag:
                href = a_tag.get("href", "")
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                break
            parent = parent.parent

        if not url:
            return None

        source_id = job_id if job_id else self._build_source_id(url)

        # Ciudad: div[id="data-col-job-posting-{job_id}"] → primer texto
        city = None
        salary_raw = None
        data_div_id = f"data-col-job-posting-{job_id}"
        data_div = soup.find("div", id=data_div_id)
        if data_div:
            texts = [
                t.strip() for t in data_div.get_text(separator="|").split("|")
                if t.strip()
            ]
            if texts:
                city = texts[0]  # "Chorrillos, Lima"
            # Buscar salario en el data_div
            for t in texts:
                if any(k in t.lower() for k in ["s/", "soles", "usd", "$"]):
                    salary_raw = t
                    break

        # Modalidad también está en data-col
        modality_raw = None
        if data_div:
            modality_keywords = ["presencial", "remoto", "híbrido", "hibrido", "virtual"]
            for t in texts:
                if any(k in t.lower() for k in modality_keywords):
                    modality_raw = t
                    break

        return ScrapedJob(
            source_id=source_id,
            portal=self.portal_name,
            url=url,
            scraped_at=datetime.utcnow(),
            title=title,
            company=company,
            city=city,
            country="Perú",
            salary_raw=salary_raw,
            modality_raw=modality_raw,
        )

    def _parse_detail_page(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, str] = {}

        candidates = [
            el for el in soup.find_all(["div", "section"])
            if len(el.get_text(strip=True)) > 200
        ]
        # bumeran.com.pe es una app React con clases generadas (sc-xxxxx,
        # sin id/clase semantica estable). El <div id="root"> envuelve TODO
        # el contenido (nav + descripcion + footer), asi que "el bloque de
        # texto mas grande" sin mas filtro siempre elige ese wrapper en vez
        # de la descripcion real. Quedarse solo con los candidatos que NO
        # contienen otro candidato anidado (los mas especificos/internos).
        candidate_ids = {id(el) for el in candidates}
        leaf_candidates = [
            el for el in candidates
            if not any(id(child) in candidate_ids for child in el.find_all(["div", "section"]))
        ]
        pool = leaf_candidates or candidates
        if pool:
            biggest = max(pool, key=lambda el: len(el.get_text(strip=True)))
            result["description_raw"] = biggest.get_text(separator="\n", strip=True)[:5000]

        return result

    def _has_next_page(self, html: str) -> bool:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            txt = a.get_text(strip=True).lower()
            if "page=" in href and any(k in txt for k in ["siguiente", "next", "›", "»"]):
                return True
        return False
