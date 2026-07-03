# Plantillas de Scraping — Spec de Diseño
**Fecha:** 2026-06-27  
**Estado:** Aprobado

## Contexto

SIVML permite configurar estudios de mercado laboral (keywords, portales, ciudades, programa académico). Actualmente cada estudio se configura desde cero. Se requiere guardar configuraciones reutilizables ("plantillas") para poder repetir el mismo scraping periódicamente actualizando solo las fechas.

---

## Modelo de datos

### Nueva tabla: `study_templates`

```python
class StudyTemplate(Base):
    __tablename__ = "study_templates"

    id:               Integer PK autoincrement
    name:             String(255) NOT NULL
    academic_program: String(255) NOT NULL
    keywords_json:    Text NOT NULL        # JSON array de strings
    cities_json:      Text NOT NULL        # JSON array de strings
    portals_json:     Text NOT NULL        # JSON array de strings
    max_pages:        Integer default 10
    delay_min:        Float default 2.0
    delay_max:        Float default 5.0
    headless:         Boolean default True
    notes:            Text nullable
    created_at:       DateTime NOT NULL
    last_run_at:      DateTime nullable
    run_count:        Integer default 0

    # Propiedades calculadas (deserializan JSON)
    keywords -> list[str]
    cities   -> list[str]
    portals  -> list[str]
```

- `init_db()` crea la tabla automáticamente al arrancar.
- No FK hacia `studies` — los estudios son independientes de las plantillas.
- Nombres duplicados permitidos (identificación por `id`).

---

## Repositorio (`database/repository.py`)

Funciones nuevas sin modificar las existentes:

```python
create_template(session, data: dict) -> StudyTemplate
list_templates(session) -> list[StudyTemplate]   # ordenadas por last_run_at desc
get_template(session, template_id: int) -> StudyTemplate | None
update_template(session, template_id: int, data: dict) -> StudyTemplate
delete_template(session, template_id: int) -> None
mark_template_used(session, template_id: int) -> None  # last_run_at = now, run_count += 1
```

---

## UI — Dashboard (`dashboard/app.py`)

### Sidebar: nueva entrada "Mis Plantillas" (5ª pestaña)

### Cambio 1: "Nuevo Estudio" — arriba del formulario

Expander colapsado **"Cargar plantilla guardada"**:
- Dropdown con plantillas (muestra: nombre + programa académico)
- Botón "Cargar" → pre-llena todos los campos del formulario
- Sin plantillas → mensaje "No tienes plantillas guardadas aún"

Checkbox al final del formulario: **"Guardar como plantilla"**  
- Si marcado: aparece campo de nombre de plantilla (obligatorio)
- Al enviar el formulario: además de lanzar el scraping, guarda la plantilla

### Cambio 2: Página "Mis Plantillas"

Lista de cards por plantilla con:
- Nombre + programa académico
- Tags de portales (primeros 3 + "y N más")
- Keywords (primeras 3 + "y N más")
- "Última ejecución: fecha" y "Usos: N"

**Botón "Ejecutar"** → panel expandible con:
- Presets de fecha: `Esta semana (7d)` · `Último mes (30d)` · `Últimos 3 meses (90d)` · `Personalizado`
- Selectores fecha inicio/fin (pre-llenados por preset, editables)
- Toggle dry run
- Botón "Lanzar scraping" → ejecuta `run_scraping()`, crea nuevo Study, llama `mark_template_used()`

**Botón "Editar"** → formulario inline pre-llenado con los campos de la plantilla, botón "Guardar cambios"

**Botón "Eliminar"** → confirmación, borra solo la plantilla (los estudios existentes no se tocan)

---

## Presets de fecha

| Preset | date_from | date_to |
|---|---|---|
| Esta semana | today − 7d | today |
| Último mes | today − 30d | today |
| Últimos 3 meses | today − 90d | today |
| Personalizado | editable | editable |

---

## Casos borde

- **Portal inactivo en plantilla**: `scraping.py` lo filtra con `[SKIP]`, no bloquea la ejecución.
- **Eliminar plantilla**: los estudios ya generados con ella persisten sin cambios.
- **Cargar plantilla en formulario**: sobrescribe los campos actuales del form; el usuario puede seguir editando.
- **Guardar plantilla y lanzar a la vez**: ambas operaciones ocurren en el mismo submit.

---

## Archivos a modificar / crear

| Archivo | Cambio |
|---|---|
| `database/models.py` | Agregar `StudyTemplate` |
| `database/repository.py` | Agregar 6 funciones `*_template` |
| `database/session.py` | `init_db()` ya llama `Base.metadata.create_all` — sin cambio |
| `dashboard/app.py` | Nueva página + cambios en Nuevo Estudio |
| `tests/test_repository.py` o nuevo `tests/test_templates.py` | Tests de las funciones de repositorio |

---

## Fuera de scope

- Exportar/importar plantillas como archivo
- Compartir plantillas entre usuarios
- Programar ejecuciones automáticas (cron)
- Historial de ejecuciones por plantilla (los estudios en "Mis Estudios" ya cumplen ese rol)
