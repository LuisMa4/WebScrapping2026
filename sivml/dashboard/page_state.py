from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Navegacion: resolver que pagina preseleccionar segun el query param de la URL
# ---------------------------------------------------------------------------


def resolve_page_index(pages: dict[str, str], query_page: str | None) -> int:
    """Indice a preseleccionar en el radio de navegacion segun ?page=... de la URL.

    Permite que un refresh (F5) del navegador conserve la pagina actual en vez
    de volver siempre a la primera opcion (Nuevo Estudio).
    """
    if query_page:
        for i, value in enumerate(pages.values()):
            if value == query_page:
                return i
    return 0


# ---------------------------------------------------------------------------
# Borrador del formulario "Nuevo Estudio": sobrevive a un refresh (F5) porque
# se guarda en disco en vez de en st.session_state (que se pierde con cada
# sesion nueva de Streamlit).
# ---------------------------------------------------------------------------

_DRAFT_FIELDS = [
    "study_name", "academic_program", "keywords_raw",
    "cities", "portals", "max_pages", "delay_min", "delay_max", "headless",
]


def load_draft(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_draft(path: Path, data: dict) -> None:
    payload = {k: data[k] for k in _DRAFT_FIELDS if k in data}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def clear_draft(path: Path) -> None:
    if path.exists():
        path.unlink()
