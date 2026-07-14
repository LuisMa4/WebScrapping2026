from __future__ import annotations

# Palabras vacias en español: no aportan significado a una busqueda y se
# descartan al elegir que palabras de una keyword de varias palabras usar
# como terminos de busqueda independientes.
_SPANISH_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "en", "y", "o", "para",
    "con", "un", "una", "unos", "unas", "al", "a", "por", "su", "sus",
}


def expand_keyword_terms(keyword: str, max_terms: int = 3) -> list[str]:
    """
    Separa una keyword de varias palabras en terminos de busqueda
    independientes.

    Los portales buscan una keyword de varias palabras (ej. "analista de
    datos junior") como si TODAS las palabras tuvieran que aparecer juntas
    en la oferta -- eso descarta ofertas legitimas que solo usan parte de
    la frase y puede terminar en 0 resultados. En vez de mandar la frase
    completa, se buscan por separado hasta `max_terms` palabras
    significativas (sin stopwords) y se juntan los resultados -- basta con
    que UNA de ellas aparezca, en vez de exigir la frase completa.

    Una keyword de una sola palabra se devuelve sin cambios (no hay nada
    que aflojar).
    """
    words = keyword.strip().split()
    if len(words) <= 1:
        return [keyword.strip()] if keyword.strip() else []

    significant = [w for w in words if w.lower() not in _SPANISH_STOPWORDS]
    if not significant:
        significant = words

    return significant[:max_terms]
