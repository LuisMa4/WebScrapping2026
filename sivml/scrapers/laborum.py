from __future__ import annotations

import time
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from config.settings import StudyConfig
from scrapers.base import BaseScraper, ScrapedJob

# laborum.pe usa Material-UI (MUI) con React SSR.
# Los jobs cargan con JavaScript. Se espera el selector de cards antes de parsear.
# URL validada: https://www.laborum.pe/empleos?q={keyword}
# Cards: div.MuiCard-root o article con link de oferta


class LaborumScraper(BaseScraper):
    portal_name = "laborum"
    base_url = "https://www.laborum.pe"
    engine = "playwright"

    def __init__(self, config: StudyConfig, page: Page | None = None):
        super().__init__(config, page)

    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        jobs: list[ScrapedJob] = []
        started_at = time.time()

        for page_num in range(1, self.config.scraper.max_pages + 1):
            if self._time_budget_exceeded(started_at):
                break

            url = self._build_search_url(keyword, city, page_num)

            try:
                html = self._fetch_html(url)
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
            html = self._fetch_html(url)
            return self._parse_detail_page(html)
        except Exception as exc:
            self.logger.warning(f"Error detalle {url}: {exc}")
            return {}

    def _build_search_url(self, keyword: str, city: str, page: int) -> str:
        params: dict = {"q": keyword}
        if city and city.lower() not in ("remoto", "remote"):
            params["l"] = city
        if page > 1:
            params["page"] = page
        return f"{self.base_url}/empleos?{urllib.parse.urlencode(params)}"

    def _fetch_html(self, url: str) -> str:
        if self.page is None:
            raise RuntimeError("Playwright page no inicializado")
        self.page.goto(url, timeout=self.config.scraper.timeout_ms)
        # Esperar a que React hidrate el contenido — probar varios selectores
        for selector in [
            "a[href*='/empleo/']",
            "a[href*='/trabajo/']",
            "div.MuiCard-root",
            "article",
            "[data-testid='job-card']",
        ]:
            try:
                self.page.wait_for_selector(selector, timeout=8_000)
                break
            except Exception:
                continue
        else:
            self.page.wait_for_timeout(4000)
        return self.page.content()

    def _parse_listing_page(self, html: str) -> list[ScrapedJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[ScrapedJob] = []

        # Laborum: buscar links a páginas de empleo/trabajo
        seen: set[str] = set()
        job_links = [
            a for a in soup.find_all("a", href=True)
            if any(k in a.get("href", "") for k in ["/empleo/", "/trabajo/", "/oferta/"])
        ]

        # Fallback: buscar MuiCard
        if not job_links:
            cards = soup.select("div.MuiCard-root, article")
            for card in cards:
                title_el = card.find(["h2", "h3", "h4"])
                link_el = card.find("a", href=True)
                if not title_el or not link_el:
                    continue
                href = link_el.get("href", "")
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                if url in seen:
                    continue
                seen.add(url)
                jobs.append(ScrapedJob(
                    source_id=self._build_source_id(url),
                    portal=self.portal_name,
                    url=url,
                    scraped_at=datetime.utcnow(),
                    title=title_el.get_text(strip=True),
                    country="Perú",
                ))
            return jobs

        for a in job_links:
            href = a.get("href", "")
            url = href if href.startswith("http") else f"{self.base_url}{href}"
            if url in seen:
                continue
            seen.add(url)

            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Subir al contenedor padre para extraer empresa y ciudad
            card = a.parent
            for _ in range(5):
                if card is None or len(card.get_text(strip=True)) > len(title) + 10:
                    break
                card = card.parent

            company = None
            city_val = None
            if card:
                texts = [
                    t.strip()
                    for t in card.get_text(separator="|").split("|")
                    if t.strip() and t.strip() != title
                ]
                if texts:
                    company = texts[0][:100]
                city_kws = ["lima", "arequipa", "trujillo", "cusco", "piura", "remoto"]
                for t in texts[1:]:
                    if any(k in t.lower() for k in city_kws):
                        city_val = t[:100]
                        break

            jobs.append(ScrapedJob(
                source_id=self._build_source_id(url),
                portal=self.portal_name,
                url=url,
                scraped_at=datetime.utcnow(),
                title=title,
                company=company,
                city=city_val,
                country="Perú",
            ))

        return jobs

    def _parse_detail_page(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, str] = {}
        candidates = [
            el for el in soup.find_all(["div", "section"])
            if len(el.get_text(strip=True)) > 200
        ]
        if candidates:
            biggest = max(candidates, key=lambda el: len(el.get_text(strip=True)))
            result["description_raw"] = biggest.get_text(separator="\n", strip=True)[:5000]
        return result

    def _has_next_page(self, html: str) -> bool:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True).lower()
            if any(k in txt for k in ["siguiente", "next"]) and a.get("href"):
                return True
        # MUI Pagination
        next_btn = soup.find("button", attrs={"aria-label": lambda x: x and "next" in x.lower()})
        return bool(next_btn and not next_btn.get("disabled"))
