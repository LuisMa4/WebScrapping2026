"""
Orquestador de scraping — sin dependencia de Click.
Importado por cli/commands.py y dashboard/app.py por igual.

Caracteristicas:
- Contexto de navegador fresco por keyword para portales con anti-bot (Indeed, LinkedIn)
- Ejecucion paralela de portales independientes usando threads
- Salto automatico de portales inactivos (Laborum, Jooble sin API key)
"""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace as dc_replace
from typing import Callable

from config.settings import StudyConfig
from database import repository as repo

logger = logging.getLogger("sivml.scraping")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Lock para escrituras en DB cuando hay ejecucion paralela
_db_lock = threading.Lock()


def run_scraping(
    session,
    cfg: StudyConfig,
    study_id: str,
    dry_run: bool = False,
    on_progress: Callable[[str], None] | None = None,
    parallel: bool = True,
) -> None:
    """
    Ejecuta el scraping completo para un estudio.

    Args:
        session:     SQLAlchemy session ya abierta.
        cfg:         Configuracion del estudio.
        study_id:    ID del estudio en la DB.
        dry_run:     Si True, solo listing (sin get_detail).
        on_progress: Callback de progreso — recibe strings de texto.
        parallel:    Si True, corre portales independientes en paralelo.
    """
    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            logger.info(msg)

    from scrapers import REGISTRY
    from scrapers.portal_info import PORTAL_STATUS, INACTIVE_PORTALS

    # ── Filtrar portales inactivos ───────────────────────────────────────────
    portals_to_use = []
    for p in cfg.portals:
        if p in INACTIVE_PORTALS:
            if p == "jooble" and os.environ.get("JOOBLE_API_KEY"):
                portals_to_use.append(p)
            else:
                nota = PORTAL_STATUS.get(p, {}).get("nota", "")[:70]
                log(f"[SKIP] {p}: {nota}")
        elif p not in REGISTRY:
            log(f"[SKIP] {p}: portal desconocido")
        else:
            portals_to_use.append(p)

    if not portals_to_use:
        log("[WARN] Ningun portal activo.")
        return

    cfg = dc_replace(cfg, portals=portals_to_use)

    # ── Agrupar portales por tipo de ejecucion ───────────────────────────────
    # Portales que necesitan Playwright
    pw_portals = [p for p in portals_to_use if REGISTRY[p].engine == "playwright"]
    # Portales que usan requests (pueden ir en threads sin Playwright)
    req_portals = [p for p in portals_to_use if REGISTRY[p].engine != "playwright"]
    # Portales con anti-bot agresivo: contexto fresco por keyword (Indeed, LinkedIn)
    fresh_ctx_portals = {p for p in pw_portals if getattr(REGISTRY[p], "fresh_context_per_keyword", False)}
    # Portales Playwright normales: comparten un contexto (mas rapido)
    shared_ctx_portals = [p for p in pw_portals if p not in fresh_ctx_portals]

    log(f"Portales activos: {', '.join(portals_to_use)}")
    if fresh_ctx_portals:
        log(f"  Contexto fresco por keyword: {', '.join(fresh_ctx_portals)}")
    if parallel and len(portals_to_use) > 1:
        log(f"  Modo: ejecucion paralela de portales")
    else:
        log(f"  Modo: ejecucion secuencial")

    # ── Lanzar scraping ──────────────────────────────────────────────────────
    if parallel and len(portals_to_use) > 1:
        _run_parallel(session, cfg, study_id, dry_run, log,
                      shared_ctx_portals, fresh_ctx_portals, req_portals)
    else:
        _run_sequential(session, cfg, study_id, dry_run, log,
                        shared_ctx_portals, fresh_ctx_portals, req_portals)


# ---------------------------------------------------------------------------
# Ejecucion paralela: cada portal en su propio thread con su propio browser
# ---------------------------------------------------------------------------

def _make_session_factory(session):
    """
    Extrae el engine del session actual y devuelve una factory para crear
    sessions nuevas en threads secundarios (sin compartir el session original).
    """
    from sqlalchemy.orm import sessionmaker
    engine = session.get_bind()
    return sessionmaker(bind=engine)


def _run_parallel(session, cfg, study_id, dry_run, log,
                  shared_ctx_portals, fresh_ctx_portals, req_portals):
    """Corre cada portal en un thread independiente con su propio browser y session."""
    from playwright.sync_api import sync_playwright

    SessionFactory = _make_session_factory(session)

    def run_portal_group(portals, use_fresh_ctx):
        """Un thread por portal — crea su propia session de DB."""
        thread_session = SessionFactory()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=cfg.scraper.headless)
                try:
                    for portal_name in portals:
                        if use_fresh_ctx:
                            _scrape_portal_fresh_ctx(thread_session, cfg, study_id, dry_run,
                                                      browser, portal_name, log)
                        else:
                            ctx = browser.new_context(user_agent=_UA)
                            page = ctx.new_page()
                            page.set_default_timeout(cfg.scraper.timeout_ms)
                            try:
                                _scrape_portal(thread_session, cfg, study_id, dry_run,
                                               page, portal_name, log)
                            finally:
                                ctx.close()
                finally:
                    browser.close()
        finally:
            thread_session.close()

    def run_requests_portal(portal_name):
        thread_session = SessionFactory()
        try:
            _scrape_portal(thread_session, cfg, study_id, dry_run, None, portal_name, log)
        finally:
            thread_session.close()

    futures = []
    n_workers = len(shared_ctx_portals) + len(fresh_ctx_portals) + len(req_portals)
    with ThreadPoolExecutor(max_workers=max(n_workers, 1)) as executor:
        for portal in shared_ctx_portals:
            futures.append(executor.submit(run_portal_group, [portal], False))
        for portal in fresh_ctx_portals:
            futures.append(executor.submit(run_portal_group, [portal], True))
        for portal in req_portals:
            futures.append(executor.submit(run_requests_portal, portal))

        for f in as_completed(futures):
            exc = f.exception()
            if exc:
                logger.error(f"Error en thread de portal: {exc}")


