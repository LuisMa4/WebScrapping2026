"""
Corrida semanal automatica de las 4 plantillas fijas + subida a Google
Drive. Disparado por la Tarea Programada de Windows los lunes (ver
scripts/install_weekly_task.py) -- tambien invocable a mano desde el boton
"Probar ahora" del dashboard (dashboard/app.py::page_mis_plantillas), o
desde linea de comandos: `python weekly_run.py`.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent

# La Tarea Programada de Windows arranca python.exe con cwd=%SystemRoot%\System32
# salvo que se configure lo contrario -- sqlite:///sivml.db (database/session.py)
# es una ruta RELATIVA que necesita cwd=sivml/. Debe ejecutarse ANTES de
# importar nada que toque database.session (crea el engine al importarse).
# Es un no-op cuando ya se corre desde sivml/ (dashboard, pytest, CLI).
if Path.cwd() != ROOT:
    os.chdir(ROOT)

from config.settings import ScraperConfig, StudyConfig
from database import repository as repo
from database.session import SessionLocal, init_db
from exports.excel_exporter import export_study_to_excel
from integrations import google_drive
from processing.deduplicator import run_exact_dedup
import study_runner

logger = logging.getLogger("sivml.weekly_run")

# Limite duro por plantilla: si una busqueda (sobre todo LinkedIn, con
# contexto fresco por keyword) se alarga, no debe arrastrar toda la corrida
# por horas -- a los 15 min se pide detener (mismo mecanismo que el boton
# "Detener" del dashboard: stop_requested, revisado entre cada
# keyword/ciudad -- el corte real puede caer uno o dos minutos despues de
# los 15, nunca horas). Si execute_study() no alcanzo a exportar el Excel
# por haberse detenido a mitad de camino, se exporta a mano con lo que ya
# se encontro hasta ese punto -- confirmado en vivo (backfill 2026-10-03,
# 8/8 plantillas cortadas limpio con Excel parcial).
PER_TEMPLATE_TIMEOUT_SECONDS = 15 * 60


def _request_stop_after_timeout(study_id: str) -> None:
    s = SessionLocal()
    try:
        repo.request_stop(s, study_id)
        logger.info(f"Limite de {PER_TEMPLATE_TIMEOUT_SECONDS}s alcanzado -- solicitando detener estudio {study_id}")
    finally:
        s.close()
# OAuth client (Desktop app), NO cuenta de servicio -- las cuentas de
# servicio no pueden subir archivos a una carpeta de Drive personal
# (confirmado en vivo: sin cuota de almacenamiento propia). El token
# generado tras la primera autorizacion se guarda junto a este archivo
# como google_oauth_token.json (ver integrations/google_drive.py).
CREDENTIALS_PATH = ROOT / "credentials" / "google_oauth_client.json"

# Evita corridas duplicadas superpuestas: el disparador de respaldo dispara
# cada 6 horas (scripts/install_weekly_task.py), pero una corrida real puede
# tardar horas (visto en vivo: 1-3+ horas) -- _needs_catchup_run() solo se
# vuelve False cuando la corrida TERMINA, asi que sin este lock, un disparo
# del respaldo mientras la primera corrida sigue en curso lanzaria OTRA
# corrida completa en paralelo (mismo riesgo si "Probar ahora" se usa
# mientras la Tarea Programada ya esta corriendo).
#
# El lock guarda el PID del proceso que lo tomo. Para decidir si un lock
# esta "vivo" o "abandonado" se revisa si ese PID sigue corriendo de
# verdad (psutil.pid_exists) -- NO un limite de tiempo fijo: una corrida
# real y lenta (6+ horas, ej. muchas ciudades/keywords en LinkedIn) no
# deberia confundirse con un proceso muerto solo por tardar. Si el PID ya
# no existe (el proceso murio sin limpiar -- crash, lo mataron, apagon),
# el lock se trata como abandonado y se toma de todos modos -- mismo
# principio que el "estudio colgado" de gotcha #13 del proyecto.
_LOCK_PATH = ROOT / ".weekly_run.lock"


def _acquire_lock() -> bool:
    if _LOCK_PATH.exists():
        try:
            held_by_pid = int(_LOCK_PATH.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            held_by_pid = None
        if held_by_pid is not None:
            import psutil
            if psutil.pid_exists(held_by_pid):
                return False
    _LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        _LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def _needs_catchup_run(settings) -> bool:
    """
    True si la automatizacion no ha corrido todavia esta semana (semana =
    desde el lunes mas reciente, inclusive). Usado por main() para que el
    disparador de respaldo (scripts/install_weekly_task.py, tarea
    SIVML_CorridaSemanal_Catchup) se ponga al dia sin duplicar trabajo si
    dispara varias veces en la misma semana, y sin interferir con la Tarea
    Programada principal de los lunes 7am (si esa ya corrio, el disparador
    de respaldo no hace nada esa semana).

    No se usa dentro de run_weekly_automation() a proposito: el boton
    "Probar ahora" del dashboard llama run_weekly_automation() directamente
    y SIEMPRE debe poder forzar una corrida, sin importar si ya corrio esta
    semana.

    La tarea de respaldo dispara cada 6 horas (no "al iniciar sesion" ni
    "al arrancar la PC": esos tipos de disparador tambien exigen permisos
    de admin para crearlos, confirmado en vivo con ambos; tampoco se apaga
    tras correr -- necesitaria algo igual de confiable para prenderla de
    nuevo el lunes, y no existe sin admin, ver install_weekly_task.py) --
    este chequeo es lo que evita que se repita el trabajo cada 6h una vez
    que ya corrio esa semana; en el caso comun (ya corrio) la tarea abre
    la BD, revisa una fecha y sale, practicamente gratis.
    """
    if settings.last_run_at is None:
        return True
    today = date.today()
    most_recent_monday = today - timedelta(days=today.weekday())
    return settings.last_run_at.date() < most_recent_monday


def _build_cfg_from_template(tpl, date_from: date, date_to: date) -> StudyConfig:
    return StudyConfig(
        study_name=f"{tpl.name} ({date_from} / {date_to})",
        academic_program=tpl.academic_program,
        keywords=tpl.keywords,
        cities=tpl.cities,
        portals=tpl.portals,
        date_from=date_from,
        date_to=date_to,
        scraper=ScraperConfig(
            delay_range=(tpl.delay_min, tpl.delay_max),
            max_pages=tpl.max_pages,
            headless=tpl.headless,
        ),
    )


def run_weekly_automation() -> dict:
    """
    Ejecuta las plantillas configuradas en AutomationSettings (secuencial,
    una por una) y sube los Excel resultantes a Drive. Devuelve un resumen
    usado tanto por main() (log) como por el boton "Probar ahora" del
    dashboard (muestra el resultado al usuario):

        {
            "ran": bool,   # False si la automatizacion esta desactivada o ya hay otra corrida en progreso
            "results": [(template_name, study_id|None, excel_path|None, error|None), ...],
            "upload": UploadResult | None,
            "message": str,
        }

    Protegido con un lock de archivo (ver _acquire_lock) para que no se
    superpongan dos corridas si el disparador de respaldo (cada 6h)
    dispara mientras una corrida anterior todavia esta en progreso, o si
    "Probar ahora" se usa mientras la Tarea Programada ya esta corriendo.
    """
    if not _acquire_lock():
        logger.info("Ya hay una corrida en progreso (lock activo), no se hace nada.")
        return {
            "ran": False, "results": [], "upload": None,
            "message": "Ya hay una corrida en progreso (lock activo).",
        }
    try:
        return _run_weekly_automation_locked()
    finally:
        _release_lock()


def _run_weekly_automation_locked() -> dict:
    init_db()
    session = SessionLocal()
    try:
        settings = repo.get_automation_settings(session)
        if not settings.enabled:
            logger.info("Automatizacion desactivada, no se hace nada.")
            return {"ran": False, "results": [], "upload": None, "message": "Automatizacion desactivada."}

        try:
            today = date.today()
            date_from, date_to = today - timedelta(days=7), today
            template_ids = json.loads(settings.template_ids_json)

            results: list[tuple[str, str | None, Path | None, str | None]] = []
            for tid in template_ids:
                tpl = None
                try:
                    tpl = repo.get_template(session, tid)
                    if tpl is None:
                        results.append((f"[plantilla id {tid} no encontrada]", None, None, "plantilla eliminada"))
                        continue
                    cfg = _build_cfg_from_template(tpl, date_from, date_to)
                    study = repo.create_study(session, cfg, status="running", dry_run=False)
                    repo.mark_template_used(session, tpl.id)

                    timer = threading.Timer(PER_TEMPLATE_TIMEOUT_SECONDS, _request_stop_after_timeout, args=(study.id,))
                    timer.daemon = True
                    timer.start()
                    try:
                        excel_path = study_runner.execute_study(cfg, study.id, dry_run=False)
                    finally:
                        timer.cancel()

                    # execute_study() se salta el export si el estudio se
                    # detuvo a mitad de camino (status "stopped", no
                    # "completed") -- aqui SI queremos el Excel con lo que
                    # se alcanzo a encontrar antes del limite de tiempo.
                    if excel_path is None:
                        raw_total = len(repo.get_raw_jobs_for_study(session, study.id))
                        if raw_total > 0:
                            stats = run_exact_dedup(session, study.id)
                            if stats["jobs_created"] > 0:
                                excel_path = export_study_to_excel(session, study.id, output_dir=study_runner.OUTPUT_DIR)
                                logger.info(f"{tpl.name}: export manual tras corte por tiempo -> {excel_path}")

                    results.append((tpl.name, study.id, excel_path, None))
                except Exception as exc:
                    session.rollback()
                    tpl_name = tpl.name if tpl is not None else f"[plantilla id {tid}]"
                    logger.exception(f"Error corriendo plantilla {tpl_name}")
                    results.append((tpl_name, None, None, str(exc)))

            excel_paths = [r[2] for r in results if r[2] is not None]
            upload_result = None
            if not excel_paths:
                upload_note = "Sin Excel generados, no se subio nada a Drive."
            elif not settings.drive_folder_id:
                upload_note = "Sin carpeta de Drive configurada, no se subio nada."
            elif not CREDENTIALS_PATH.exists():
                upload_note = (
                    f"Archivo de credenciales OAuth no encontrado en {CREDENTIALS_PATH} "
                    "-- crea un 'OAuth client ID' (Desktop app) en Google Cloud Console "
                    "y guardalo ahi."
                )
            else:
                try:
                    upload_result = google_drive.upload_files_to_dated_folder(
                        credentials_path=str(CREDENTIALS_PATH),
                        parent_folder_id=settings.drive_folder_id,
                        date_str=today.isoformat(),
                        file_paths=excel_paths,
                    )
                    upload_note = f"Subidos {len(upload_result.uploaded)}/{len(excel_paths)} archivos a Drive."
                    if upload_result.failed:
                        upload_note += f" {len(upload_result.failed)} fallaron."
                except Exception as exc:
                    logger.exception("Error subiendo a Drive")
                    upload_note = f"Error subiendo a Drive: {exc}"

            n_ok = sum(1 for r in results if r[3] is None)
            upload_ok = (not excel_paths) or (upload_result is not None and not upload_result.failed)
            if n_ok == 0:
                status = "failed"
            elif n_ok == len(results) and upload_ok:
                status = "success"
            else:
                status = "partial"

            message = f"{n_ok}/{len(results)} plantillas OK. {upload_note}"
            repo.record_automation_run(session, status=status, message=message)

            return {"ran": True, "results": results, "upload": upload_result, "message": message}
        except Exception as outer_exc:
            logger.exception("Fallo inesperado en run_weekly_automation")
            repo.record_automation_run(session, status="failed", message=f"Error inesperado: {outer_exc}")
            raise
    finally:
        session.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / "sivml_weekly_run.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    init_db()
    session = SessionLocal()
    try:
        settings = repo.get_automation_settings(session)
        if not _needs_catchup_run(settings):
            logger.info("Ya corrio esta semana, no se hace nada (disparador de las 7am o de respaldo repetido).")
            return 0
    finally:
        session.close()

    summary = run_weekly_automation()
    logger.info(summary["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
