# Automatización semanal: 4 plantillas fijas + subida a Google Drive

**Fecha:** 2026-08-10
**Estado:** Aprobado por el usuario, listo para plan de implementación.

## Contexto

El usuario tiene 4 plantillas de estudio ya configuradas y validadas (ver captura de
pantalla adjunta a la conversación original): "Derecho Administrativo", "Derecho
Constitucional", "Derecho Civil" e "Ingeniería Civil". Quiere que estas 4 corran
automáticamente cada lunes con un rango de fecha de una semana (últimos 7 días),
que los resultados (Excel) se suban a una carpeta de Google Drive específica dentro
de una subcarpeta nombrada con la fecha, y que exista un interruptor para
activar/desactivar este ciclo cuando quiera.

Antes de esto, la base de datos real tiene plantillas duplicadas/viejas y ~24
Estudios históricos que deben limpiarse para que solo queden las 4 plantillas de
la imagen.

## Identificación de las 4 plantillas (confirmado contra la BD real)

Hay pares duplicados en `study_templates` — la versión correcta de cada una es la
que NO incluye "Puno" en las ciudades (coincide exactamente con "Lima, +4 más" en
la captura de pantalla y con el conteo de keywords mostrado en cada tarjeta):

| id | Nombre | Ciudades | # Keywords (coincide con la imagen) |
|----|--------|----------|--------------------------------------|
| 8  | Ingeniería Civil | Lima, Tacna, Arequipa, Moquegua, Cusco | 5 |
| 9  | Derecho Civil | Lima, Tacna, Arequipa, Moquegua, Cusco | 4 |
| 10 | Derecho Constitucional | Lima, Tacna, Arequipa, Moquegua, Cusco | 3 |
| 11 | Derecho Administrativo | Lima, Tacna, Arequipa, Moquegua, Cusco | 3 |

Todo lo demás en `study_templates` (ids 1-7) y **todos** los `studies` existentes
(históricos) se eliminan como parte de este trabajo.

## Alcance de la limpieza de datos (decisión del usuario)

- Se borran las plantillas 1-7 (duplicados con "Puno" + plantillas de prueba).
- Se borran **todos** los Estudios/corridas históricos (incluyendo sus `raw_jobs`,
  `jobs`, `scraping_runs`) — no solo los de las plantillas eliminadas. El usuario
  quiere empezar limpio para el ciclo semanal.
- **Antes de borrar**: se hace una copia de `sivml.db` a
  `sivml.db.bak_pre_weekly_automation_YYYYMMDD` (mismo patrón que backups previos
  del proyecto, ver `sivml.db.bak_pre_schema_fix`), como red de seguridad ante un
  borrado irreversible de datos reales.
- Se implementa como un script explícito (`scripts/cleanup_for_automation.py`),
  no como parte del flujo automático — se corre una sola vez, a mano, mostrando
  antes un resumen de qué se va a borrar (conteos) y pidiendo confirmación por
  teclado antes de ejecutar.

## Arquitectura del disparador semanal

