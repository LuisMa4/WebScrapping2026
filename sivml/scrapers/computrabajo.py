from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from config.settings import StudyConfig
from processing.normalizer import parse_relative_date
from scrapers.base import BaseScraper, ScrapedJob

# URL real validada: https://pe.computrabajo.com/trabajo-de-{slug-con-guiones}
# El slug se forma con guiones, no con +


class ComputrabajoScraper(BaseScraper):
    portal_name = "computrabajo"
    base_url = "https://pe.computrabajo.com"
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
            self.logger.debug(f"Página {page_num}: {url}")

            try:
                html = self._fetch_html(url)
                page_jobs = self._parse_listing_page(html)

                if not page_jobs:
                    self.logger.debug(f"Sin resultados en página {page_num}, deteniendo")
                    break

                jobs.extend(page_jobs)

                if not self._has_next_page(html, page_num):
                    break

            except Exception as exc:
                self.logger.warning(f"Error en página {page_num}: {exc}")
                break

        return jobs

    def get_detail(self, url: str) -> dict[str, str]:
        try:
            html = self._fetch_html(url)
            return self._parse_detail_page(html)
        except Exception as exc:
            self.logger.warning(f"Error en detalle {url}: {exc}")
            return {}

    # ------------------------------------------------------------------

    def _build_search_url(self, keyword: str, city: str, page: int) -> str:
        # Slug con guiones: "analista de datos" → "analista-de-datos"
        slug = re.sub(r"\s+", "-", keyword.strip().lower())
        slug = urllib.parse.quote(slug, safe="-")
        base = f"{self.base_url}/trabajo-de-{slug}"
        # El filtro de ciudad real es "-en-{ciudad}" (verificado en vivo,
        # julio 2026) -- antes se ignoraba por completo y toda "ciudad"
        # devolvia la misma busqueda nacional generica.
        if city and city.strip():
            city_slug = re.sub(r"\s+", "-", city.strip().lower())
            city_slug = urllib.parse.quote(city_slug, safe="-")
            base += f"-en-{city_slug}"
        if page > 1:
            return f"{base}?p={page}"
        return base

    def _fetch_html(self, url: str) -> str:
        if self.page is None:
            raise RuntimeError("Playwright page no inicializado")
        self._goto_with_retry(self.page, url, self.config.scraper.timeout_ms)
        self.page.wait_for_load_state("domcontentloaded")
        return self.page.content()

    def _parse_listing_page(self, html: str) -> list[ScrapedJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[ScrapedJob] = []

        # Selector validado contra HTML real de pe.computrabajo.com
        articles = soup.select("article.box_offer")

        for art in articles:
            try:
                job = self._parse_card(art)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.logger.debug(f"Error en card: {exc}")

        return jobs

    def _parse_card(self, art) -> ScrapedJob | None:
        # Source ID desde atributo data-id del article
        source_id = art.get("data-id") or ""

        # Título: <h2> > <a class="js-o-link">
        title_el = art.select_one("h2 a.js-o-link, h2 a")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        # URL: href relativo → absoluto
        href = title_el.get("href", "")
        # Quitar el fragmento #lc=... del URL
        href = href.split("#")[0]
        url = href if href.startswith("http") else f"{self.base_url}{href}"

        if not source_id:
            source_id = self._build_source_id(url)

        # Empresa: <p class="dFlex ..."> → <a class="fc_base t_ellipsis">
        company = None
        company_el = art.select_one("p.dFlex a.fc_base, p.fs16 a[offer-grid-article-company-url]")
        if company_el:
            company = company_el.get_text(strip=True)

        # Ciudad: <p class="fs16 fc_base mt5"> → <span class="mr10">
        city = None
        # Hay dos <p class="fs16 fc_base mt5">: primero es empresa, segundo es ciudad
        city_paras = art.select("p.fs16.fc_base.mt5, p.fs16.mt5")
        for p in city_paras:
            # El párrafo de ciudad tiene un span.mr10 con texto de ubicación (no un <a>)
            span = p.select_one("span.mr10")
            if span and not p.select_one("a"):
                city = span.get_text(strip=True)
                break

        # Salario: div.fs13 → span con ícono de salario
        salary_raw = None
        salary_div = art.select_one("div.fs13")
        if salary_div:
            sal_text = salary_div.get_text(strip=True)
            if sal_text:
                salary_raw = sal_text

        # Fecha de publicacion: <p class="fs13 fc_aux mt15"> "Hace 2 dias" / "Ayer"
        # (verificado en vivo, julio 2026). Texto relativo -> date real via
        # parse_relative_date; None si el formato no se reconoce.
        posted_date = None
        date_p = art.select_one("p.fs13.fc_aux.mt15")
        if date_p:
            posted_date = parse_relative_date(date_p.get_text(strip=True))

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
            posted_date=posted_date,
        )

    def _parse_detail_page(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, str] = {}

        # Selector validado contra HTML real de pe.computrabajo.com (junio 2026):
        # La descripcion esta en el primer div.mb40.pb40.bb1 dentro de div[description-offer]
        desc_div = soup.select_one("div[description-offer] div.mb40.pb40.bb1")
        if not desc_div:
            # Fallback: buscar el div que contenga el h3 "Descripcion de la oferta"
            h3 = soup.find("h3", string=lambda t: t and "Descripci" in t if t else False)
            if h3:
                desc_div = h3.find_parent("div")

        if desc_div:
            result["description_raw"] = desc_div.get_text(separator="\n", strip=True)

        # Competencias: Computrabajo muestra una <ul> con skills del reclutador
        for p in soup.find_all("p"):
            txt = p.get_text(strip=True).lower()
            if "conocimientos y habilidades" in txt or "reclutador buscará" in txt:
                ul = p.find_next_sibling("ul")
                if ul:
                    skills = [li.get_text(strip=True) for li in ul.find_all("li") if li.get_text(strip=True)]
                    if skills:
                        # Agregar al final de la descripcion si no están ya incluidas
                        competencias = "\n\n[COMPETENCIAS REQUERIDAS]\n" + "\n".join(f"- {s}" for s in skills)
                        result["description_raw"] = result.get("description_raw", "") + competencias
                break

        # Extraer campos estructurados de los tags de la oferta
        for span in soup.select("div.mbB span.tag.base"):
            text = span.get_text(strip=True).lower()
            if any(k in text for k in ["contrato", "plazo", "honorarios", "services"]):
                result.setdefault("contract_raw", span.get_text(strip=True))
            elif any(k in text for k in ["completo", "parcial", "horas", "tiempo"]):
                result.setdefault("modality_raw", span.get_text(strip=True))

        # Experiencia y educacion desde el texto de la descripcion
        desc_text = result.get("description_raw", "")
        for line in desc_text.splitlines():
            line_lower = line.lower()
            if any(k in line_lower for k in ["experiencia", "años de exp", "exp mínima"]):
                result.setdefault("experience_raw", line.strip(" -•*"))
            if any(k in line_lower for k in ["bachiller", "titulado", "egresado", "maestría", "técnico"]):
                result.setdefault("education_raw", line.strip(" -•*"))

        return result

    def _has_next_page(self, html: str, current_page: int) -> bool:
        soup = BeautifulSoup(html, "lxml")
        # Computrabajo usa paginación numérica — buscar enlace a página siguiente
        for sel in ["a[rel='next']", f"a[href*='?p={current_page + 1}']", "li.next a"]:
            if soup.select_one(sel):
                return True
        return False
