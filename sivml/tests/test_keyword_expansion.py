"""
Cuando una keyword tiene varias palabras (ej. "analista de datos junior"),
el portal la busca como si TODAS las palabras tuvieran que aparecer juntas
-- eso descarta ofertas legitimas y puede terminar en 0 resultados.
expand_keyword_terms() la separa en palabras significativas para buscarlas
una por una y juntar resultados (basta con que UNA coincida).
"""
from processing.keyword_expansion import expand_keyword_terms


class TestExpandKeywordTerms:
    def test_single_word_returned_unchanged(self):
        assert expand_keyword_terms("contador") == ["contador"]

    def test_multi_word_without_stopwords_returns_all_up_to_limit(self):
        assert expand_keyword_terms("gestion hospitalaria publica", max_terms=3) == [
            "gestion", "hospitalaria", "publica",
        ]

    def test_removes_spanish_stopwords(self):
        assert expand_keyword_terms("analista de datos") == ["analista", "datos"]

    def test_caps_to_max_terms_default_three(self):
        result = expand_keyword_terms("analista senior de datos y reportes financieros")
        assert len(result) == 3
        assert result == ["analista", "senior", "datos"]

    def test_caps_to_custom_max_terms(self):
        result = expand_keyword_terms("analista de datos junior", max_terms=2)
        assert result == ["analista", "datos"]

    def test_all_stopwords_falls_back_to_original_words(self):
        # Caso extremo, no deberia pasar en la practica, pero no debe
        # devolver una lista vacia (perderia la keyword por completo).
        result = expand_keyword_terms("de la y")
        assert result == ["de", "la", "y"]

    def test_empty_string_returns_empty_list(self):
        assert expand_keyword_terms("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert expand_keyword_terms("   ") == []

    def test_preserves_original_case(self):
        assert expand_keyword_terms("Analista de Datos") == ["Analista", "Datos"]

    def test_extra_whitespace_between_words_is_ignored(self):
        assert expand_keyword_terms("analista   de    datos") == ["analista", "datos"]
