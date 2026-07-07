"""
Sistema visual de SIVML: paleta semantica de estados + CSS global.
Logica pura (sin llamar a Streamlit) donde es posible, para poder testear
con pytest sin necesitar un runtime de Streamlit -- mismo patron que
template_cards.py y page_state.py.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Paleta semantica: un mismo significado (ok / parcial / bloqueado / neutral)
# se ve igual en todas las paginas (tabla de portales, estado de estudio,
# estado de busqueda) -- antes cada pagina mostraba el estado como texto
# plano sin color, o con el rojo de alerta por defecto de Streamlit sin
# relacion con el significado real.
# ---------------------------------------------------------------------------

_GREEN  = ("#E6F7EC", "#1B7A3D")   # fondo, texto -- ok / completado / operacional
_AMBER  = ("#FFF4E0", "#B7690A")   # parcial / en progreso / en cola
_RED    = ("#FDEBEC", "#C21F2E")   # fallido / bloqueado / error
_BLUE   = ("#E8EEFD", "#2C4CB0")   # informativo (poco usado, evita confundir con ok)
_GRAY   = ("#EEF0F3", "#5C6370")   # detenido / inactivo / sin dato

STATUS_META: dict[str, tuple[str, str, str]] = {
    # clave: (texto a mostrar, color_fondo, color_texto)
    "OPERACIONAL":    ("Operacional", *_GREEN),
    "PARCIAL":        ("Parcial", *_AMBER),
    "NO_OPERACIONAL": ("Bloqueado", *_RED),
    "REQUIERE_API":   ("Requiere API key", *_AMBER),
    "completed":      ("Completado", *_GREEN),
    "running":        ("En progreso", *_BLUE),
    "queued":         ("En cola", *_AMBER),
    "failed":         ("Fallido", *_RED),
    "stopped":        ("Detenido", *_GRAY),
}

def badge_html(status_key: str) -> str:
    """
    Pill HTML para un estado (portal o estudio). Usar con
    st.markdown(badge_html(...), unsafe_allow_html=True).
    Claves reconocidas: ver STATUS_META. Cualquier otra cae en un badge
    gris neutro con el texto tal cual, en vez de romper la pagina.
    """
    label, bg, fg = STATUS_META.get(status_key, (status_key, _GRAY[0], _GRAY[1]))
    return (
        f'<span style="'
        f'background:{bg}; color:{fg}; padding:2px 10px; border-radius:999px; '
        f'font-size:0.82rem; font-weight:600; white-space:nowrap; '
        f'display:inline-block; line-height:1.6;">{label}</span>'
    )


# Emoji cortos para lugares donde no se puede inyectar HTML crudo (labels de
# st.expander/st.tabs solo soportan markdown basico, no <span> con estilo).
STATUS_EMOJI: dict[str, str] = {
    "completed": "\U0001F7E2",  # circulo verde
    "running":   "\U0001F535",  # circulo azul
    "queued":    "\U0001F7E1",  # circulo amarillo
    "failed":    "\U0001F534",  # circulo rojo
    "stopped":   "⚫",      # circulo negro/gris
}


def status_emoji(status_key: str) -> str:
    return STATUS_EMOJI.get(status_key, "⚪")  # circulo blanco por defecto


# ---------------------------------------------------------------------------
# CSS global
# ---------------------------------------------------------------------------

GLOBAL_CSS = """
<style>
/* Tarjetas (containers con borde, expanders) -- esquinas redondeadas y
   sombra suave en vez del borde recto por defecto de Streamlit. */
div[data-testid="stExpander"],
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(16, 24, 64, 0.08);
}

/* Botones: esquinas redondeadas consistentes y transicion suave. El color
   primario ya lo da .streamlit/config.toml (primaryColor) -- aca solo se
   pareja la forma para que primarios y secundarios luzcan de la misma
   familia visual. */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
    border-radius: 8px !important;
    transition: transform 0.05s ease-in-out, box-shadow 0.15s ease-in-out;
}
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {
    box-shadow: 0 2px 6px rgba(16, 24, 64, 0.15);
}

/* Acciones destructivas (Eliminar, Detener) -- contenedor marcado con
   key=f"danger_zone_{id}" desde Python (el id varia por fila, ver
   dashboard/app.py), asi que se matchea por subcadena de clase en vez de
   una clase exacta: Streamlit expone el key como .st-key-<key>. */
div[class*="st-key-danger_zone"] button {
    border-color: #C21F2E !important;
    color: #C21F2E !important;
}
div[class*="st-key-danger_zone"] button:hover {
    background-color: #FDEBEC !important;
    border-color: #C21F2E !important;
    color: #C21F2E !important;
}

/* Metricas: etiqueta en mayusculas pequenas y mas tenue, para que el
   numero grande sea lo primero que se lee (jerarquia visual). */
div[data-testid="stMetricLabel"] {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.72rem !important;
    opacity: 0.75;
}

/* Sidebar: separa visualmente del contenido principal con un fondo propio
   (ya lo da secondaryBackgroundColor) y un poco mas de aire arriba del logo. */
section[data-testid="stSidebar"] .stRadio > label {
    font-weight: 600;
}

/* Responsive: en pantallas angostas, reducir el padding lateral del
   contenido principal para no desperdiciar espacio en un dispositivo chico. */
@media (max-width: 640px) {
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
}
</style>
"""


def inject_global_css(st_module) -> None:
    """Inyecta el CSS global una sola vez por render. Recibe el modulo
    `streamlit` importado por el llamador (evita importar streamlit aqui
    arriba, asi este archivo se puede testear sin tenerlo instalado)."""
    st_module.markdown(GLOBAL_CSS, unsafe_allow_html=True)
