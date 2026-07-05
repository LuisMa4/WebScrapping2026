from dashboard.template_cards import template_summary, valid_defaults


class TestTemplateSummary:
    def test_single_keyword_single_city(self):
        assert template_summary(["analista de datos"], ["Lima"]) == "1 keyword · Lima"

    def test_multiple_keywords_single_city(self):
        assert template_summary(["a", "b", "c"], ["Lima"]) == "3 keywords · Lima"

    def test_multiple_cities_shows_first_plus_count(self):
        result = template_summary(["a"], ["Lima", "Arequipa", "Cusco"])
        assert result == "1 keyword · Lima, +2 más"

    def test_no_cities_omits_city_part(self):
        assert template_summary(["a", "b"], []) == "2 keywords"

    def test_no_keywords_still_returns_string(self):
        assert template_summary([], ["Lima"]) == "0 keywords · Lima"


class TestValidDefaults:
    """
    Regresion: cuando CITIES_PE se reduce (o ALL_PORTALS cambia), una
    plantilla guardada ANTES del cambio puede tener ciudades/portales que
    ya no estan en la lista de opciones actual. Pasar esos valores directo
    como `default=` de un st.multiselect revienta la pagina entera con
    StreamlitAPIException: "The default value 'X' is not part of the
    options." valid_defaults() filtra los valores obsoletos antes de
    pasarlos como default.
    """

    def test_keeps_values_still_in_options(self):
        assert valid_defaults(["Lima", "Cusco"], ["Lima", "Cusco", "Tacna"]) == ["Lima", "Cusco"]

    def test_drops_values_no_longer_in_options(self):
        assert valid_defaults(["Lima", "Trujillo", "Cusco"], ["Lima", "Cusco", "Tacna"]) == ["Lima", "Cusco"]

    def test_all_values_removed_returns_empty_list(self):
        assert valid_defaults(["Trujillo", "Chiclayo"], ["Lima", "Cusco"]) == []

    def test_empty_saved_values_returns_empty_list(self):
        assert valid_defaults([], ["Lima", "Cusco"]) == []

    def test_preserves_order_of_saved_values(self):
        assert valid_defaults(["Cusco", "Lima"], ["Lima", "Cusco"]) == ["Cusco", "Lima"]
