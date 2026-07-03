from __future__ import annotations

from config.settings import StudyConfig
from scrapers.base import BaseScraper, ScrapedJob

# Jooble bloquea el acceso directo por HTML (403 Forbidden) y el dominio
# pe.jooble.org redirige de forma cíclica sin servir contenido scrappable.
# Se requiere API key oficial (https://jooble.org/api/about).
# Sin API key: el scraper retorna 0 resultados con un aviso en el log.
# Con API key: configurar JOOBLE_API_KEY en .env


class JoobleScraper(BaseScraper):
    portal_name = "jooble"
    base_url = "https://jooble.org"
    engine = "requests"

    _API_URL = "https://jooble.org/api/"

    def __init__(self, config: StudyConfig, page=None):
        super().__init__(config, page)
        import os
        self._api_key = os.environ.get("JOOBLE_API_KEY")
        if not self._api_key:
            self.logger.warning(
                "JOOBLE_API_KEY no configurada. "
                "Jooble no permite scraping HTML directo. "
                "Obtén una API key en https://jooble.org/api/about"
            )

    def search(self, keyword: str, city: str) -> list[ScrapedJob]:
        if not self._api_key:
            return []
        return self._search_via_api(keyword, city)

    def get_detail(self, url: str) -> dict[str, str]:
        return {}

    def _search_via_api(self, keyword: str, city: str) -> list[ScrapedJob]:
        import json
        import requests
        from datetime import datetime

        jobs: list[ScrapedJob] = []
        session = requests.Session()
        session.headers["Content-Type"] = "application/json"

        for page in range(1, self.config.scraper.max_pages + 1):
            payload = json.dumps({"keywords": keyword, "location": city, "page": page})
            try:
                resp = session.post(
                    f"{self._API_URL}{self._api_key}",
                    data=payload,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("jobs", [])

                if not items:
                    break

                for item in items:
                    link = item.get("link", "")
                    jobs.append(ScrapedJob(
                        source_id=str(item.get("id") or self._build_source_id(link)),
                        portal=self.portal_name,
                        url=link,
                        scraped_at=datetime.utcnow(),
                        title=item.get("title", ""),
                        company=item.get("company"),
                        city=item.get("location"),
                        country="Perú",
                        salary_raw=item.get("salary"),
                        description_raw=item.get("snippet"),
                    ))
                self._rate_limit()
            except Exception as exc:
                self.logger.warning(f"Error API Jooble página {page}: {exc}")
                break

        return jobs
