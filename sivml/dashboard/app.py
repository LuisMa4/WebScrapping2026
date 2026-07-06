"""
SIVML - Dashboard
Ejecutar desde sivml/: python -m streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

st.set_page_config(
    page_title="SIVML - Vigilancia del Mercado Laboral",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Bootstrap DB
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_db():
    from database.session import init_db
    init_db()
    # Limpiar navegadores de Playwright huerfanos de una sesion anterior
    # que se interrumpio abruptamente (crash, conflicto de puertos,
    # reinicio de Streamlit a mitad de un scraping).
    try:
        from scrapers.browser_cleanup import cleanup_orphaned_browsers
        cleanup_orphaned_browsers()
    except Exception:
        pass  # la limpieza es best-effort, nunca debe impedir que arranque el dashboard
    return True

_init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session():
    from database.session import SessionLocal
    return SessionLocal()

def _badge(status: str) -> str:
    return {
        "OPERACIONAL":    "OK",
        "PARCIAL":        "PARCIAL",
        "REQUIERE_API":   "API KEY",
        "NO_OPERACIONAL": "BLOQUEADO",
    }.get(status, "?")

def _badge_color(status: str) -> str:
    return {
        "OPERACIONAL":    "green",
        "PARCIAL":        "orange",
        "REQUIERE_API":   "red",
        "NO_OPERACIONAL": "red",
    }.get(status, "gray")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

PAGES = {
    "Nuevo Estudio":   "nuevo_estudio",
    "Mis Plantillas":  "mis_plantillas",
    "Mis Estudios":    "mis_estudios",
    "Resultados":      "resultados",
    "Estado Portales": "portales",
}

from dashboard.page_state import resolve_page_index

st.sidebar.title("SIVML")
st.sidebar.caption("Sistema Inteligente de Vigilancia del Mercado Laboral")
st.sidebar.divider()

_NAV_KEY = "sivml_nav_page_label"
if _NAV_KEY not in st.session_state:
    # Solo se ejecuta la PRIMERA vez que esta sesion renderiza el radio (justo
    # tras cargar la pagina/F5): siembra el valor inicial desde ?page=... de
    # la URL para que un refresh conserve la pagina actual en vez de volver
    # siempre a "Nuevo Estudio". Pasar index=... recalculado en cada rerun (en
    # vez de sembrar session_state una sola vez) rompe el radio: sin un key
    # fijo, Streamlit trata el widget como si cambiara de identidad en cada
    # rerun y se come uno de cada dos clicks de navegacion (reproducido con
    # Playwright: cada click alterno no actualizaba la pagina).
    idx = resolve_page_index(PAGES, st.query_params.get("page"))
    st.session_state[_NAV_KEY] = list(PAGES.keys())[idx]

page_label = st.sidebar.radio(
    "Navegacion", list(PAGES.keys()), key=_NAV_KEY, label_visibility="collapsed"
)
page = PAGES[page_label]
if st.query_params.get("page") != page:
    st.query_params["page"] = page
st.sidebar.divider()
st.sidebar.caption("v1.0 - Peru")

CITIES_PE = [
    # Ciudades habilitadas para el estudio (alcance reducido, julio 2026).
    "Lima", "Tacna", "Arequipa", "Moquegua", "Cusco", "Puno",
]
MAX_KEYWORDS = 5  # cada keyword adicional puede sumar varios minutos por ciudad/portal
from scrapers.portal_info import ACTIVE_PORTALS, INACTIVE_PORTALS
from dashboard.template_cards import template_summary, valid_defaults
ALL_PORTALS = ACTIVE_PORTALS  # laborum y jooble excluidos (0 resultados validados)

# ---------------------------------------------------------------------------
# PAGINA: Estado de Portales
# ---------------------------------------------------------------------------

def page_portales():
    st.title("Estado de Portales")
    st.caption("Informacion tecnica validada sobre cada portal de empleo.")

    from scrapers.portal_info import (
        PORTAL_STATUS, PORTAL_CAPABILITIES, RECOMMENDED_PORTALS, SAFE_COMBINATIONS
    )

    # Tabla resumen
    import pandas as pd
    rows = []
    for portal, info in PORTAL_STATUS.items():
        cap = PORTAL_CAPABILITIES.get(portal, {})
        rows.append({
            "Portal":           portal,
            "Estado":           info["status"],
            "Uso Simultaneo":   "Si" if cap.get("uso_simultaneo") else "No",
            "Max Keywords":     cap.get("max_keywords", "N/A"),
            "Anti-Bot":         cap.get("anti_bot", "N/A"),
            "Delay Recomendado": cap.get("delay_recomendado", "N/A"),
            "Recomendado":      "Recomendado" if portal in RECOMMENDED_PORTALS else "",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)

    st.divider()

    # Combinaciones seguras
    st.subheader("Combinaciones seguras para uso simultaneo")
    st.info(
        "Solo estos grupos de portales pueden ejecutarse en la misma sesion sin interferencia. "
        "LinkedIn e Indeed deben usarse siempre solos."
    )
    for combo in SAFE_COMBINATIONS:
        st.markdown(f"- `{' + '.join(combo)}`")

    st.divider()

    # Detalle por portal
    st.subheader("Detalle por portal")
    for portal, info in PORTAL_STATUS.items():
        status = info["status"]
        rec = " - Recomendado" if portal in RECOMMENDED_PORTALS else ""
        cap = PORTAL_CAPABILITIES.get(portal, {})

        with st.expander(f"**{portal.upper()}** [{_badge(status)}]{rec}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Estado:** `{status}`")
                st.markdown(f"**Nota:** {info['nota']}")
                if cap.get("nota_simultaneo"):
                    st.info(f"Uso simultaneo: {cap['nota_simultaneo']}")
            with col2:
                if cap:
                    st.markdown(f"**Paginacion:** {cap.get('paginacion','N/A')}")
                    st.markdown(f"**Anti-bot:** {cap.get('anti_bot','N/A')}")
                    st.markdown(f"**Campos disponibles:** {', '.join(cap.get('campos_disponibles',[]))}")
                    st.markdown(f"**Cobertura:** {cap.get('cobertura','N/A')}")
                    st.markdown(f"**Requiere login:** {'Si' if cap.get('requiere_login') else 'No'}")


# ---------------------------------------------------------------------------
# PAGINA 1: Nuevo Estudio
# ---------------------------------------------------------------------------

def page_nuevo_estudio():
    st.title("Nuevo Estudio de Mercado Laboral")

    from scrapers.portal_info import PORTAL_STATUS, RECOMMENDED_PORTALS
    from database import repository as repo
    from dashboard.page_state import load_draft, save_draft, clear_draft

    # ── Tarjetas de plantillas guardadas (visibles de inmediato, sin expander) ─
    session_pre = _session()
    templates = repo.list_templates(session_pre)
    session_pre.close()

    # Borrador en disco: sobrevive a un refresh (F5) del navegador, que crea
    # una sesion de Streamlit nueva y por lo tanto vacia st.session_state.
    draft_path = ROOT / ".sivml_draft_nuevo_estudio.json"

    # Valores iniciales (se sobreescriben si se carga una plantilla)
    if "form_defaults" in st.session_state:
        defaults = st.session_state["form_defaults"]
    else:
        defaults = load_draft(draft_path)

    st.session_state.setdefault("dismissed_template_ids", set())
    visible_templates = [
        t for t in templates if t.id not in st.session_state["dismissed_template_ids"]
    ]

    if visible_templates:
        st.markdown("**Tus plantillas:**")
        cols = st.columns(min(len(visible_templates), 4))
        for i, t in enumerate(visible_templates):
            with cols[i % 4]:
                with st.container(border=True):
                    st.markdown(f"**{t.name}**")
                    st.caption(template_summary(t.keywords, t.cities))
                    bcol1, bcol2 = st.columns([3, 1])
                    with bcol1:
                        if st.button("Cargar", key=f"load_tpl_{t.id}", use_container_width=True):
                            st.session_state["form_defaults"] = {
                                "study_name":       t.name,
                                "academic_program": t.academic_program,
                                "keywords_raw":     "\n".join(t.keywords),
                                "cities":           t.cities,
                                "portals":          t.portals,
                                "max_pages":        t.max_pages,
                                "delay_min":        t.delay_min,
                                "delay_max":        t.delay_max,
                                "headless":         t.headless,
                                "tpl_id":           t.id,
                            }
                            st.rerun()
                    with bcol2:
                        if st.button("✕", key=f"dismiss_tpl_{t.id}", help="Ocultar por esta sesion"):
                            st.session_state["dismissed_template_ids"].add(t.id)
                            st.rerun()

        if defaults.get("tpl_id"):
            st.success(f"Plantilla cargada: **{defaults['study_name']}** — edita los campos si necesitas y lanza.")

    # ── Guardar como plantilla — FUERA del form a proposito ─────────────────────
    # Streamlit no re-renderiza widgets condicionales dentro de un st.form() hasta
    # el submit, asi que el checkbox y el campo de nombre deben vivir aqui afuera
    # para que el campo de texto aparezca apenas se marca el checkbox.
    st.divider()
    save_as_tpl = st.checkbox(
        "Guardar esta configuracion como plantilla para reutilizarla",
        key="save_as_tpl_cb",
    )
    tpl_name_input = ""
    if save_as_tpl:
        tpl_name_input = st.text_input(
            "Nombre de la plantilla *",
            placeholder="Salud Publica - Lima",
            key="tpl_name_input_field",
        )

    # ── Formulario principal ────────────────────────────────────────────────────
    with st.form("form_estudio"):
        col1, col2 = st.columns(2)
        with col1:
            study_name = st.text_input(
                "Nombre del estudio *",
                value=defaults.get("study_name", ""),
                placeholder="Demanda Laboral - Salud Publica 2026",
            )
            academic_program = st.text_input(
                "Programa academico *",
                value=defaults.get("academic_program", ""),
                placeholder="Maestria en Salud Publica",
            )
            keywords_raw = st.text_area(
                f"Palabras clave * (una por linea, maximo {MAX_KEYWORDS})",
                value=defaults.get("keywords_raw", ""),
                placeholder="salud publica\nepidemiologia\ngestion hospitalaria",
                height=130,
                help=f"Cada palabra clave adicional suma tiempo de scraping por cada ciudad y portal seleccionados. Maximo {MAX_KEYWORDS}.",
            )
        with col2:
            cities = st.multiselect(
                "Ciudades *", CITIES_PE,
                default=valid_defaults(defaults.get("cities", list(CITIES_PE)), CITIES_PE),
            )
            portals = st.multiselect(
                "Portales *", ALL_PORTALS,
                default=valid_defaults(defaults.get("portals", ["computrabajo", "bumeran"]), ALL_PORTALS),
                help="Computrabajo + Bumeran es la combinacion mas estable.",
            )
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                date_from = st.date_input("Desde", value=date.today() - timedelta(days=7))
            with col_d2:
                date_to = st.date_input("Hasta", value=date.today())

        # Estado de portales seleccionados
        if portals:
            st.markdown("**Estado de los portales seleccionados:**")
            cols = st.columns(min(len(portals), 4))
            for i, p in enumerate(portals):
                info = PORTAL_STATUS.get(p, {})
                s = info.get("status", "")
                with cols[i % 4]:
                    st.markdown(f"`{p}` **[{_badge(s)}]**")
                    if s != "OPERACIONAL":
                        st.caption(info.get("nota", "")[:100])

        st.divider()
        # key fijo: sin el, el expander pierde su estado abierto/cerrado tras
        # cada envio del formulario (reproducido en vivo: al enviar varios
        # estudios seguidos, "Opciones avanzadas" -- y por lo tanto el
        # checkbox de Dry run que vive adentro -- se colapsaba solo en cada
        # envio siguiente, obligando a volver a abrirlo cada vez).
        with st.expander("Opciones avanzadas", expanded=False, key="nuevo_estudio_adv_expander"):
            c3, c4, c5 = st.columns(3)
            with c3:
                max_pages = st.number_input("Max paginas/busqueda", min_value=1, max_value=100,
                                             value=defaults.get("max_pages", 10))
            with c4:
                delay_min = st.number_input("Espera minima (s)", min_value=0.5, max_value=10.0,
                                             value=float(defaults.get("delay_min", 2.0)), step=0.5)
            with c5:
                delay_max = st.number_input("Espera maxima (s)", min_value=1.0, max_value=20.0,
                                             value=float(defaults.get("delay_max", 5.0)), step=0.5)

            c6, c7 = st.columns(2)
            with c6:
                headless = st.checkbox("Navegador oculto (headless)", value=defaults.get("headless", True))
            with c7:
                dry_run = st.checkbox(
                    "Dry run - solo listing (mas rapido, sin descripcion completa)",
                    help=(
                        "Dry run: extrae titulo, empresa, ciudad y salario del listado. "
                        "No visita cada oferta individualmente. "
                        "Los campos de modalidad, experiencia y educacion estaran vacios."
                    ),
                )

        submitted = st.form_submit_button("Crear estudio y ejecutar scraping", type="primary", use_container_width=True)

    # Autoguardar el progreso del formulario en disco en cada rerun (aunque no
    # se haya presionado "Crear estudio"), para que un refresh (F5) -- que
    # crea una sesion de Streamlit nueva y vacia st.session_state -- pueda
    # recuperarlo en vez de mostrar el formulario en blanco.
    save_draft(draft_path, {
        "study_name": study_name,
        "academic_program": academic_program,
        "keywords_raw": keywords_raw,
        "cities": cities,
        "portals": portals,
        "max_pages": int(max_pages),
        "delay_min": delay_min,
        "delay_max": delay_max,
        "headless": headless,
    })

    if submitted:
        errors = []
        if not study_name.strip():
            errors.append("El nombre del estudio es obligatorio.")
        if not academic_program.strip():
            errors.append("El programa academico es obligatorio.")
        keywords = [k.strip() for k in keywords_raw.splitlines() if k.strip()]
        if not keywords:
            errors.append("Ingresa al menos una palabra clave.")
        elif len(keywords) > MAX_KEYWORDS:
            errors.append(f"Maximo {MAX_KEYWORDS} palabras clave por estudio (ingresaste {len(keywords)}).")
        if not cities:
            errors.append("Selecciona al menos una ciudad.")
        if not portals:
            errors.append("Selecciona al menos un portal.")
        if date_from > date_to:
            errors.append("La fecha 'Desde' no puede ser posterior a 'Hasta'.")
        if save_as_tpl and not tpl_name_input.strip():
            errors.append("Ingresa un nombre para la plantilla.")

        for p in portals:
            info = PORTAL_STATUS.get(p, {})
            s = info.get("status", "")
            if s == "REQUIERE_API":
                st.warning(f"{p}: {info['nota']}")
            elif s == "NO_OPERACIONAL":
                st.error(f"{p}: {info['nota']}")

        if errors:
            for e in errors:
                st.error(e)
        else:
            # Guardar plantilla si se pidio
            if save_as_tpl:
                sess_tpl = _session()
                repo.create_template(sess_tpl, {
                    "name": tpl_name_input.strip(),
                    "academic_program": academic_program.strip(),
                    "keywords": keywords,
                    "cities": cities,
                    "portals": portals,
                    "max_pages": int(max_pages),
                    "delay_min": delay_min,
                    "delay_max": delay_max,
                    "headless": headless,
                })
                sess_tpl.close()
                st.success(f"Plantilla **{tpl_name_input.strip()}** guardada.")

            # Limpiar defaults de session_state y el borrador en disco al lanzar
            st.session_state.pop("form_defaults", None)
            clear_draft(draft_path)

            _launch_study(
                study_name=study_name.strip(),
                academic_program=academic_program.strip(),
                keywords=keywords,
                cities=cities,
                portals=portals,
                date_from=date_from,
                date_to=date_to,
                max_pages=int(max_pages),
                delay_range=(delay_min, delay_max),
                headless=headless,
                dry_run=dry_run,
            )


def _launch_study(**params) -> None:
    """
    Crea el StudyConfig y lo entrega a study_runner: arranca en segundo
    plano de inmediato si hay cupo, o queda 'en cola' si ya hay
    MAX_CONCURRENT_STUDIES corriendo (se arranca solo cuando se libera un
    cupo). No bloquea la pantalla -- el progreso se sigue en "Mis Estudios".
    """
    from config.settings import StudyConfig, ScraperConfig
    from study_runner import start_or_queue_study, MAX_CONCURRENT_STUDIES

    cfg = StudyConfig(
        study_name=params["study_name"],
        academic_program=params["academic_program"],
        keywords=params["keywords"],
        cities=params["cities"],
        portals=params["portals"],
        date_from=params["date_from"],
        date_to=params["date_to"],
        scraper=ScraperConfig(
            delay_range=params["delay_range"],
            max_pages=params["max_pages"],
            headless=params["headless"],
        ),
    )
    session = _session()
    try:
        study = start_or_queue_study(session, cfg, dry_run=params["dry_run"])
        if study.status == "queued":
            st.info(
                f"Ya hay {MAX_CONCURRENT_STUDIES} estudios corriendo. "
                f"**{study.name}** quedo en cola y arrancara automaticamente "
                f"en cuanto se libere un cupo. Sigue su progreso en **Mis Estudios**."
            )
        else:
            st.success(
                f"Estudio **{study.name}** iniciado en segundo plano. "
                f"Sigue su progreso en **Mis Estudios**."
            )
    finally:
        session.close()
    # Deja la URL lista para cuando el usuario navegue a Mis Estudios (o
    # refresque): no fuerza la navegacion en esta misma sesion (el radio del
    # sidebar ya fue instanciado en este script run; reasignar su
    # session_state aqui lanzaria StreamlitAPIException).
    st.query_params["page"] = "mis_estudios"


# ---------------------------------------------------------------------------
# PAGINA 2: Mis Estudios
# ---------------------------------------------------------------------------

def _find_latest_excel(study_id: str):
    output_dir = ROOT / "output"
    matches = sorted(output_dir.glob(f"SIVML_{study_id[:8]}_*.xlsx"))
    return matches[-1] if matches else None


def _render_pending_auto_downloads() -> None:
    """
    Banner destacado + boton de descarga para estudios que acaban de
    terminar (detectados por el fragment de Mis Estudios, que solo guarda el
    pendiente en session_state -- ver el comentario en page_mis_estudios).

    NOTA: un <script> que dispara un click programatico (sin interaccion
    real del usuario) para descargar un archivo NO funciona de forma
    confiable -- los navegadores modernos bloquean silenciosamente las
    descargas que no se originan en un gesto real del usuario (verificado en
    vivo: el anchor con el archivo en base64 SI llegaba al DOM, pero el
    evento de descarga nunca se disparaba). Como el estudio ahora corre en
    segundo plano y termina sin que el usuario haga click en nada en ese
    instante, ninguna descarga "silenciosa" es posible en ningun navegador.
    En su lugar: un banner dificil de ignorar con un st.download_button real
    (un click genuino del usuario, que si es un gesto valido) -- la senal
    de que termino sigue siendo inmediata y visible, solo requiere un click.

    El pendiente NO se limpia hasta que el usuario descarga o descarta el
    banner explicitamente: esta funcion solo se re-ejecuta en un rerun
    COMPLETO (no en cada tick de 5s del fragment, que es fragment-scoped y
    no toca codigo de afuera) -- si se limpiara apenas se dibuja una vez,
    el banner podia desaparecer con el siguiente rerun completo (ej. el
    usuario hace click en cualquier otra cosa) sin que el usuario alcanzara
    a verlo o descargarlo.
    """
    pending = st.session_state.get("_pending_auto_dl")
    if not pending:
        return

    from database import repository as repo
    session = _session()
    try:
        for sid in list(pending):
            study = repo.get_study(session, sid)
            name = study.name if study else sid[:8]
            filepath = _find_latest_excel(sid)
            with st.container(border=True):
                st.success(f"**Estudio completado: {name}**")
                bcol1, bcol2 = st.columns([4, 1])
                with bcol1:
                    if filepath and filepath.exists():
                        clicked = st.download_button(
                            label=f"Descargar Excel ({filepath.stat().st_size // 1024} KB)",
                            data=filepath.read_bytes(),
                            file_name=filepath.name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                            key=f"auto_dl_btn_{sid}",
                        )
                        if clicked:
                            st.session_state["_pending_auto_dl"].discard(sid)
                            st.session_state[f"_auto_dl_done_{sid}"] = True
                    else:
                        st.caption("Sin ofertas para exportar (0 resultados o descartadas por duplicado).")
                with bcol2:
                    if st.button("Descartar", key=f"dismiss_auto_dl_{sid}"):
                        st.session_state["_pending_auto_dl"].discard(sid)
                        st.session_state[f"_auto_dl_done_{sid}"] = True
                        st.rerun()
    finally:
        session.close()


def _render_study_body(session, study):
    """Cuerpo comun (metricas, aviso de estancado/detener, tabla de busquedas,
    acciones) para un estudio -- usado tanto en las pestanas 'En curso' como
    en el Historial."""
    from database import repository as repo
    from processing.deduplicator import run_exact_dedup, run_fuzzy_dedup
    from exports.excel_exporter import export_study_to_excel
    from database.models import ScrapingRun
    from sqlalchemy import select
    import pandas as pd
    from scrapers.portal_info import PORTAL_STATUS as PS

    raw_count = len(repo.get_raw_jobs_for_study(session, study.id))
    jobs_count = len(repo.get_jobs_for_study(session, study.id))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Scrapeadas", raw_count)
    m2.metric("Unicas (dedup)", jobs_count)
    m3.metric("Estado", study.status)
    m4.metric("Programa", (study.academic_program or "-")[:18])
    st.caption(f"ID: `{study.id}`")

    if study.status == "running":
        last_activity = repo.get_last_activity(session, study.id)
        if repo.is_study_stale(study, last_activity, threshold_minutes=15):
            ref = last_activity or study.started_at
            st.warning(
                f"Este estudio dice \"En progreso\" pero no ha tenido actividad desde "
                f"{ref.strftime('%Y-%m-%d %H:%M')} (mas de 15 minutos). "
                f"Probablemente el proceso de scraping murio a mitad de camino "
                f"(cierre inesperado, conflicto de puertos, etc.). Los datos ya "
                f"recolectados ({raw_count} ofertas) no se pierden."
            )
            stale_key = f"confirm_stale_{study.id}"
            st.checkbox("Confirmo que quiero marcar este estudio como fallido", key=stale_key)
            if st.button("Marcar como fallido", key=f"mark_failed_{study.id}"):
                if st.session_state.get(stale_key):
                    repo.mark_study_failed(
                        session, study.id,
                        reason="Marcado como fallido: sin actividad por mas de 15 minutos (proceso interrumpido)",
                    )
                    st.success("Estudio marcado como fallido.")
                    st.rerun()
                else:
                    st.error("Marca la casilla de confirmacion primero.")

        if study.stop_requested:
            st.info(
                "Detencion solicitada -- se detendra apenas termine la busqueda "
                "keyword/ciudad que este en curso en este momento."
            )
        else:
            stop_key = f"confirm_stop_{study.id}"
            st.checkbox("Confirmo que quiero detener este estudio", key=stop_key)
            if st.button("Detener", key=f"stop_{study.id}"):
                if st.session_state.get(stop_key):
                    repo.request_stop(session, study.id)
                    st.success(
                        "Detencion solicitada. Los datos ya recolectados no se pierden; "
                        "el estudio se detendra en cuanto termine la busqueda en curso."
                    )
                    st.rerun()
                else:
                    st.error("Marca la casilla de confirmacion primero.")

    runs = session.scalars(select(ScrapingRun).where(ScrapingRun.study_id == study.id)).all()
    if runs:
        run_df = pd.DataFrame([{
            "Portal":   r.portal,
            "Keyword":  r.keyword,
            "Ciudad":   r.city,
            "Halladas": r.records_found,
            "Nuevas":   r.records_new,
            "Estado":   r.status,
            "Error":    r.error_message or "",
        } for r in runs])

        errors_count = int((run_df["Error"] != "").sum())
        zero_count = int((run_df["Halladas"] == 0).sum())
        ok_count = int((run_df["Estado"] == "completed").sum())

        c_ok, c_warn, c_err = st.columns(3)
        c_ok.metric("Busquedas OK", ok_count)
        c_warn.metric("Con 0 resultados", zero_count)
        c_err.metric("Con error", errors_count)

        if errors_count > 0 or zero_count > 0:
            with st.expander(f"Ver problemas ({errors_count} errores, {zero_count} vacias)"):
                prob = run_df[(run_df["Error"] != "") | (run_df["Halladas"] == 0)].copy()
                def _diag(row):
                    if row["Error"]:
                        return row["Error"][:100]
                    info = PS.get(row["Portal"], {})
                    return info.get("nota", "Sin resultados")[:100]
                prob["Diagnostico"] = prob.apply(_diag, axis=1)
                st.dataframe(prob[["Portal", "Keyword", "Ciudad", "Halladas", "Diagnostico"]], hide_index=True, use_container_width=True)

    st.divider()
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Procesar", key=f"proc_{study.id}", use_container_width=True):
            with st.spinner("Procesando..."):
                s1 = run_exact_dedup(session, study.id)
                s2 = run_fuzzy_dedup(session, study.id)
            st.success(f"{s1['jobs_created']} jobs unicos | {s1['duplicates_marked']} duplicados | {s2['merged']} fusionados")
            st.rerun()
    with b2:
        if st.button("Exportar Excel", key=f"exp_{study.id}", use_container_width=True):
            output_dir = ROOT / "output"
            with st.spinner("Generando Excel..."):
                filepath = export_study_to_excel(session, study.id, output_dir=output_dir)
            kb = filepath.stat().st_size // 1024
            if kb > 0:
                with open(filepath, "rb") as f:
                    st.download_button(
                        label=f"Descargar ({kb} KB)",
                        data=f,
                        file_name=filepath.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{study.id}",
                    )
            else:
                st.error(f"Excel vacio ({kb} KB). Procesa el estudio primero.")
    with b3:
        if st.button("Ver Resultados", key=f"view_{study.id}", use_container_width=True):
            st.session_state["selected_study_id"] = study.id
            st.info("Ve a la pestana Resultados.")
    with b4:
        del_key = f"confirm_del_{study.id}"
        st.checkbox("Confirmar", key=del_key, help="Marca esta casilla y luego presiona Eliminar.")
        if st.button("Eliminar", key=f"del_{study.id}", use_container_width=True):
            if st.session_state.get(del_key):
                repo.delete_study(session, study.id)
                st.success(f"Estudio '{study.name}' eliminado.")
                st.rerun()
            else:
                st.error("Marca la casilla de confirmacion primero.")


@st.fragment(run_every=5)
def page_mis_estudios():
    # Fragment con auto-refresh: sin esto, una pestana con "Mis Estudios"
    # abierta nunca se enteraria de que un estudio cambio de estado (running
    # -> completed/stopped, o queued -> running) en OTRA pestana/sesion,
    # porque Streamlit solo re-ejecuta el script ante una interaccion del
    # usuario. Re-consulta la BD cada 5s y solo redibuja este fragmento.
    from database import repository as repo
    from study_runner import MAX_CONCURRENT_STUDIES

    st.title("Mis Estudios")
    session = _session()
    try:
        studies = repo.list_studies(session)
        if not studies:
            st.info("No hay estudios. Ve a Nuevo Estudio para crear uno.")
            return

        running = [s for s in studies if s.status == "running"]
        queued = [s for s in studies if s.status == "queued"]
        history = [s for s in studies if s.status not in ("running", "queued")]

        # ── Deteccion de estudios recien terminados (para auto-descarga) ────
        # Un estudio corre en un hilo de fondo que ya genero el Excel antes de
        # que esta pestana note el cambio de estado -- comparamos contra la
        # ultima vez que este fragment reviso, para disparar la descarga
        # automatica exactamente una vez por estudio y por sesion.
        st.session_state.setdefault("_seen_running_ids", set())
        st.session_state.setdefault("_pending_auto_dl", set())
        current_running_ids = {s.id for s in running}
        just_finished_ids = st.session_state["_seen_running_ids"] - current_running_ids
        st.session_state["_seen_running_ids"] = current_running_ids

        new_pending = False
        for sid in just_finished_ids:
            if not st.session_state.get(f"_auto_dl_done_{sid}"):
                st.session_state["_pending_auto_dl"].add(sid)
                new_pending = True

        if new_pending:
            # st.components.v1.html() (usado por la descarga automatica) no
            # se ejecuta de forma confiable en el navegador cuando se llama
            # DENTRO del arbol de un fragment -- verificado en vivo: pese a
            # forzar un rerun de scope='app' desde aca (que si vuelve a
            # ejecutar dashboard/app.py entero, confirmado con logs), el
            # iframe nunca llegaba al DOM real. _render_pending_auto_downloads()
            # se llama FUERA de este fragment (ver el dispatcher de paginas
            # mas abajo) -- ahi si funciona. Este rerun solo sirve para darle
            # a esa funcion la oportunidad de correr con el pendiente ya
            # guardado en session_state.
            st.rerun(scope="app")

        # ── Seccion: En curso (pestanas) + En cola (lista compacta) ─────────
        if running or queued:
            header = f"En curso: {len(running)}/{MAX_CONCURRENT_STUDIES} corriendo"
            if queued:
                header += f", {len(queued)} en cola"
            st.subheader(header)

            if queued:
                # key fijo (no basado en el label, que cambia con len(queued)):
                # sin esto, el expander pierde su identidad -- y por lo tanto
                # su estado abierto/cerrado -- cada vez que cambia la cantidad
                # de estudios en cola, colapsandose solo apenas se agrega o
                # quita uno (reproducido en vivo con Playwright).
                with st.expander(f"Estudios en cola ({len(queued)})", expanded=False, key="queued_expander"):
                    for i, q in enumerate(queued, start=1):
                        qc1, qc2 = st.columns([5, 1])
                        is_stale_q = repo.is_study_stale(q, None, threshold_minutes=15)
                        with qc1:
                            st.markdown(f"**#{i}** {q.name}")
                            if q.stop_requested:
                                st.caption("Cancelado -- se marcara como detenido en cuanto se libere un cupo.")
                            elif is_stale_q:
                                st.warning(
                                    "Lleva mas de 15 minutos en cola sin arrancar -- probablemente "
                                    "el dashboard se reinicio antes de poder promoverlo."
                                )
                        with qc2:
                            if not q.stop_requested:
                                if st.button("Cancelar", key=f"cancel_q_{q.id}", use_container_width=True):
                                    repo.request_stop(session, q.id)
                                    st.rerun()
                            if is_stale_q:
                                if st.button("Marcar como fallido", key=f"fail_q_{q.id}", use_container_width=True):
                                    repo.mark_study_failed(
                                        session, q.id,
                                        reason="Marcado como fallido: mas de 15 minutos en cola sin arrancar",
                                    )
                                    st.rerun()

            if running:
                tabs = st.tabs([s.name[:30] or s.id[:8] for s in running])
                for tab, study in zip(tabs, running):
                    with tab:
                        _render_study_body(session, study)

        # ── Historial ────────────────────────────────────────────────────────
        st.subheader("Historial")
        if not history:
            st.caption("Todavia no hay estudios finalizados.")
        for study in history:
            icon = {"completed": "Completado", "failed": "Fallido", "stopped": "Detenido"}.get(study.status, study.status)
            fecha = study.started_at.strftime("%Y-%m-%d %H:%M") if study.started_at else "-"
            with st.expander(f"[{icon}] {study.name} - {fecha}"):
                _render_study_body(session, study)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# PAGINA: Mis Plantillas
# ---------------------------------------------------------------------------

def page_mis_plantillas():
    from datetime import timedelta
    from database import repository as repo
    from config.settings import StudyConfig, ScraperConfig

    st.title("Mis Plantillas")
    st.caption("Configuraciones guardadas para reutilizar. Solo actualizas las fechas y lanzas.")

    session = _session()
    try:
        templates = repo.list_templates(session)

        if not templates:
            st.info("No tienes plantillas guardadas. Ve a **Nuevo Estudio** y marca 'Guardar como plantilla' al configurar un estudio.")
            return

        for tpl in templates:
            last_run = tpl.last_run_at.strftime("%Y-%m-%d %H:%M") if tpl.last_run_at else "Nunca ejecutada"
            created = tpl.created_at.strftime("%Y-%m-%d") if tpl.created_at else "-"

            with st.expander(f"**{tpl.name}** — {tpl.academic_program}", expanded=False):
                # Metadata en columnas
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Usos", tpl.run_count)
                mc2.metric("Ultima ejecucion", last_run)
                mc3.metric("Creada", created)
                mc4.metric("Keywords", len(tpl.keywords))

                # Tags de portales y keywords
                st.markdown("**Portales:** " + "  ".join(f"`{p}`" for p in tpl.portals))
                kws = tpl.keywords
                kw_display = ", ".join(kws[:3]) + (f" y {len(kws)-3} mas" if len(kws) > 3 else "")
                st.markdown(f"**Keywords:** {kw_display}")
                if tpl.notes:
                    st.caption(tpl.notes)

                st.divider()

                # ── Tabs: Ejecutar / Editar / Eliminar ────────────────────
                tab_run, tab_edit, tab_del = st.tabs(["Ejecutar", "Editar", "Eliminar"])

                # ── TAB: EJECUTAR ──────────────────────────────────────────
                with tab_run:
                    st.markdown("**Selecciona el rango de fechas:**")

                    today = date.today()
                    preset_col, _ = st.columns([2, 3])
                    with preset_col:
                        preset = st.radio(
                            "Periodo",
                            ["Esta semana (7d)", "Ultimo mes (30d)", "Ultimos 3 meses (90d)", "Personalizado"],
                            key=f"preset_{tpl.id}",
                            horizontal=False,
                        )

                    if preset == "Esta semana (7d)":
                        df_from, df_to = today - timedelta(days=7), today
                    elif preset == "Ultimo mes (30d)":
                        df_from, df_to = today - timedelta(days=30), today
                    elif preset == "Ultimos 3 meses (90d)":
                        df_from, df_to = today - timedelta(days=90), today
                    else:
                        df_from = tpl.last_run_at.date() if tpl.last_run_at else today - timedelta(days=30)
                        df_to = today

                    dc1, dc2 = st.columns(2)
                    with dc1:
                        run_date_from = st.date_input("Desde", value=df_from, key=f"dfrom_{tpl.id}")
                    with dc2:
                        run_date_to = st.date_input("Hasta", value=df_to, key=f"dto_{tpl.id}")

                    dry_run_tpl = st.checkbox("Dry run", key=f"dry_{tpl.id}",
                                               help="Solo listing, sin descripcion completa. Mas rapido.")

                    if st.button("Lanzar scraping", type="primary", key=f"run_{tpl.id}", use_container_width=True):
                        if run_date_from > run_date_to:
                            st.error("La fecha 'Desde' no puede ser posterior a 'Hasta'.")
                            st.stop()
                        repo.mark_template_used(session, tpl.id)
                        _launch_study(
                            study_name=f"{tpl.name} ({run_date_from} / {run_date_to})",
                            academic_program=tpl.academic_program,
                            keywords=tpl.keywords,
                            cities=tpl.cities,
                            portals=tpl.portals,
                            date_from=run_date_from,
                            date_to=run_date_to,
                            max_pages=tpl.max_pages,
                            delay_range=(tpl.delay_min, tpl.delay_max),
                            headless=tpl.headless,
                            dry_run=dry_run_tpl,
                        )

                # ── TAB: EDITAR ────────────────────────────────────────────
                with tab_edit:
                    with st.form(f"edit_tpl_{tpl.id}"):
                        e_name = st.text_input("Nombre", value=tpl.name)
                        e_prog = st.text_input("Programa academico", value=tpl.academic_program)
                        e_kw   = st.text_area(f"Keywords (una por linea, maximo {MAX_KEYWORDS})", value="\n".join(tpl.keywords), height=100)
                        e_city = st.multiselect("Ciudades", CITIES_PE, default=valid_defaults(tpl.cities, CITIES_PE))
                        e_port = st.multiselect("Portales", ALL_PORTALS, default=valid_defaults(tpl.portals, ALL_PORTALS))
                        e_notes = st.text_input("Notas (opcional)", value=tpl.notes or "")
                        e_pages = st.number_input("Max paginas", min_value=1, max_value=100, value=tpl.max_pages)

                        if st.form_submit_button("Guardar cambios", type="primary"):
                            new_kws = [k.strip() for k in e_kw.splitlines() if k.strip()]
                            if not e_name.strip() or not new_kws or not e_city or not e_port:
                                st.error("Nombre, keywords, ciudades y portales son obligatorios.")
                            elif len(new_kws) > MAX_KEYWORDS:
                                st.error(f"Maximo {MAX_KEYWORDS} palabras clave por plantilla (ingresaste {len(new_kws)}).")
                            else:
                                repo.update_template(session, tpl.id, {
                                    "name": e_name.strip(),
                                    "academic_program": e_prog.strip(),
                                    "keywords": new_kws,
                                    "cities": e_city,
                                    "portals": e_port,
                                    "notes": e_notes.strip() or None,
                                    "max_pages": int(e_pages),
                                })
                                st.success("Plantilla actualizada.")
                                st.rerun()

                # ── TAB: ELIMINAR ──────────────────────────────────────────
                with tab_del:
                    st.warning(f"Esta accion eliminara la plantilla **{tpl.name}**. Los estudios ya ejecutados con ella NO se eliminan.")
                    confirm_key = f"confirm_del_{tpl.id}"
                    st.checkbox("Confirmo que quiero eliminar esta plantilla", key=confirm_key)
                    if st.button("Eliminar plantilla", type="primary", key=f"del_{tpl.id}"):
                        if st.session_state.get(confirm_key):
                            repo.delete_template(session, tpl.id)
                            st.success("Plantilla eliminada.")
                            st.rerun()
                        else:
                            st.error("Marca la casilla de confirmacion primero.")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# PAGINA 3: Resultados
# ---------------------------------------------------------------------------

def page_resultados():
    st.title("Resultados")
    session = _session()
    try:
        from database import repository as repo
        import pandas as pd
        import plotly.express as px

        studies = repo.list_studies(session)
        if not studies:
            st.info("No hay estudios todavia.")
            return

        study_options = {f"{s.name} ({s.id[:8]})": s.id for s in studies}
        default_label = None
        if "selected_study_id" in st.session_state:
            for label, sid in study_options.items():
                if sid == st.session_state["selected_study_id"]:
                    default_label = label
                    break

        selected_label = st.selectbox(
            "Selecciona un estudio",
            list(study_options.keys()),
            index=list(study_options.keys()).index(default_label) if default_label else 0,
        )
        study_id = study_options[selected_label]
        study = repo.get_study(session, study_id)
        jobs = repo.get_jobs_for_study(session, study_id)

        if not jobs:
            st.warning("Sin ofertas procesadas. Ve a Mis Estudios y presiona Procesar.")
            return

        df = pd.DataFrame([{
            "ID":          j.id,
            "Titulo":      j.title_normalized or "-",
            "Empresa":     j.company_normalized or "-",
            "Ciudad":      j.city_normalized or "-",
            "Portal":      j.portal or "-",
            "Fecha":       j.posted_date,
            "Modalidad":   j.modality or "-",
            "Educacion":   j.education_level or "-",
            "Exp. Min":    j.experience_years_min,
            "Salario Min": j.salary_min,
            "Salario Max": j.salary_max,
            "Moneda":      j.salary_currency or "-",
            "URL":         j.url or "",
        } for j in jobs])

        st.subheader(study.name)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ofertas unicas", len(df))
        m2.metric("Con salario", int(df["Salario Min"].notna().sum()))
        m3.metric("Ciudades", df["Ciudad"].nunique())
        m4.metric("Empresas", df["Empresa"].nunique())

        raw_jobs = repo.get_raw_jobs_for_study(session, study_id)
        sin_desc = sum(1 for r in raw_jobs if not r.description_raw)
        if raw_jobs and sin_desc > len(raw_jobs) * 0.5:
            st.warning(f"{sin_desc}/{len(raw_jobs)} ofertas sin descripcion (posiblemente dry run).")

        st.divider()

        with st.expander("Filtros", expanded=True):
            fc1, fc2, fc3, fc4 = st.columns(4)
            with fc1:
                f_ciudad = st.selectbox("Ciudad", ["Todas"] + sorted(df["Ciudad"].dropna().unique().tolist()))
            with fc2:
                f_portal = st.selectbox("Portal", ["Todos"] + sorted(df["Portal"].dropna().unique().tolist()))
            with fc3:
                f_modal = st.selectbox("Modalidad", ["Todas"] + sorted(df["Modalidad"].dropna().unique().tolist()))
            with fc4:
                f_edu = st.selectbox("Educacion", ["Todas"] + sorted(df["Educacion"].dropna().unique().tolist()))

        mask = pd.Series([True] * len(df), index=df.index)
        if f_ciudad != "Todas":  mask &= df["Ciudad"] == f_ciudad
        if f_portal != "Todos":  mask &= df["Portal"] == f_portal
        if f_modal != "Todas":   mask &= df["Modalidad"] == f_modal
        if f_edu != "Todas":     mask &= df["Educacion"] == f_edu

        df_f = df[mask].copy()
        st.caption(f"{len(df_f)} ofertas con los filtros aplicados")

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "Tabla", "Por Ciudad", "Por Empresa", "Por Portal", "Tendencia", "Salarios"
        ])

        with tab1:
            cols = ["Titulo", "Empresa", "Ciudad", "Portal", "Fecha", "Modalidad", "Educacion", "Salario Min", "Moneda", "URL"]
            st.dataframe(df_f[cols], use_container_width=True, hide_index=True)

        with tab2:
            cc = df_f.groupby("Ciudad").size().reset_index(name="Vacantes").sort_values("Vacantes", ascending=False)
            if not cc.empty:
                st.plotly_chart(px.bar(cc, x="Ciudad", y="Vacantes", color="Vacantes", color_continuous_scale="Blues"), use_container_width=True)
                st.dataframe(cc, hide_index=True, use_container_width=True)

        with tab3:
            ec = df_f.groupby("Empresa").size().reset_index(name="Vacantes").sort_values("Vacantes", ascending=False).head(20)
            if not ec.empty:
                fig = px.bar(ec, x="Vacantes", y="Empresa", orientation="h", color="Vacantes", color_continuous_scale="Teal")
                fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)

        with tab4:
            pc = df_f.groupby("Portal").size().reset_index(name="Vacantes").sort_values("Vacantes", ascending=False)
            if not pc.empty:
                st.plotly_chart(px.pie(pc, names="Portal", values="Vacantes", title="Distribucion por Portal"), use_container_width=True)
                st.dataframe(pc, hide_index=True, use_container_width=True)

        with tab5:
            df_t = df_f.dropna(subset=["Fecha"]).copy()
            if not df_t.empty:
                df_t["Mes"] = pd.to_datetime(df_t["Fecha"]).dt.to_period("M").astype(str)
                tc = df_t.groupby("Mes").size().reset_index(name="Vacantes")
                fig = px.line(tc, x="Mes", y="Vacantes", markers=True)
                fig.update_traces(line_color="#1F4E79")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sin fechas disponibles.")

        with tab6:
            df_s = df_f.dropna(subset=["Salario Min"]).copy()
            if not df_s.empty:
                c1, c2 = st.columns(2)
                c1.metric("Promedio minimo", f"S/ {df_s['Salario Min'].mean():,.0f}")
                c1.metric("Mediana minimo",  f"S/ {df_s['Salario Min'].median():,.0f}")
                c2.metric("Con salario publicado", len(df_s))
                st.plotly_chart(px.histogram(df_s, x="Salario Min", nbins=20, color_discrete_sequence=["#2E75B6"]), use_container_width=True)
            else:
                st.info("Sin datos de salario.")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if page == "nuevo_estudio":
    page_nuevo_estudio()
elif page == "mis_estudios":
    _render_pending_auto_downloads()
    page_mis_estudios()
elif page == "resultados":
    page_resultados()
elif page == "mis_plantillas":
    page_mis_plantillas()
elif page == "portales":
    page_portales()


