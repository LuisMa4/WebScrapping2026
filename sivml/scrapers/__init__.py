from __future__ import annotations

# Constantes en módulo independiente — importables sin riesgo de ImportError en cadena
from scrapers.portal_info import (
    PORTAL_STATUS,
    PORTAL_CAPABILITIES,
    RECOMMENDED_PORTALS,
    SAFE_COMBINATIONS,
)

from scrapers.base import BaseScraper, ScrapedJob

# Imports individuales con try/except: un scraper que falle no rompe el módulo
try:
    from scrapers.computrabajo import ComputrabajoScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"computrabajo: {_e}")
    ComputrabajoScraper = None  # type: ignore[assignment,misc]

try:
    from scrapers.indeed import IndeedScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"indeed: {_e}")
    IndeedScraper = None  # type: ignore[assignment,misc]

try:
    from scrapers.bumeran import BumeranScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"bumeran: {_e}")
    BumeranScraper = None  # type: ignore[assignment,misc]

try:
    from scrapers.laborum import LaborumScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"laborum: {_e}")
    LaborumScraper = None  # type: ignore[assignment,misc]

try:
    from scrapers.jooble import JoobleScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"jooble: {_e}")
    JoobleScraper = None  # type: ignore[assignment,misc]

try:
    from scrapers.linkedin import LinkedInScraper
except Exception as _e:
    import logging; logging.getLogger("sivml.scrapers").error(f"linkedin: {_e}")
    LinkedInScraper = None  # type: ignore[assignment,misc]

REGISTRY: dict[str, type[BaseScraper]] = {
    name: cls
    for name, cls in {
        "computrabajo": ComputrabajoScraper,
        "indeed":       IndeedScraper,
        "bumeran":      BumeranScraper,
        "laborum":      LaborumScraper,
        "jooble":       JoobleScraper,
        "linkedin":     LinkedInScraper,
    }.items()
    if cls is not None
}


def get_scraper(portal: str) -> type[BaseScraper]:
    if portal not in REGISTRY:
        available = ", ".join(REGISTRY) or "(ninguno cargado)"
        raise ValueError(f"Portal desconocido '{portal}'. Disponibles: {available}")
    return REGISTRY[portal]


def get_portal_status(portal: str) -> dict:
    return PORTAL_STATUS.get(portal, {"status": "DESCONOCIDO", "nota": ""})