# ---------------------------------------------------------------------------
# Ejecucion secuencial
# ---------------------------------------------------------------------------

def _run_sequential(session, cfg, study_id, dry_run, log,
                    shared_ctx_portals, fresh_ctx_portals, req_portals):
    """Ejecuta portales uno tras otro, compartiendo el browser donde es posible."""
    from playwright.sync_api import sync_playwright

    all_pw_portals = shared_ctx_portals + list(fresh_ctx_portals)

    if all_pw_portals:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=cfg.scraper.headless)
            try:
                for portal_name in all_pw_portals:
                    if portal_name in fresh_ctx_portals:
                        _scrape_portal_fresh_ctx(session, cfg, study_id, dry_run,
                                                  browser, portal_name, log)
                    else:
                        ctx = browser.new_context(user_agent=_UA)
                        page = ctx.new_page()
                        page.set_default_timeout(cfg.scraper.timeout_ms)
                        try:
                            _scrape_portal(session, cfg, study_id, dry_run,
                                           page, portal_name, log)
                        finally:
                            ctx.close()
            finally:
                browser.close()

    for portal_name in req_portals:
        _scrape_portal(session, cfg, study_id, dry_run, None, portal_name, log)


# ---------------------------------------------------------------------------
# Contexto fresco por keyword (Indeed, LinkedIn)
# ---------------------------------------------------------------------------

def _scrape_portal_fresh_ctx(session, cfg, study_id, dry_run, browser, portal_name, log):
    """
    Para portales con anti-bot agresivo: cada keyword recibe un contexto
    de navegador totalmente nuevo (cookies limpias, nueva sesion).
    Indeed devuelve resultados para todas las keywords con esta tecnica.
    """
    from scrapers import get_scraper

    ScraperClass = get_scraper(portal_name)
    log(f"\n>> Portal: {portal_name.upper()} (contexto fresco por keyword)")

    for keyword in cfg.keywords:
        for city in cfg.cities:
            # Nuevo contexto = cookies nuevas = nueva sesion = sin deteccion de bot
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            page.set_default_timeout(cfg.scraper.timeout_ms)
            scraper = ScraperClass(cfg, page=page)

            with _db_lock:
                run = repo.start_scraping_run(session, study_id, portal_name, keyword, city)
            found = 0
            new_count = 0

            try:
                jobs = scraper.search(keyword, city)
                if not dry_run:
                    enriched = []
                    for job in jobs:
                        detail = scraper.get_detail(job.url)
                        job = scraper._merge_detail(job, detail)
                        job.study_id = study_id
                        job.keyword_matched = keyword
                        enriched.append(job)
                    jobs = enriched
                else:
                    for job in jobs:
                        job.study_id = study_id
                        job.keyword_matched = keyword

                found = len(jobs)
                for job in jobs:
                    with _db_lock:
                        _, is_new = repo.upsert_raw_job(session, job)
                    if is_new:
                        new_count += 1

                with _db_lock:
                    repo.finish_scraping_run(session, run.id,
                                              records_found=found, records_new=new_count)
                log(f"    {keyword} / {city}: {found} encontradas, {new_count} nuevas")

            except Exception as exc:
                with _db_lock:
                    repo.finish_scraping_run(session, run.id, records_found=found,
                                              records_new=new_count, success=False,
                                              error_message=str(exc))
                logger.error(f"Error {portal_name}/{keyword}/{city}: {exc}")
            finally:
                ctx.close()


# ---------------------------------------------------------------------------
# Scraping de un portal con page ya configurada (compartida o requests)
# ---------------------------------------------------------------------------

def _scrape_portal(session, cfg, study_id, dry_run, page, portal_name, log):
    """Scraping de un portal usando la page/None que recibe."""
    from scrapers import get_scraper

    ScraperClass = get_scraper(portal_name)
    scraper = ScraperClass(cfg, page=page)
    log(f"\n>> Portal: {portal_name.upper()}")

    for keyword in cfg.keywords:
        for city in cfg.cities:
            with _db_lock:
                run = repo.start_scraping_run(session, study_id, portal_name, keyword, city)
            found = 0
            new_count = 0

            try:
                jobs = scraper.search(keyword, city)
                if not dry_run:
                    enriched = []
                    for job in jobs:
                        detail = scraper.get_detail(job.url)
                        job = scraper._merge_detail(job, detail)
                        job.study_id = study_id
                        job.keyword_matched = keyword
                        enriched.append(job)
                    jobs = enriched
                else:
                    for job in jobs:
                        job.study_id = study_id
                        job.keyword_matched = keyword

                found = len(jobs)
                for job in jobs:
                    with _db_lock:
                        _, is_new = repo.upsert_raw_job(session, job)
                    if is_new:
                        new_count += 1

                with _db_lock:
                    repo.finish_scraping_run(session, run.id,
                                              records_found=found, records_new=new_count)
                log(f"    {keyword} / {city}: {found} encontradas, {new_count} nuevas")

            except Exception as exc:
                with _db_lock:
                    repo.finish_scraping_run(session, run.id, records_found=found,
                                              records_new=new_count, success=False,
                                              error_message=str(exc))
                logger.error(f"Error {portal_name}/{keyword}/{city}: {exc}")
