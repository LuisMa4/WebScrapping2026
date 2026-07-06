"""
Orquestador de estudios concurrentes.

Antes, crear un estudio ejecutaba el scraping DENTRO del script de Streamlit
de esa sesion (bloqueaba la pantalla hasta terminar). Este modulo lo separa:
crear un estudio lanza un hilo en segundo plano (o lo deja 'queued' si ya
hay MAX_CONCURRENT_STUDIES corriendo) y devuelve el control de inmediato.
El propio hilo, al terminar, revisa la cola y promueve el siguiente -- no
hace falta un scheduler aparte.

Sin llamadas a Streamlit aqui: este modulo corre en hilos de fondo sin
contexto de sesion/UI. La UI (dashboard/app.py) solo lee el estado desde la
BD (Study.status, ScrapingRun) para dibujar el progreso.
"""
from __future__ import annotations

import threading
from pathlib import Path

from config.settings import StudyConfig
from database import repository as repo
from database.session import SessionLocal
from processing.deduplicator import run_exact_dedup
from exports.excel_exporter import export_study_to_excel
from scraping import run_scraping

MAX_CONCURRENT_STUDIES = 5
OUTPUT_DIR = Path(__file__).parent / "output"


def can_start_immediately(session) -> bool:
    return repo.count_running_studies(session) < MAX_CONCURRENT_STUDIES


def start_or_queue_study(session, cfg: StudyConfig, dry_run: bool):
    """
    Crea el estudio y, si hay cupo, lanza su ejecucion en segundo plano.
    Si no hay cupo (ya hay MAX_CONCURRENT_STUDIES corriendo), lo deja
    'queued' -- se arrancara solo cuando otro estudio libere un cupo.
    """
    if can_start_immediately(session):
        study = repo.create_study(session, cfg, status="running", dry_run=dry_run)
        _spawn(cfg, study.id, dry_run)
    else:
        study = repo.create_study(session, cfg, status="queued", dry_run=dry_run)
    return study


def _spawn(cfg: StudyConfig, study_id: str, dry_run: bool) -> None:
    threading.Thread(
        target=_run_and_cascade, args=(cfg, study_id, dry_run), daemon=True
    ).start()


def _run_and_cascade(cfg: StudyConfig, study_id: str, dry_run: bool) -> None:
    execute_study(cfg, study_id, dry_run)
    promote_next_queued()


def execute_study(cfg: StudyConfig, study_id: str, dry_run: bool) -> None:
    """
    Pipeline completo de un estudio: scraping -> finalizar -> deduplicar ->
    exportar a Excel. Cada estudio usa su PROPIA session (no se comparte
    entre hilos), igual que ya hace scraping.py para paralelizar portales
    dentro de un mismo estudio.
    """
    session = SessionLocal()
    try:
        run_scraping(session, cfg, study_id, dry_run=dry_run)

        was_stopped = repo.is_stop_requested(session, study_id)

        # Deduplicar y exportar el Excel ANTES de marcar el estudio como
        # terminado (finish_study, mas abajo): el dashboard usa la
        # transicion de status "running" -> terminal para decidir cuando
        # mostrar el banner de descarga. Si finish_study se llamara primero,
        # un observador (el fragment de Mis Estudios, en otra pestana/hilo)
        # podia ver el estudio ya "completed" en una ventana en la que el
        # Excel todavia no existia -- reproducido en vivo: el banner
        # mostraba "sin ofertas para exportar" pese a que el estudio si
        # tenia resultados, porque el archivo aun se estaba generando.
        if not was_stopped:
            raw_total = len(repo.get_raw_jobs_for_study(session, study_id))
            if raw_total > 0:
                stats = run_exact_dedup(session, study_id)
                if stats["jobs_created"] > 0:
                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    export_study_to_excel(session, study_id, output_dir=OUTPUT_DIR)

        repo.finish_study(session, study_id, success=True)
    except Exception:
        session.rollback()
        repo.finish_study(session, study_id, success=False)
    finally:
        session.close()


def promote_next_queued() -> None:
    """
    Arranca estudios en cola mientras haya cupo libre. Se llama al terminar
    cada estudio (desde _run_and_cascade), asi que no hace falta un
    scheduler/poller aparte: la cola avanza sola en cuanto se libera un cupo.
    """
    session = SessionLocal()
    try:
        while can_start_immediately(session):
            candidate = repo.next_queued_study(session)
            if candidate is None:
                return

            if not repo.claim_queued_study(session, candidate.id):
                # Otro hilo (terminando casi al mismo tiempo) ya lo reclamo
                # primero -- probar con el siguiente de la cola.
                continue

            if repo.is_stop_requested(session, candidate.id):
                # Cancelado mientras esperaba en cola: no llego a correr.
                repo.finish_study(session, candidate.id, success=False)
                continue

            result = repo.get_study_config(session, candidate.id)
            if result is None:
                # No deberia pasar (start_or_queue_study siempre guarda la
                # config), pero si pasa, no hay como ejecutarlo -- fallar
                # explicito en vez de dejarlo "running" para siempre.
                repo.finish_study(session, candidate.id, success=False)
                continue

            cfg, candidate_dry_run = result
            _spawn(cfg, candidate.id, candidate_dry_run)
    finally:
        session.close()
