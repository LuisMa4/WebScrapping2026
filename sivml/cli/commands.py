from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import click

from config.settings import load_study_config, StudyConfig
from database.session import SessionLocal, init_db
from database import repository as repo

logger = logging.getLogger("sivml.cli")


def _setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Grupo principal
# ---------------------------------------------------------------------------

@click.group()
@click.option("--log-level", default="INFO", show_default=True,
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False))
def cli(log_level: str):
    """SIVML - Sistema Inteligente de Vigilancia del Mercado Laboral"""
    _setup_logging(log_level)
    init_db()


# ---------------------------------------------------------------------------
# sivml scrape
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True), help="Ruta al archivo YAML de configuración del estudio")
@click.option("--portals", default=None,
              help="Portales a usar (coma-separados). Si se omite, se usan los del YAML.")
@click.option("--keywords", default=None,
              help="Palabras clave (coma-separadas). Sobrescribe las del YAML.")
@click.option("--cities", default=None,
              help="Ciudades (coma-separadas). Sobrescribe las del YAML.")
@click.option("--max-pages", default=None, type=int,
              help="Máximo de páginas por búsqueda. Sobrescribe el YAML.")
@click.option("--dry-run", is_flag=True,
              help="Inserta en DB pero omite el get_detail() por oferta.")
def scrape(config_path, portals, keywords, cities, max_pages, dry_run):
    """Ejecuta el scraping según la configuración del estudio."""
    from dataclasses import replace

    cfg = load_study_config(config_path)

    # Sobrescrituras por CLI
    overrides = {}
    if portals:
        overrides["portals"] = [p.strip() for p in portals.split(",")]
    if keywords:
        overrides["keywords"] = [k.strip() for k in keywords.split(",")]
    if cities:
        overrides["cities"] = [c.strip() for c in cities.split(",")]
    if max_pages:
        overrides["scraper"] = replace(cfg.scraper, max_pages=max_pages)

    if overrides:
        cfg = replace(cfg, **overrides)

    click.echo(f"\n{'='*60}")
    click.echo(f"  SIVML - Scraping: {cfg.study_name}")
    click.echo(f"  Portales : {', '.join(cfg.portals)}")
    click.echo(f"  Keywords : {', '.join(cfg.keywords)}")
    click.echo(f"  Ciudades : {', '.join(cfg.cities)}")
    click.echo(f"  Study ID : {cfg.study_id}")
    click.echo(f"{'='*60}\n")

    session = SessionLocal()
    try:
        study = repo.create_study(session, cfg, config_path)
        _run_scraping(session, cfg, study.id, dry_run=dry_run)
        repo.finish_study(session, study.id, success=True)
        click.echo(f"\n[OK] Scraping completado. Study ID: {study.id}")
        click.echo(f"  Ejecutar procesamiento: python main.py process --study-id {study.id}")
    except Exception as exc:
        logger.error(f"Error fatal: {exc}", exc_info=True)
        if "study" in dir():
            repo.finish_study(session, study.id, success=False)
        sys.exit(1)
    finally:
        session.close()


def _run_scraping(session, cfg: StudyConfig, study_id: str, dry_run: bool):
    """Wrapper CLI: delega en scraping.run_scraping usando click.echo como logger."""
    from scraping import run_scraping
    run_scraping(session, cfg, study_id, dry_run=dry_run, on_progress=click.echo)


# ---------------------------------------------------------------------------
# sivml process
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--study-id", required=True, help="ID del estudio a procesar")
@click.option("--skip-dedup", is_flag=True, help="Omitir deduplicación")
@click.option("--skip-normalize", is_flag=True, help="Omitir normalización (solo dedup)")
@click.option("--fuzzy", is_flag=True, help="Ejecutar dedup fuzzy después del exacto")
def process(study_id, skip_dedup, skip_normalize, fuzzy):
    """Normaliza y deduplica las ofertas de un estudio."""
    session = SessionLocal()
    try:
        study = repo.get_study(session, study_id)
        if not study:
            click.echo(f"[ERROR] Estudio {study_id!r} no encontrado.")
            sys.exit(1)

        click.echo(f"\n>> Procesando estudio: {study.name}")

        if not skip_dedup:
            from processing.deduplicator import run_exact_dedup, run_fuzzy_dedup
            click.echo("  Ejecutando dedup exacto...")
            stats = run_exact_dedup(session, study_id)
            click.echo(f"    {stats['jobs_created']} jobs creados, {stats['duplicates_marked']} duplicados")

            if fuzzy:
                click.echo("  Ejecutando dedup fuzzy...")
                stats2 = run_fuzzy_dedup(session, study_id)
                click.echo(f"    {stats2['merged']} jobs fusionados")

        click.echo(f"\n[OK] Procesamiento completado.")
        click.echo(f"  Exportar: python main.py export --study-id {study_id} --format excel")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# sivml export
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--study-id", required=True, help="ID del estudio a exportar")
@click.option("--format", "fmt", default="excel",
              type=click.Choice(["excel"]), show_default=True)
@click.option("--output", default="output", show_default=True,
              help="Directorio de salida")
def export(study_id, fmt, output):
    """Genera el reporte de exportación del estudio."""
    session = SessionLocal()
    try:
        if fmt == "excel":
            from exports.excel_exporter import export_study_to_excel
            filepath = export_study_to_excel(session, study_id, output_dir=output)
            click.echo(f"\n[OK] Excel generado: {filepath}")
    except ValueError as exc:
        click.echo(f"[ERROR] {exc}")
        sys.exit(1)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# sivml studies
# ---------------------------------------------------------------------------

@cli.group()
def studies():
    """Gestión de estudios."""


@studies.command("list")
def studies_list():
    """Lista todos los estudios disponibles."""
    session = SessionLocal()
    try:
        all_studies = repo.list_studies(session)
        if not all_studies:
            click.echo("No hay estudios registrados.")
            return

        click.echo(f"\n{'ID':38} {'Nombre':30} {'Estado':12} {'Inicio'}")
        click.echo("-" * 100)
        for s in all_studies:
            inicio = s.started_at.strftime("%Y-%m-%d %H:%M") if s.started_at else "-"
            click.echo(f"{s.id:38} {s.name[:28]:30} {s.status:12} {inicio}")
    finally:
        session.close()


@studies.command("show")
@click.option("--study-id", required=True)
def studies_show(study_id):
    """Muestra detalles de un estudio."""
    session = SessionLocal()
    try:
        study = repo.get_study(session, study_id)
        if not study:
            click.echo(f"Estudio {study_id!r} no encontrado.")
            return

        raw_total = len(repo.get_raw_jobs_for_study(session, study_id))
        jobs_total = len(repo.get_jobs_for_study(session, study_id))

        click.echo(f"\nEstudio   : {study.name}")
        click.echo(f"Programa  : {study.academic_program or '-'}")
        click.echo(f"ID        : {study.id}")
        click.echo(f"Estado    : {study.status}")
        click.echo(f"Inicio    : {study.started_at}")
        click.echo(f"Fin       : {study.finished_at}")
        click.echo(f"Scrapeadas: {raw_total}")
        click.echo(f"Únicas    : {jobs_total}")
    finally:
        session.close()
