# Dashboard "Nuevo Estudio" Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up `page_nuevo_estudio()` in the SIVML dashboard — remove stale portal warnings, replace the template-loading expander with dismissable quick-access cards, and collapse advanced scraper config into a closed-by-default expander.

**Architecture:** All changes live in `dashboard/app.py`'s `page_nuevo_estudio()` function. One small new pure-logic module (`dashboard/template_cards.py`, no Streamlit dependency) holds the testable summary-string formatting; the Streamlit rendering and session-state dismiss-tracking stay inline in `app.py` since they're inherently coupled to a live Streamlit session and aren't independently testable with pytest.

**Tech Stack:** Python 3.14, Streamlit, SQLAlchemy (`database.repository.list_templates`), pytest, Playwright (for live end-to-end verification — this codebase has no pytest coverage of `dashboard/app.py` itself; UI behavior is verified by driving the actual running app, per established project convention).

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-02-dashboard-nuevo-estudio-cleanup-design.md` — follow it exactly for behavior.
- Dismissed template IDs are session-only (`st.session_state`), never written to the database.
- No changes to `database/models.py`, `database/repository.py`, or the "Mis Plantillas" page.
- No changes to portal status badges (`[OPERACIONAL]`/`[PARCIAL]` + captions) — only the two `st.warning()` calls are removed.

---

### Task 1: Remove obsolete portal warnings

**Files:**
- Modify: `dashboard/app.py` (inside `page_nuevo_estudio()`, currently around line 264-268)

**Interfaces:**
- Consumes: nothing new
- Produces: nothing new (pure deletion)

- [ ] **Step 1: Locate and remove the two stale warnings**

Find this block inside `page_nuevo_estudio()`:

```python
        if portals:
            if "indeed" in portals and len(portals) > 1:
                st.warning("Indeed detecta bots si se combina con otros portales. Usalo solo con 1 keyword.")
            if "linkedin" in portals and len(portals) > 1:
                st.warning("LinkedIn tiene anti-bot agresivo. Recomendado usarlo solo.")
```

Delete it entirely (all 5 lines, including the `if portals:` wrapper — it has no other purpose).

- [ ] **Step 2: Verify the portal status badges block above it is untouched**

Confirm this block (a few lines above the one you just deleted) is still present and unmodified:

```python
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
```

- [ ] **Step 3: Syntax check**

Run: `python -c "import ast; ast.parse(open('dashboard/app.py', encoding='utf-8').read())"`
Expected: no output, exit code 0 (valid syntax).

- [ ] **Step 4: Commit**

No git repo in this project (confirmed: `Is a git repository: false`) — skip commit steps for all tasks in this plan. Just move to the next task.

---

### Task 2: Extract and test the template summary helper

**Files:**
- Create: `dashboard/template_cards.py`
- Create: `tests/test_template_cards.py`

**Interfaces:**
- Produces: `template_summary(keywords: list[str], cities: list[str]) -> str` — used by Task 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_template_cards.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sivml && python -m pytest tests/test_template_cards.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.template_cards'`

- [ ] **Step 3: Write minimal implementation**

Create `dashboard/template_cards.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sivml && python -m pytest tests/test_template_cards.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all tests pass (122 previously + 5 new = 127 passed)

---

### Task 3: Replace the template-loading expander with dismissable cards

**Files:**
- Modify: `dashboard/app.py` (inside `page_nuevo_estudio()`, currently lines ~163-197)

**Interfaces:**
- Consumes: `template_summary(keywords, cities) -> str` from Task 2 (`dashboard/template_cards.py`)
- Consumes: `repo.list_templates(session) -> list[StudyTemplate]` (existing, `database/repository.py`) — each `StudyTemplate` has `.id`, `.name`, `.academic_program`, `.keywords` (list[str]), `.cities` (list[str]), `.portals` (list[str]), `.max_pages`, `.delay_min`, `.delay_max`, `.headless` (all existing properties, see `database/models.py`)
- Produces: sets `st.session_state["form_defaults"]` and calls `st.rerun()` on "Cargar" click (same contract the rest of `page_nuevo_estudio()` already reads from, e.g. `defaults = st.session_state.get("form_defaults", {})` a few lines below)
- Produces: maintains `st.session_state["dismissed_template_ids"]` as a `set[int]`

- [ ] **Step 1: Add the import**

At the top of `dashboard/app.py`, near the other imports (after `from scrapers.portal_info import ACTIVE_PORTALS, INACTIVE_PORTALS` around line 85), add:

```python
from dashboard.template_cards import template_summary
```

- [ ] **Step 2: Locate the block to replace**

Find this in `page_nuevo_estudio()` (currently lines ~163-197):

```python
    # ── Cargador de plantilla (fuera del form para poder reaccionar al select) ─
    session_pre = _session()
    templates = repo.list_templates(session_pre)
    session_pre.close()

    # Valores iniciales (se sobreescriben si se carga una plantilla)
    defaults = st.session_state.get("form_defaults", {})

    if templates:
        with st.expander("Cargar plantilla guardada", expanded=False):
            tpl_options = {"-- Selecciona una plantilla --": None}
            for t in templates:
                label = f"{t.name} | {t.academic_program} | {', '.join(t.portals[:2])}{'...' if len(t.portals) > 2 else ''}"
                tpl_options[label] = t

            selected_label = st.selectbox("Plantilla", list(tpl_options.keys()), label_visibility="collapsed")
            selected_tpl = tpl_options[selected_label]

            if selected_tpl and st.button("Cargar configuracion", type="secondary"):
                st.session_state["form_defaults"] = {
                    "study_name":       selected_tpl.name,
                    "academic_program": selected_tpl.academic_program,
                    "keywords_raw":     "\n".join(selected_tpl.keywords),
                    "cities":           selected_tpl.cities,
                    "portals":          selected_tpl.portals,
                    "max_pages":        selected_tpl.max_pages,
                    "delay_min":        selected_tpl.delay_min,
                    "delay_max":        selected_tpl.delay_max,
                    "headless":         selected_tpl.headless,
                    "tpl_id":           selected_tpl.id,
                }
                st.rerun()

            if defaults.get("tpl_id"):
                st.success(f"Plantilla cargada: **{defaults['study_name']}** — edita los campos si necesitas y lanza.")
