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


def valid_defaults(saved_values: list[str], options: list[str]) -> list[str]:
    """
    Filtra `saved_values` (ej. las ciudades o portales guardados en una
    plantilla) para dejar solo los que siguen presentes en `options`.

    Necesario porque las listas de opciones (CITIES_PE, ALL_PORTALS) pueden
    reducirse con el tiempo -- una plantilla guardada ANTES del cambio
    puede tener valores que ya no existen. Pasar esos valores directo como
    `default=` de un st.multiselect revienta la pagina entera con
    StreamlitAPIException; filtrarlos primero lo evita.
    """
    options_set = set(options)
    return [v for v in saved_values if v in options_set]
