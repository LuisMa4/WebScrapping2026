"""
Limpieza de procesos de Chromium huerfanos dejados por Playwright cuando un
proceso de scraping muere abruptamente -- crash, kill forzado (Stop-Process),
conflicto de dos dashboards en el mismo puerto, o Streamlit reiniciando el
script a mitad de una corrida. En esos casos el `finally: browser.close()`
del navegador nunca se ejecuta y el proceso de Chromium queda corriendo
indefinidamente, sin que nada lo cierre.

Solo se tocan navegadores lanzados por Playwright (identificados por su ruta
de instalacion bajo la cache "ms-playwright") que ya no tienen un proceso
python.exe vivo como ancestro -- nunca se toca el navegador personal del
usuario, que corre desde una ruta de instalacion distinta.
"""
from __future__ import annotations

import logging

import psutil

logger = logging.getLogger("sivml.browser_cleanup")

_PLAYWRIGHT_PATH_MARKER = "ms-playwright"
_MAX_ANCESTOR_DEPTH = 10


def _is_playwright_browser(proc) -> bool:
    try:
        exe = proc.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    return _PLAYWRIGHT_PATH_MARKER in exe.lower()


def _has_live_python_ancestor(proc) -> bool:
    """True si algun ancestro del proceso es un python.exe vivo."""
    try:
        current = proc.parent()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    depth = 0
    while current is not None and depth < _MAX_ANCESTOR_DEPTH:
        try:
            name = current.name().lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            return False
        if name.startswith("python"):
            return True
        try:
            current = current.parent()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return False
        depth += 1
    return False


def cleanup_orphaned_browsers() -> int:
    """
    Termina procesos de Chromium de Playwright que ya no tienen un proceso
    python vivo como ancestro. Devuelve la cantidad de procesos terminados.
    Pensado para llamarse al arrancar el dashboard, limpiando restos de una
    sesion anterior que se interrumpio abruptamente.
    """
    killed = 0
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if not _is_playwright_browser(proc):
                continue
            if _has_live_python_ancestor(proc):
                continue
            proc.kill()
            killed += 1
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    if killed:
        logger.info(f"Limpiados {killed} procesos de navegador huerfanos de Playwright")
    return killed