**Elegido:** Tarea Programada de Windows → ejecuta `weekly_run.py` (script
standalone en la raíz de `sivml/`, mismo patrón que `scraping.py`/`cli/commands.py`).
No depende de que el dashboard de Streamlit esté abierto — `study_runner.py` ya no
tiene ninguna dependencia de Streamlit (confirmado: "Sin llamadas a Streamlit
aqui" en su docstring), así que el script puede importar y usar
`study_runner.execute_study()` directamente.

**Descartado:** hacer que la Tarea Programada abra el dashboard con una bandera
especial — innecesariamente complejo, sin ninguna ventaja ya que el pipeline de
scraping no necesita el dashboard corriendo.

La Tarea Programada corre los lunes a las **7:00 AM** por default (antes del
horario típico de inicio de jornada) — `scripts/install_weekly_task.py` acepta
un argumento opcional `--hora HH:MM` por si el usuario prefiere otra hora al
instalarla; sin el argumento usa el default.

Se registra con `schtasks` (Windows nativo, sin dependencias nuevas) apuntando a:
```
python.exe C:\...\sivml\weekly_run.py
```
con "Iniciar en" = la carpeta `sivml/` (igual que hace `launcher/sivml_launcher.py`
con `cwd=base_dir`, necesario para que `sqlite:///sivml.db` resuelva al archivo
correcto — ver gotcha conocido de rutas relativas en `database/session.py`).
Configurada para "Ejecutar tanto si el usuario inició sesión como si no" y
"Ejecutar con los privilegios más altos" NO marcado (no hace falta admin).

El registro de la tarea se hace con un script (`scripts/install_weekly_task.py`)
que el usuario corre una sola vez desde una consola (o un botón en el dashboard
que muestra el comando exacto antes de ejecutarlo — ver sección Dashboard). Esto
es un cambio a nivel de sistema operativo, así que nunca se ejecuta en silencio.

## Componentes nuevos

### 1. `database/models.py` — tabla `AutomationSettings`

Fila única (singleton, `id=1`) con:
- `enabled: bool` (default `False` hasta que el usuario lo active desde el dashboard)
- `drive_folder_id: str | None` — el ID de carpeta extraído de la URL de Drive
  (`1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1` para
  `https://drive.google.com/drive/folders/1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1`)
- `template_ids_json: str` — los 4 ids fijos (`[8, 9, 10, 11]`), guardados como
  dato (no hardcodeados en el script) para que si el usuario cambia qué plantillas
  quiere automatizar, no haga falta tocar código
- `last_run_at: datetime | None`
- `last_run_status: str | None` (`success` / `partial` / `failed`)
- `last_run_message: str | None` — resumen legible ("4/4 plantillas OK, subido a
  Drive" o el error si algo falló)

Migración ligera igual que `stop_requested` en `_run_lightweight_migrations()`
(`database/session.py`) — crea la tabla si no existe, no rompe una BD ya
poblada.

### 2. `database/repository.py` — funciones nuevas

- `get_automation_settings(session) -> AutomationSettings` (crea la fila si no
  existe, con defaults)
- `set_automation_enabled(session, enabled: bool) -> None`
- `record_automation_run(session, status: str, message: str) -> None`

### 3. `integrations/google_drive.py` (paquete nuevo)

Capa delgada sobre `google-api-python-client` + `google-auth`:

```python
def get_drive_service(credentials_path: str):
    """Construye el cliente de la API a partir del JSON de la cuenta de servicio."""

def create_dated_folder(service, parent_folder_id: str, date_str: str) -> str:
    """Crea (o reutiliza si ya existe, por si el script corre dos veces el mismo
    dia) una subcarpeta `date_str` dentro de parent_folder_id. Devuelve su ID."""

def upload_file(service, folder_id: str, file_path: Path) -> str:
    """Sube un archivo a la carpeta dada. Devuelve el ID del archivo subido."""

def upload_files_to_dated_folder(
    credentials_path: str, parent_folder_id: str, date_str: str, file_paths: list[Path]
) -> dict:
    """Orquesta todo: conecta, crea/reutiliza la carpeta fechada, sube cada
    archivo. Devuelve {"folder_id": ..., "folder_url": ..., "uploaded": [...],
    "failed": [(path, error), ...]}. Nunca lanza excepcion por un archivo
    individual que falle -- sigue con los demas y reporta al final, para que un
    solo Excel corrupto no tumbe la subida de los otros 3."""
```

Diseñado para poder testear sin credenciales reales: `get_drive_service` es la
única función que toca la red/autenticación de verdad; `create_dated_folder`,
`upload_file` y `upload_files_to_dated_folder` reciben `service` como parámetro
inyectado, así que los tests le pasan un objeto falso (fake) que graba las
llamadas en vez de golpear la API de Google.

### 4. `weekly_run.py` (raíz de `sivml/`)

Punto de entrada de la Tarea Programada. Sin argumentos de línea de comandos
(todo sale de `AutomationSettings`).

```python
def main() -> int:
    session = SessionLocal()
    settings = repo.get_automation_settings(session)

    if not settings.enabled:
        logger.info("Automatizacion desactivada, no se hace nada.")
        return 0

    today = date.today()
    date_from, date_to = today - timedelta(days=7), today
    template_ids = json.loads(settings.template_ids_json)

    results = []  # (template_name, study_id | None, excel_path | None, error | None)
    for tid in template_ids:
        tpl = repo.get_template(session, tid)
        if tpl is None:
            results.append((f"[id {tid} no encontrado]", None, None, "plantilla eliminada"))
            continue
        try:
            cfg = _build_cfg_from_template(tpl, date_from, date_to)
            study = repo.create_study(session, cfg, status="running", dry_run=False)
            repo.mark_template_used(session, tpl.id)
            study_runner.execute_study(cfg, study.id, dry_run=False)
            excel_path = _find_excel_for_study(study.id)  # busca en output/
            results.append((tpl.name, study.id, excel_path, None))
        except Exception as exc:
            logger.exception(f"Error corriendo plantilla {tpl.name}")
            results.append((tpl.name, None, None, str(exc)))

    excel_paths = [r[2] for r in results if r[2] is not None]
    upload_result = None
    if excel_paths and settings.drive_folder_id:
        try:
            upload_result = google_drive.upload_files_to_dated_folder(
                credentials_path=CREDENTIALS_PATH,
                parent_folder_id=settings.drive_folder_id,
                date_str=today.isoformat(),
                file_paths=excel_paths,
            )
        except Exception as exc:
            logger.exception("Error subiendo a Drive")

    # construir mensaje resumen y llamar repo.record_automation_run(...)
    ...
    return 0
```

Cada plantilla corre en secuencia (no en paralelo) — decisión deliberada para
mantener acotado el uso de recursos (cada estudio ya paraleliza 4 portales
internamente vía `scraping.py`) y simplificar el aislamiento de errores: si una
plantilla falla, las otras 3 igual se ejecutan y se sube lo que sí se generó.

Un fallo de Drive (sin internet, credenciales inválidas/revocadas, carpeta ya no
compartida) **nunca** borra ni descarta los Excel locales — quedan en
`output/` exactamente como cualquier corrida manual de hoy. Un fallo tampoco
apaga `enabled` — solo el usuario lo apaga a mano desde el dashboard.

### 5. Dashboard — sección "Automatización semanal"

Nueva sección al principio de `page_mis_plantillas()` (antes de listar las
plantillas), en un `st.container(border=True)`:

- Interruptor `st.toggle("Automatización semanal activa", value=settings.enabled)`
  — al cambiar, llama `repo.set_automation_enabled()` inmediatamente (sin botón
  de confirmar aparte; encender/apagar un interruptor no es una acción
  destructiva).
- Texto de estado: "Próxima corrida: el próximo lunes" / última corrida (fecha,
  status, mensaje) leído de `AutomationSettings`.
- Botón **"Probar ahora"**: llama la misma lógica que `weekly_run.main()`
  (refactorizada para ser invocable como función, no solo como script CLI) en un
  hilo de fondo, mostrando un spinner y el resultado al terminar. Permite validar
  todo el flujo (incluida la subida real a Drive) sin esperar al lunes.
- Botón **"Instalar tarea programada de Windows"**: muestra el comando `schtasks`
  exacto que se va a ejecutar y pide confirmación explícita (checkbox, mismo
  patrón que los botones "Eliminar" existentes) antes de correrlo vía
  `subprocess`.

## Credenciales de Google (dependencia externa, la completa el usuario)

- El usuario crea una cuenta de servicio en Google Cloud Console, descarga el
  JSON, comparte la carpeta de Drive de destino con el email de esa cuenta como
  Editor (pasos detallados ya explicados en la conversación).
- El archivo `.json` se guarda en `sivml/credentials/google_service_account.json`
  — carpeta nueva, agregada a `.gitignore` (nunca debe llegar a un repositorio).
- Hasta que ese archivo exista, "Probar ahora" y la corrida real completan el
  scraping normalmente pero la subida a Drive falla con un mensaje claro
  ("Archivo de credenciales no encontrado en credentials/google_service_account.json
  — sigue el instructivo para crearlo") en vez de una traza de error críptica.

## Dependencias nuevas

`requirements.txt` gana `google-api-python-client`, `google-auth`.

## Testing

- `tests/test_automation_settings.py`: `get_automation_settings` crea el default
  si no existe, `set_automation_enabled` persiste, `record_automation_run`
  actualiza los 3 campos de estado.
- `tests/test_google_drive.py`: `create_dated_folder` (reutiliza si ya existe en
  vez de duplicar), `upload_file`, `upload_files_to_dated_folder` (aisla fallos
  por archivo) — todo contra un `service` falso, sin red.
- `tests/test_weekly_run.py`: `main()` con `enabled=False` no hace nada; con
  `enabled=True` corre las 4 plantillas (mockeando `study_runner.execute_study`
  para no scrapear de verdad) y llama la subida a Drive; una plantilla que falla
  no detiene a las demás; sin `drive_folder_id` configurado, no intenta subir.
- `tests/test_cleanup_script.py`: el script de limpieza, contra una BD de prueba
  con datos sintéticos que imitan el patrón real (duplicados + plantillas
  correctas + estudios históricos) — verifica que solo sobrevivan los ids
  correctos y que se haya hecho el backup del archivo antes de borrar.
- Prueba en vivo final: botón "Probar ahora" contra el dashboard real, una vez
  el usuario complete el setup de Google Cloud — confirma el flujo completo de
  punta a punta (scraping real de las 4 plantillas + Excel + subida real a
  Drive + carpeta fechada visible en la carpeta compartida).

## Fuera de alcance (explícitamente, para no inflar este trabajo)

- Notificaciones por email/Slack si la corrida falla — no existe integración de
  este tipo en el proyecto hoy; se puede agregar después si hace falta.
- Configurar CUÁLES plantillas se automatizan desde el dashboard (más allá de
  ON/OFF) — por ahora son las 4 fijas guardadas en `template_ids_json`; cambiar
  la lista requiere editar esa fila directamente. Se puede exponer en UI en una
  iteración futura si el usuario lo pide.
- Reintentos automáticos de subida a Drive si falla — un fallo se reporta, se
  resuelve manualmente esa semana, y la corrida siguiente (el próximo lunes)
  funciona normal si ya se arregló la causa.