```

- [ ] **Step 3: Replace it with the card-row implementation**

```python
    # ── Tarjetas de plantillas guardadas (visibles de inmediato, sin expander) ─
    session_pre = _session()
    templates = repo.list_templates(session_pre)
    session_pre.close()

    # Valores iniciales (se sobreescriben si se carga una plantilla)
    defaults = st.session_state.get("form_defaults", {})

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
```

- [ ] **Step 4: Syntax check**

Run: `python -c "import ast; ast.parse(open('dashboard/app.py', encoding='utf-8').read())"`
Expected: no output, exit code 0.

- [ ] **Step 5: Full pytest suite still passes**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass (same count as end of Task 2 — this task only touches `app.py`, no test changes).

---

### Task 4: Collapse advanced scraper options into an expander

**Files:**
- Modify: `dashboard/app.py` (inside `page_nuevo_estudio()`'s `st.form("form_estudio")` block, currently lines ~270-294)

**Interfaces:**
- Consumes: nothing new
- Produces: `max_pages`, `delay_min`, `delay_max`, `headless`, `dry_run` variables — same names, same downstream usage in the rest of the function (the code after `submitted = st.form_submit_button(...)` reads these by the same names, unchanged)

- [ ] **Step 1: Locate the block to wrap**

Find this inside the `with st.form("form_estudio"):` block:

```python
        st.divider()
        st.subheader("Configuracion del scraper")
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
```

- [ ] **Step 2: Wrap it in a closed-by-default expander**

Replace with:

```python
        st.divider()
        with st.expander("Opciones avanzadas", expanded=False):
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
```

(Only change: `st.subheader("Configuracion del scraper")` removed — the expander label replaces it — and everything indented one level into `with st.expander(...)`.)

- [ ] **Step 3: Syntax check**

Run: `python -c "import ast; ast.parse(open('dashboard/app.py', encoding='utf-8').read())"`
Expected: no output, exit code 0.

- [ ] **Step 4: Full pytest suite still passes**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass, same count as Task 3.

---

### Task 5: Live end-to-end verification against the running dashboard

**Files:**
- Create (scratch, not part of repo): a temporary Playwright script in the scratchpad directory to drive the live app.

**Interfaces:**
- Consumes: the running Streamlit app started via `python -m streamlit run dashboard/app.py --server.headless true --server.port <port>`

This project has no pytest coverage of Streamlit rendering — verify by driving the actual app, per established project convention (see project memory: prefer real-browser Playwright checks over trusting unit tests for dashboard behavior).

- [ ] **Step 1: Start the dashboard**

Run (from `sivml/`): `python -m streamlit run dashboard/app.py --server.headless true --server.port 8520` in the background, then poll `http://localhost:8520` until it returns HTTP 200.

- [ ] **Step 2: Seed one template directly via the repository (fast, no UI needed for setup)**

```python
import sys; sys.path.insert(0, ".")
from database.session import SessionLocal
from database import repository as repo
s = SessionLocal()
repo.create_template(s, {
    "name": "Verificacion E2E", "academic_program": "Test",
    "keywords": ["analista de datos", "contador"], "cities": ["Lima", "Arequipa"],
    "portals": ["computrabajo", "bumeran"], "max_pages": 10,
    "delay_min": 2.0, "delay_max": 5.0, "headless": True,
})
s.commit()
s.close()
```

- [ ] **Step 3: Drive the dashboard with Playwright and assert on each change**

Write and run a script that:
1. Navigates to `http://localhost:8520`, clicks "Nuevo Estudio" in the sidebar (scoped to `section[data-testid='stSidebar']` to avoid text-match ambiguity elsewhere on the page).
2. Asserts `page.get_by_text("Indeed detecta bots", exact=False).count() == 0` and same for `"LinkedIn tiene anti-bot"` — confirms Task 1.
3. Asserts a card with text "Verificacion E2E" is visible, and `page.get_by_text("2 keywords · Lima, +1 más", exact=False).count() > 0` — confirms Task 2/3's summary formatting renders correctly.
4. Clicks the card's "Cargar" button, waits, asserts the "Nombre del estudio" field now has value `"Verificacion E2E"` (via `.input_value()`) — confirms load-on-click still works.
5. Reloads the page fresh (`page.goto` again) or opens the card row again, clicks the "✕" dismiss button for a template, waits, asserts the card is no longer visible on this page render — confirms Task 3's dismiss behavior.
6. Asserts `page.get_by_text("Opciones avanzadas", exact=False).count() > 0` and that `page.get_by_text("Max paginas/busqueda", exact=False).first.is_visible() == False` before expanding, then clicks the expander and confirms it becomes visible — confirms Task 4.
7. Checks `page.locator("[data-testid='stException']").count() == 0` throughout — no crashes.

- [ ] **Step 4: Clean up**

Delete the "Verificacion E2E" template via `repo.delete_template()` (direct repository call, same pattern as prior sessions). Stop the Streamlit process (`Stop-Process` on the PID bound to port 8520, or matching command line).

- [ ] **Step 5: Report results**

If all assertions pass: cleanup is done, dashboard is verified end-to-end. If anything fails: follow `superpowers:systematic-debugging` before making further changes — do not guess at a fix.
