from __future__ import annotations

import re
import time
import unicodedata
import urllib.parse
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from config.settings import StudyConfig
from scrapers.base import BaseScraper, ScrapedJob

# Selectores validados contra HTML real de pe.indeed.com (junio 2026):
# Card:    div.job_seen_beacon  (16 por página)
# Título:  a.jcs-JobTitle
# Empresa: [data-testid='company-name']
# Ciudad:  [data-testid='text-location']
# Salario: div.salary-snippet-container
#
# NOTA: Indeed PE acepta keywords sin tilde. Las búsquedas con caracteres
# especiales (ú, é, á, ó, ñ) devuelven 0 resultados. Se normalizan antes
# de construir la URL.


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


class IndeedScraper(BaseScraper):
    portal_name = "indeed"
    base_url = "https://pe.indeed.com"
    engine = "playwright"
    # Requiere contexto de navegador fresco por cada keyword para evitar deteccion de bot
    fresh_context_per_keyword: bool = True

    def __init__(self, config: StudyConfig, page: Page | None = None):
        super().__init__(config, page)

    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        jobs: list[ScrapedJob] = []
        # Normalizar keyword: sin tildes (requisito de Indeed PE)
        keyword_norm = _strip_accents(keyword)
        start = 0
        results_per_page = 15
        started_at = time.time()

        for _ in range(self.config.scraper.max_pages):
            if self._time_budget_exceeded(started_at):
                break

            url = self._build_search_url(keyword, city, start)
            self.logger.debug(f"Indeed offset {start}: {url}")

            try:
                html = self._fetch_html(url)
                page_jobs = self._parse_listing_page(html)

                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                start += results_per_page

                # Pausa extra para evitar detección por bot
                time.sleep(2)

            except Exception as exc:
                self.logger.warning(f"Error offset {start}: {exc}")
                break

        return jobs

    def get_detail(self, url: str) -> dict[str, str]:
        try:
            html = self._fetch_html(url)
            return self._parse_detail_page(html)
        except Exception as exc:
            self.logger.warning(f"Error detalle {url}: {exc}")
            return {}

    def _build_search_url(self, keyword: str, city: str, start: int) -> str:
        # Siempre normalizar: Indeed PE no acepta tildes en el query
        keyword_clean = _strip_accents(keyword)
        # fromage = dias desde publicacion (parametro nativo de Indeed) --
        # deriva del date_from del estudio, asi el filtro de fechas del
        # estudio se aplica del lado del portal en vez de descartar despues.
        days_ago = max(1, (date.today() - self.config.date_from).days)
        params = urllib.parse.urlencode({
            "q": keyword_clean, "l": city, "start": start, "fromage": days_ago,
        })
        return f"{self.base_url}/jobs?{params}"

    def _fetch_html(self, url: str) -> str:
        if self.page is None:
            raise RuntimeError("Playwright page no inicializado")
        self._goto_with_retry(self.page, url, self.config.scraper.timeout_ms)
        self.page.wait_for_load_state("domcontentloaded")
        return self.page.content()

    def _parse_listing_page(self, html: str) -> list[ScrapedJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[ScrapedJob] = []

        cards = soup.select("div.job_seen_beacon")

        for card in cards:
            try:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.logger.debug(f"Error card: {exc}")

        return jobs

    def _parse_card(self, card) -> ScrapedJob | None:
        title_el = card.select_one("a.jcs-JobTitle, h2.jobTitle a")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        href = title_el.get("href", "")
        jk_match = re.search(r"jk=([a-f0-9]+)", href)
        if jk_match:
            jk = jk_match.group(1)
            url = f"{self.base_url}/viewjob?jk={jk}"
            source_id = jk
        else:
            url = href if href.startswith("http") else f"{self.base_url}{href}"
            source_id = self._build_source_id(url)

        company_el = card.select_one("[data-testid='company-name']")
        company = company_el.get_text(strip=True) if company_el else None

        city_el = card.select_one("[data-testid='text-location']")
        city = city_el.get_text(strip=True) if city_el else None

        salary_el = card.select_one("div.salary-snippet-container, div.attribute_snippet")
        salary_raw = salary_el.get_text(strip=True) if salary_el else None

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
        )

    def _parse_detail_page(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, str] = {}

        desc_el = soup.select_one(
            "div#jobDescriptionText, "
            "div.jobsearch-jobDescriptionText, "
            "div[id*=jobDescription]"
        )
        if desc_el:
            result["description_raw"] = desc_el.get_text(separator="\n", strip=True)

        return result
