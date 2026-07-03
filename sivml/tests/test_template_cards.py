from dashboard.template_cards import template_summary


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
