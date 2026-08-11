"""
Limpieza unica de la base de datos antes de activar la automatizacion
semanal: deja solo las 4 plantillas ya validadas (Derecho Administrativo,
Derecho Constitucional, Derecho Civil, Ingenieria Civil -- ids 8, 9, 10, 11
en la BD real) y borra todo lo demas (plantillas viejas/duplicadas + TODOS
los Estudios historicos). Hace un backup de sivml.db antes de tocar nada.

Se corre a mano UNA SOLA VEZ: `python scripts/cleanup_for_automation.py`
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Study, StudyTemplate

KEEP_TEMPLATE_IDS = [8, 9, 10, 11]


def backup_db(root: Path) -> Path:
    db_path = root / "sivml.db"
    backup_path = root / f"sivml.db.bak_pre_weekly_automation_{date.today().isoformat()}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def summarize(session: Session) -> dict:
    all_templates = session.scalars(select(StudyTemplate)).all()
    all_studies = session.scalars(select(Study)).all()
    return {
        "templates_to_keep": [t for t in all_templates if t.id in KEEP_TEMPLATE_IDS],
        "templates_to_delete": [t for t in all_templates if t.id not in KEEP_TEMPLATE_IDS],
        "studies_to_delete": all_studies,
    }


def run_cleanup(session: Session, summary: dict) -> None:
    from database import repository as repo

    for study in summary["studies_to_delete"]:
        repo.delete_study(session, study.id)
    for tpl in summary["templates_to_delete"]:
        repo.delete_template(session, tpl.id)


def main() -> int:
    from database.session import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        summary = summarize(session)

        print(f"Plantillas a CONSERVAR ({len(summary['templates_to_keep'])}):")
        for t in summary["templates_to_keep"]:
            print(f"  - [{t.id}] {t.name}")

        print(f"\nPlantillas a BORRAR ({len(summary['templates_to_delete'])}):")
        for t in summary["templates_to_delete"]:
            print(f"  - [{t.id}] {t.name}")

        print(f"\nEstudios a BORRAR ({len(summary['studies_to_delete'])}): TODOS los historicos.")

        if not summary["templates_to_keep"]:
            print(
                f"\n[ERROR] Ninguna de las 4 plantillas esperadas (ids {KEEP_TEMPLATE_IDS}) "
                "existe en la base de datos -- abortando sin tocar nada, revisa los ids "
                "antes de reintentar."
            )
            return 1

        answer = input("\nEscribe BORRAR para confirmar (cualquier otra cosa cancela): ")
        if answer.strip() != "BORRAR":
            print("Cancelado, no se borro nada.")
            return 0

        backup_path = backup_db(ROOT)
        print(f"\nBackup creado en: {backup_path}")

        run_cleanup(session, summary)
        print("Listo. Solo quedan las 4 plantillas indicadas, sin estudios historicos.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
