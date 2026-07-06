from datetime import date

from config.settings import (
    ScraperConfig,
    StudyConfig,
    study_config_from_dict,
    study_config_to_dict,
)


class TestStudyConfigRoundtrip:
    """
    Un estudio en cola se guarda como JSON en Study.config_yaml y se
    reconstruye al promoverlo (cuando se libera un cupo, posiblemente
    minutos u horas despues, en otro hilo). El roundtrip debe preservar
    cada campo exactamente.
    """

    def _cfg(self, **overrides):
        base = dict(
            study_name="Estudio X",
            keywords=["contador", "ingeniero"],
            cities=["Lima", "Arequipa"],
            portals=["computrabajo", "bumeran"],
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            academic_program="Contabilidad",
            study_id="abc-123",
            scraper=ScraperConfig(
                delay_range=(1.5, 3.5), max_retries=2, max_pages=7,
                headless=False, timeout_ms=20_000, max_search_seconds=200.0,
            ),
        )
        base.update(overrides)
        return StudyConfig(**base)

    def test_roundtrip_preserves_all_fields(self):
        cfg = self._cfg()
        data = study_config_to_dict(cfg)
        restored = study_config_from_dict(data)
        assert restored == cfg

    def test_to_dict_is_json_serializable(self):
        import json
        cfg = self._cfg()
        data = study_config_to_dict(cfg)
        json.dumps(data)  # no debe lanzar (dates/tuples deben ir a str/list)

    def test_roundtrip_through_json_string(self):
        import json
        cfg = self._cfg()
        raw = json.dumps(study_config_to_dict(cfg))
        restored = study_config_from_dict(json.loads(raw))
        assert restored == cfg

    def test_roundtrip_with_default_scraper_config(self):
        cfg = self._cfg(scraper=ScraperConfig())
        restored = study_config_from_dict(study_config_to_dict(cfg))
        assert restored.scraper == ScraperConfig()
