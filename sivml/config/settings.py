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


def load_study_config(path: str | Path) -> StudyConfig:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    scraper_raw = raw.get("scraper", {})
    scraper = ScraperConfig(
        delay_range=tuple(scraper_raw.get("delay_range", [2.0, 5.0])),
        max_retries=scraper_raw.get("max_retries", 3),
        max_pages=scraper_raw.get("max_pages", 50),
        headless=scraper_raw.get("headless", True),
        timeout_ms=scraper_raw.get("timeout_ms", 30_000),
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
