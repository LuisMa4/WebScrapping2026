from __future__ import annotations

import time
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from config.settings import StudyConfig
from scrapers.base import BaseScraper, ScrapedJob

# LinkedIn bloquea scrapers agresivamente.
# Esta implementación usa Playwright con delays conservadores.
# Requiere sesión iniciada manualmente si el contenido está detrás de login.
_LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/search"


class LinkedInScraper(BaseScraper):
    portal_name = "linkedin"
    base_url = "https://www.linkedin.com"
    engine = "playwright"
    # LinkedIn es muy agresivo con la deteccion de bots: contexto fresco por keyword
    fresh_context_per_keyword: bool = True

    def __init__(self, config: StudyConfig, page: Page | None = None):
        super().__init__(config, page)

    _LISTING_SELECTOR = "ul.jobs-search__results-list, div.jobs-search-results-list"
    _DETAIL_SELECTOR = "div.show-more-less-html__markup, div.description__text, section.description"

    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        jobs: list[ScrapedJob] = []
        start = 0

        for _ in range(self.config.scraper.max_pages):
            url = self._build_search_url(keyword, city, start)

            try:
                html = self._fetch_html(url, self._LISTING_SELECTOR)
                page_jobs = self._parse_listing_page(html)

                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                start += 25  # LinkedIn usa offsets de 25

                # Pausa extra por las medidas anti-bot de LinkedIn
                time.sleep(3)

            except Exception as exc:
                self.logger.warning(f"Error offset {start}: {exc}")
                break

        return jobs

    def get_detail(self, url: str) -> dict[str, str]:
        try:
            html = self._fetch_html(url, self._DETAIL_SELECTOR)
            return self._parse_detail_page(html)
        except Exception as exc:
            self.logger.warning(f"Error detalle {url}: {exc}")
            return {}

    def _build_search_url(self, keyword: str, city: str, start: int) -> str:
        params = urllib.parse.urlencode({
            "keywords": keyword,
            "location": city,
            "start": start,
            "f_TPR": "r2592000",  # último mes
        })
        return f"{_LINKEDIN_JOBS_URL}?{params}"

    def _fetch_html(self, url: str, wait_selector: str) -> str:
        # LinkedIn carga contenido dinamicamente -- hay que esperar el
        # selector correcto segun la pagina (listado vs. detalle). Usar
        # siempre el selector de listado (bug original) hacia que cada
        # get_detail() esperara el timeout completo de 15s en vano, porque
        # ese selector nunca aparece en una pagina de detalle individual.
        if self.page is None:
            raise RuntimeError("Playwright page no inicializado")
        self._goto_with_retry(self.page, url, self.config.scraper.timeout_ms)
        try:
            self.page.wait_for_selector(wait_selector, timeout=15_000)
        except Exception:
            pass  # continuar con lo que haya cargado
        return self.page.content()

    def _parse_listing_page(self, html: str) -> list[ScrapedJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[ScrapedJob] = []

        cards = soup.select(
            "li.jobs-search-results__list-item, "
            "div.base-card, "
            "li.result-card"
        )

        for card in cards:
            try:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.logger.debug(f"Error card: {exc}")

        return jobs

    def _parse_card(self, card) -> ScrapedJob | None:
        title_el = card.select_one(
            "h3.base-search-card__title, "
            "span.sr-only, "
            "a.job-card-list__title"
        )
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        link_el = card.select_one("a.base-card__full-link, a.job-card-list__title")
        href = link_el.get("href", "") if link_el else ""
        url = href.split("?")[0] if href else ""  # quitar parámetros de tracking
        if not url:
            return None

        source_id = card.get("data-entity-urn", "") or self._build_source_id(url)

        company_el = card.select_one("h4.base-search-card__subtitle a, span.job-card-container__company-name")
        city_el = card.select_one("span.job-search-card__location, span.job-card-container__metadata-item")

        return ScrapedJob(
            source_id=source_id,
            portal=self.portal_name,
            url=url,
            scraped_at=datetime.utcnow(),
            title=title,
            company=company_el.get_text(strip=True) if company_el else None,
            city=city_el.get_text(strip=True) if city_el else None,
            country="Perú",
        )

    def _parse_detail_page(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, str] = {}

        desc_el = soup.select_one(
            "div.show-more-less-html__markup, "
            "div.description__text, "
            "section.description"
        )
        if desc_el:
            result["description_raw"] = desc_el.get_text(separator="\n", strip=True)

        for item in soup.select("li.description__job-criteria-item"):
            label_el = item.select_one("h3")
            value_el = item.select_one("span")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)
            if "modalidad" in label or "type" in label:
                result.setdefault("modality_raw", value)
            elif "contrato" in label or "employment" in label:
                result.setdefault("contract_raw", value)
            elif "experiencia" in label or "experience" in label:
                result.setdefault("experience_raw", value)
            elif "nivel" in label or "seniority" in label:
                result.setdefault("education_raw", value)

        return result
