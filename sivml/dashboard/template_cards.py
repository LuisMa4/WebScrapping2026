"""
Logica pura (sin dependencia de Streamlit) para las tarjetas de plantillas
en la pantalla "Nuevo Estudio". Separada de app.py para poder testear con
pytest sin necesitar un runtime de Streamlit.
"""
from __future__ import annotations


def template_summary(keywords: list[str], cities: list[str]) -> str:
    """Texto corto para una tarjeta de plantilla, ej. '3 keywords · Lima, +2 más'."""
    n_kw = len(keywords)
    kw_label = f"{n_kw} keyword" + ("" if n_kw == 1 else "s")

    if not cities:
        return kw_label

    city_label = cities[0]
    if len(cities) > 1:
        city_label += f", +{len(cities) - 1} más"

    return f"{kw_label} · {city_label}"
