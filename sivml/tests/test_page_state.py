from pathlib import Path

import pytest

from dashboard.page_state import (
    clear_draft,
    load_draft,
    resolve_page_index,
    save_draft,
)


class TestResolvePageIndex:
    PAGES = {
        "Nuevo Estudio": "nuevo_estudio",
        "Mis Plantillas": "mis_plantillas",
        "Mis Estudios": "mis_estudios",
        "Resultados": "resultados",
        "Estado Portales": "portales",
    }

    def test_no_query_param_defaults_to_first_page(self):
        assert resolve_page_index(self.PAGES, None) == 0

    def test_empty_string_defaults_to_first_page(self):
        assert resolve_page_index(self.PAGES, "") == 0

    def test_matching_query_param_returns_its_index(self):
        assert resolve_page_index(self.PAGES, "mis_estudios") == 2

    def test_unknown_query_param_defaults_to_first_page(self):
        assert resolve_page_index(self.PAGES, "pagina_inexistente") == 0


class TestDraftStore:
    def test_load_draft_missing_file_returns_empty_dict(self, tmp_path):
        assert load_draft(tmp_path / "no_existe.json") == {}

    def test_save_then_load_roundtrips_known_fields(self, tmp_path):
        path = tmp_path / "draft.json"
        data = {
            "study_name": "Estudio X",
            "academic_program": "Ing. Sistemas",
            "keywords_raw": "contador\ningeniero",
            "cities": ["Lima", "Cusco"],
            "portals": ["computrabajo"],
            "max_pages": 10,
            "delay_min": 2.0,
            "delay_max": 5.0,
            "headless": True,
        }
        save_draft(path, data)
        assert load_draft(path) == data

    def test_save_drops_unknown_fields(self, tmp_path):
        path = tmp_path / "draft.json"
        save_draft(path, {"study_name": "X", "not_a_real_field": "junk"})
        loaded = load_draft(path)
        assert loaded == {"study_name": "X"}
        assert "not_a_real_field" not in loaded

    def test_clear_draft_removes_file(self, tmp_path):
        path = tmp_path / "draft.json"
        save_draft(path, {"study_name": "X"})
        assert path.exists()
        clear_draft(path)
        assert not path.exists()

    def test_clear_draft_missing_file_does_not_raise(self, tmp_path):
        clear_draft(tmp_path / "no_existe.json")  # no debe lanzar excepcion

    def test_load_draft_corrupted_json_returns_empty_dict(self, tmp_path):
        path = tmp_path / "draft.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert load_draft(path) == {}

    def test_load_draft_non_dict_json_returns_empty_dict(self, tmp_path):
        path = tmp_path / "draft.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_draft(path) == {}
