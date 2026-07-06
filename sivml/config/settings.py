from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ScraperConfig:
    delay_range: tuple[float, float] = (2.0, 5.0)
    max_retries: int = 3
    max_pages: int = 50
    headless: bool = True
    timeout_ms: int = 30_000
    # Tiempo maximo (segundos) para UNA busqueda (keyword+ciudad) dentro de un
    # portal. Portales lentos (LinkedIn, con su anti-bot y contexto fresco por
    # keyword) pueden tardar minutos por pagina -- pasado este limite se corta
    # la paginacion y se devuelve lo ya recolectado, en vez de seguir indefinidamente.
    max_search_seconds: float = 420.0  # 7 minutos


@dataclass(frozen=True)
class StudyConfig:
    study_name: str
    keywords: list[str]
    cities: list[str]
    portals: list[str]
    date_from: date
    date_to: date
    academic_program: str
    study_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    scraper: ScraperConfig = field(default_factory=ScraperConfig)


def study_config_to_dict(cfg: StudyConfig) -> dict[str, Any]:
    """
    Serializa un StudyConfig a un dict JSON-compatible. Usado para guardar
    la configuracion completa de un estudio en cola (Study.config_yaml) y
    poder reconstruirla al promoverlo, potencialmente en otro hilo/momento.
    """
    return {
        "study_name": cfg.study_name,
        "keywords": cfg.keywords,
        "cities": cfg.cities,
        "portals": cfg.portals,
        "date_from": cfg.date_from.isoformat(),
        "date_to": cfg.date_to.isoformat(),
        "academic_program": cfg.academic_program,
        "study_id": cfg.study_id,
        "scraper": {
            "delay_range": list(cfg.scraper.delay_range),
            "max_retries": cfg.scraper.max_retries,
            "max_pages": cfg.scraper.max_pages,
            "headless": cfg.scraper.headless,
            "timeout_ms": cfg.scraper.timeout_ms,
            "max_search_seconds": cfg.scraper.max_search_seconds,
        },
    }


def study_config_from_dict(data: dict[str, Any]) -> StudyConfig:
    scraper_raw = data.get("scraper", {})
    return StudyConfig(
        study_name=data["study_name"],
        keywords=data["keywords"],
        cities=data["cities"],
        portals=data["portals"],
        date_from=date.fromisoformat(data["date_from"]),
        date_to=date.fromisoformat(data["date_to"]),
        academic_program=data["academic_program"],
        study_id=data["study_id"],
        scraper=ScraperConfig(
            delay_range=tuple(scraper_raw.get("delay_range", [2.0, 5.0])),
            max_retries=scraper_raw.get("max_retries", 3),
            max_pages=scraper_raw.get("max_pages", 50),
            headless=scraper_raw.get("headless", True),
            timeout_ms=scraper_raw.get("timeout_ms", 30_000),
            max_search_seconds=scraper_raw.get("max_search_seconds", 420.0),
        ),
    )


def load_study_config(path: str | Path) -> StudyConfig:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    scraper_raw = raw.get("scraper", {})
    scraper = ScraperConfig(
        delay_range=tuple(scraper_raw.get("delay_range", [2.0, 5.0])),
        max_retries=scraper_raw.get("max_retries", 3),
        max_pages=scraper_raw.get("max_pages", 50),
        headless=scraper_raw.get("headless", True),
        timeout_ms=scraper_raw.get("timeout_ms", 30_000),
        max_search_seconds=scraper_raw.get("max_search_seconds", 420.0),
    )

    return StudyConfig(
        study_name=raw["study_name"],
        keywords=raw["keywords"],
        cities=raw["cities"],
        portals=raw["portals"],
        date_from=date.fromisoformat(str(raw["date_from"])),
        date_to=date.fromisoformat(str(raw["date_to"])),
        academic_program=raw["academic_program"],
        scraper=scraper,
    )
