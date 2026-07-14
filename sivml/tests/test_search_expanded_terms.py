"""
_search_with_expanded_terms(): para una keyword de varias palabras, busca
cada palabra significativa por separado (en vez de la frase completa, que
el portal trata como si todas las palabras tuvieran que aparecer juntas) y
junta los resultados sin duplicados.
"""
from datetime import datetime

from scraping import _search_with_expanded_terms
from scrapers.base import ScrapedJob


def _job(source_id, title="Oferta"):
    return ScrapedJob(
        source_id=source_id, portal="fake", url=f"https://x.com/{source_id}",
        scraped_at=datetime.utcnow(), title=title,
    )


class FakeScraperByTerm:
    """Devuelve resultados distintos segun el termino buscado, para probar
    que cada palabra de una keyword de varias palabras se busca por separado."""

    def __init__(self, results_by_term: dict[str, list[ScrapedJob]]):
        self.results_by_term = results_by_term
        self.calls: list[tuple[str, str]] = []

    def search(self, keyword, city):
        self.calls.append((keyword, city))
        return self.results_by_term.get(keyword, [])


class TestSearchWithExpandedTerms:
    def test_single_word_keyword_searches_once(self):
        scraper = FakeScraperByTerm({"contador": [_job("1")]})
        jobs = _search_with_expanded_terms(scraper, "contador", "Lima")
        assert scraper.calls == [("contador", "Lima")]
        assert [j.source_id for j in jobs] == ["1"]

    def test_multi_word_keyword_searches_each_significant_word(self):
        scraper = FakeScraperByTerm({
            "analista": [_job("a1")],
            "datos": [_job("d1")],
        })
        jobs = _search_with_expanded_terms(scraper, "analista de datos", "Lima")
        assert scraper.calls == [("analista", "Lima"), ("datos", "Lima")]
        assert {j.source_id for j in jobs} == {"a1", "d1"}

    def test_merges_results_from_all_terms(self):
        scraper = FakeScraperByTerm({
            "analista": [_job("a1"), _job("a2")],
            "datos": [_job("d1")],
        })
        jobs = _search_with_expanded_terms(scraper, "analista de datos", "Lima")
        assert len(jobs) == 3

    def test_deduplicates_same_source_id_across_terms(self):
        # La misma oferta puede calzar con mas de una palabra -- no debe
        # aparecer duplicada en el resultado final.
        scraper = FakeScraperByTerm({
            "analista": [_job("shared"), _job("a1")],
            "datos": [_job("shared"), _job("d1")],
        })
        jobs = _search_with_expanded_terms(scraper, "analista de datos", "Lima")
        source_ids = [j.source_id for j in jobs]
        assert source_ids.count("shared") == 1
        assert len(jobs) == 3  # shared + a1 + d1

    def test_returns_empty_list_when_no_term_matches(self):
        scraper = FakeScraperByTerm({})
        jobs = _search_with_expanded_terms(scraper, "analista de datos", "Lima")
        assert jobs == []
