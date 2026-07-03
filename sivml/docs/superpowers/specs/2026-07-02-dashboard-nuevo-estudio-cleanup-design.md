# Dashboard "Nuevo Estudio" — Limpieza y Plantillas Rápidas — Spec de Diseño
**Fecha:** 2026-07-02
**Estado:** Aprobado

## Contexto

La pantalla "Nuevo Estudio" del dashboard (`dashboard/app.py`, función `page_nuevo_estudio()`) tiene tres problemas de usabilidad detectados por el usuario:

1. Muestra advertencias amarillas sobre Indeed/LinkedIn que ya no son ciertas — ambos portales fueron validados hoy (2026-07-02) funcionando correctamente en combinación con otros portales y con varios keywords simultáneos, gracias al mecanismo `fresh_context_per_keyword` ya implementado.
2. Cargar una plantilla guardada requiere abrir un expander, elegir de un dropdown y presionar un botón — más pasos de los necesarios.
3. El formulario mezcla campos esenciales (nombre, keywords, portales, fechas) con configuración técnica avanzada (páginas máx, delays, headless, dry run), lo que lo hace ver más denso de lo necesario.

## Cambio 1 — Quitar advertencias obsoletas

En `page_nuevo_estudio()`, eliminar estas dos líneas (dentro del bloque `if portals:`):

```python
if "indeed" in portals and len(portals) > 1:
    st.warning("Indeed detecta bots si se combina con otros portales. Usalo solo con 1 keyword.")
if "linkedin" in portals and len(portals) > 1:
    st.warning("LinkedIn tiene anti-bot agresivo. Recomendado usarlo solo.")
```

No se toca el bloque de badges `[OPERACIONAL]`/`[PARCIAL]` con notitas grises por portal (`st.markdown` + `st.caption`) — el usuario confirmó que ese se queda.

## Cambio 2 — Tarjetas de plantillas rápidas

Reemplaza el bloque actual `with st.expander("Cargar plantilla guardada", ...)` (líneas ~171–194) por una fila de tarjetas visibles de inmediato, una por plantilla guardada, **sin necesitar abrir nada**.

### Comportamiento

- Si `list_templates(session)` devuelve plantillas **no descartadas en esta sesión**, se muestra una fila de tarjetas (`st.columns`, máx 4 por fila) arriba del formulario principal.
- Si no hay plantillas, o todas fueron descartadas, la sección completa no se renderiza (sin mensajes vacíos tipo "no tienes plantillas").
- Cada tarjeta muestra:
  - Nombre de la plantilla (truncado si es muy largo)
  - Resumen corto: `"{N} keyword(s) · {ciudad1}{, +N}"` (ej. `"3 keywords · Lima"`)
  - Botón **"Cargar"** — mismo efecto que hoy: setea `st.session_state["form_defaults"]` con los campos de la plantilla y hace `st.rerun()`.
  - Botón **"✕"** pequeño (o `st.button` con label `"✕"`, `type="secondary"`) — agrega el `id` de la plantilla a `st.session_state["dismissed_template_ids"]` (un `set`, inicializado vacío) y hace `st.rerun()`. No borra la plantilla de la base de datos.

### Persistencia del descarte

Solo dura la sesión del navegador (`st.session_state`). Si el usuario cierra y vuelve a abrir el dashboard (nueva sesión de Streamlit), todas las plantillas vuelven a aparecer. No requiere cambios en la base de datos ni en `database/models.py` / `repository.py`.

### Qué se elimina

El expander "Cargar plantilla guardada" completo (dropdown `st.selectbox` + botón "Cargar configuracion" + mensaje "Plantilla cargada") se elimina — las tarjetas lo reemplazan funcionalmente uno a uno (cargar sigue haciendo lo mismo, solo con un click en vez de dos).

## Cambio 3 — Opciones avanzadas colapsadas

La sección actual (dentro del `st.form`):

```python
st.divider()
st.subheader("Configuracion del scraper")
c3, c4, c5 = st.columns(3)
... max_pages, delay_min, delay_max ...
c6, c7 = st.columns(2)
... headless, dry_run ...
```

se envuelve en:

```python
with st.expander("Opciones avanzadas", expanded=False):
    ...
```

Sin cambios en los valores por defecto, validaciones, ni en cómo se leen esas variables después del submit — solo cambia el contenedor visual. Un `st.expander` dentro de un `st.form()` es seguro aquí porque ninguno de esos widgets revela condicionalmente otro widget (la limitación conocida de Streamlit, ver memoria del proyecto, solo aplica a ese patrón específico).

## Casos borde

- **Plantilla cargada y luego descartada en la misma sesión**: son acciones independientes — cargar no descarta, descartar no afecta si ya se cargó una configuración en el formulario.
- **Usuario descarta todas las plantillas y luego crea una nueva plantilla en este submit**: la nueva plantilla aparecerá como tarjeta (no está en `dismissed_template_ids`), las anteriores siguen ocultas.
- **`dismissed_template_ids` referencia una plantilla ya eliminada** (por la pestaña "Eliminar" en "Mis Plantillas"): sin problema, simplemente no aparece en la lista de `list_templates()` de todas formas.

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `dashboard/app.py` | Los 3 cambios de arriba, todos dentro de `page_nuevo_estudio()` |

## Fuera de scope

- Persistir el descarte de plantillas entre sesiones (requeriría un campo nuevo en `study_templates` o similar — explícitamente no pedido).
- Rediseño de la pestaña "Mis Plantillas" (tabs Ejecutar/Editar/Eliminar) — no mencionado por el usuario.
- Cambios de paleta de colores / tipografía / CSS custom de Streamlit.
