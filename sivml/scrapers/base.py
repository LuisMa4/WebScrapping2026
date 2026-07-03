from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page
    from config.settings import StudyConfig


@dataclass
class ScrapedJob:
    """
    Oferta laboral tal como fue extraída del portal.
    Todos los campos de contenido son strings o None — sin parseo.
    El parseo ocurre en la capa de processing.
    """
    # Identidad
    source_id: str        # ID del portal o hash de URL
    portal: str
    url: str
    scraped_at: datetime

    # Contenido crudo
    title: str
    company: str | None = None
    city: str | None = None
    country: str | None = None
    posted_date: date | None = None
    description_raw: str | None = None
    salary_raw: str | None = None
    modality_raw: str | None = None
    contract_raw: str | None = None
    experience_raw: str | None = None
    education_raw: str | None = None

    # Contexto del estudio (inyectado por el orquestador)
    study_id: str = ""
    keyword_matched: str = ""


class BaseScraper(ABC):
    """
    Clase base para todos los scrapers de portales de empleo.

    Para agregar un nuevo portal:
    1. Crear scrapers/<portal>.py
    2. Subclasear BaseScraper
    3. Implementar search() y get_detail()
    4. Registrar en scrapers/__init__.py REGISTRY
    """

    portal_name: str = ""
    base_url: str = ""
    engine: str = "playwright"  # "playwright" o "requests"

    def __init__(self, config: StudyConfig, page: Page | None = None):
        self.config = config
        self.page = page
        self.logger = logging.getLogger(f"sivml.scraper.{self.portal_name}")

    @abstractmethod
    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        """
        Ejecuta una búsqueda para una combinación keyword + ciudad.
        Debe manejar la paginación internamente.
        No debe lanzar excepción por una oferta individual — log y continuar.
        """

    @abstractmethod
    def get_detail(self, url: str) -> dict[str, str]:
        """
        Extrae campos adicionales de la página de detalle de una oferta.
        Devuelve dict con claves como 'description_raw', 'salary_raw', etc.
        """

    def scrape_all(self) -> list[ScrapedJob]:
        """
        Producto cartesiano keywords × ciudades configuradas.
        Llama search() y luego get_detail() por cada resultado.
        """
        results: list[ScrapedJob] = []

        for keyword in self.config.keywords:
            for city in self.config.cities:
                self.logger.info(f"Buscando: '{keyword}' en {city}")
                try:
                    jobs = self.search(keyword, city)
                    self.logger.info(f"  → {len(jobs)} ofertas encontradas")

                    for job in jobs:
                        try:
                            detail = self.get_detail(job.url)
                            job = self._merge_detail(job, detail)
                        except Exception as exc:
                            self.logger.warning(f"  Error en detalle {job.url}: {exc}")

                        job.study_id = self.config.study_id
                        job.keyword_matched = keyword
                        results.append(job)
                        self._rate_limit()

                except Exception as exc:
                    self.logger.error(f"Error en búsqueda '{keyword}' / {city}: {exc}")

        return results

    def _merge_detail(self, job: ScrapedJob, detail: dict[str, str]) -> ScrapedJob:
        """Fusiona campos del detalle en el dataclass, sin sobreescribir valores ya presentes."""
        for key, value in detail.items():
            if hasattr(job, key) and getattr(job, key) is None and value:
                object.__setattr__(job, key, value)
        return job

    def _goto_with_retry(
        self, page: Page, url: str, timeout: int, retries: int = 1, retry_delay: float = 1.5
    ) -> None:
        """
        Navega con un reintento ante fallos de red transitorios. Bajo scraping
        paralelo con varios navegadores Chromium simultaneos, page.goto()
        puede fallar ocasionalmente con errores transitorios como
        net::ERR_NETWORK_IO_SUSPENDED -- un solo reintento resuelve la
        mayoria de estos casos sin enmascarar fallos reales y persistentes.
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                page.goto(url, timeout=timeout)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    self.logger.debug(f"Reintentando {url} tras error transitorio: {exc}")
                    time.sleep(retry_delay)
        raise last_exc

    def _rate_limit(self) -> None:
        lo, hi = self.config.scraper.delay_range
        time.sleep(random.uniform(lo, hi))

    def _build_source_id(self, url: str) -> str:
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()
