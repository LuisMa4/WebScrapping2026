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
from integrations import google_drive
import study_runner

logger = logging.getLogger("sivml.weekly_run")
# OAuth client (Desktop app), NO cuenta de servicio -- las cuentas de
# servicio no pueden subir archivos a una carpeta de Drive personal
# (confirmado en vivo: sin cuota de almacenamiento propia). El token
# generado tras la primera autorizacion se guarda junto a este archivo
# como google_oauth_token.json (ver integrations/google_drive.py).
CREDENTIALS_PATH = ROOT / "credentials" / "google_oauth_client.json"


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
            "ran": bool,   # False si la automatizacion esta desactivada
            "results": [(template_name, study_id|None, excel_path|None, error|None), ...],
            "upload": UploadResult | None,
            "message": str,
        }
    """
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
                    excel_path = study_runner.execute_study(cfg, study.id, dry_run=False)
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
    summary = run_weekly_automation()
    logger.info(summary["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
