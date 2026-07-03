"""
Lanzador de SIVML — un .exe hecho a partir de este script.
Doble click -> instala dependencias si faltan (primera vez) -> abre el
dashboard en el navegador. No empaqueta Streamlit/Playwright dentro del
.exe: usa el Python ya instalado en la PC, así el .exe se genera rápido
y no sufre los problemas típicos de empaquetar Streamlit con PyInstaller.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

PORT = 8501
URL = f"http://localhost:{PORT}"


def dashboard_already_running() -> bool:
    """
    True si ya hay un dashboard SIVML respondiendo en este puerto -- evita
    lanzar una segunda instancia que compita por el mismo puerto, lo que
    puede dejar el estado del scraping confuso (dos procesos, uno de ellos
    huerfano, y el usuario sin saber a cual le esta hablando el navegador).
    """
    try:
        with urllib.request.urlopen(URL, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        # El .exe vive en la raiz de sivml/, junto a dashboard/, requirements.txt, etc.
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_python() -> str | None:
    for candidate in ("python", "python3"):
        path = shutil.which(candidate)
        if path:
            return path
    if shutil.which("py"):
        return "py"
    return None


def run(python_exe: str, args: list[str], cwd: str) -> int:
    cmd = [python_exe] + args if python_exe != "py" else ["py", "-3"] + args
    print("  > " + " ".join(cmd))
    return subprocess.call(cmd, cwd=cwd)


def has_dependencies(python_exe: str, cwd: str) -> bool:
    check_cmd = [python_exe, "-c", "import streamlit, playwright"]
    if python_exe == "py":
        check_cmd = ["py", "-3", "-c", "import streamlit, playwright"]
    return subprocess.call(
        check_cmd, cwd=cwd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) == 0


def main() -> int:
    base_dir = app_dir()
    print("=" * 60)
    print("  SIVML - Sistema Inteligente de Vigilancia del Mercado Laboral")
    print("=" * 60)

    if dashboard_already_running():
        print(f"\nYa hay un dashboard SIVML abierto en {URL} -- lo abro en el navegador.")
        print("(No se lanza una segunda instancia para evitar conflictos de puerto.)")
        webbrowser.open(URL)
        time.sleep(2)
        return 0

    python_exe = find_python()
    if not python_exe:
        print("\n[ERROR] No se encontro Python instalado en esta PC.")
        print("Instala Python 3.11+ desde https://python.org/downloads")
        input("\nPresiona Enter para cerrar...")
        return 1

    requirements = os.path.join(base_dir, "requirements.txt")

    if not has_dependencies(python_exe, base_dir):
        print("\nPrimera ejecucion: instalando dependencias (puede tardar varios minutos)...")
        rc = run(python_exe, ["-m", "pip", "install", "-r", requirements], cwd=base_dir)
        if rc != 0:
            print("\n[ERROR] No se pudieron instalar las dependencias.")
            input("\nPresiona Enter para cerrar...")
            return 1

    marker = os.path.join(base_dir, ".playwright_installed")
    if not os.path.exists(marker):
        print("\nInstalando navegador Chromium para el scraping (solo la primera vez)...")
        rc = run(python_exe, ["-m", "playwright", "install", "chromium"], cwd=base_dir)
        if rc == 0:
            open(marker, "w").close()
        else:
            print("[WARN] No se pudo instalar Chromium. El scraping podria fallar.")

    print("\nIniciando el dashboard...")
    log_path = os.path.join(base_dir, "sivml_dashboard.log")
    log_file = open(log_path, "w", encoding="utf-8")

    streamlit_cmd = [
        python_exe, "-m", "streamlit", "run",
        os.path.join(base_dir, "dashboard", "app.py"),
        "--server.headless", "true",
        "--server.port", str(PORT),
    ]
    if python_exe == "py":
        streamlit_cmd = ["py", "-3", "-m", "streamlit", "run",
                          os.path.join(base_dir, "dashboard", "app.py"),
                          "--server.headless", "true",
                          "--server.port", str(PORT)]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        streamlit_cmd, cwd=base_dir,
        stdout=log_file, stderr=log_file,
        creationflags=creationflags,
    )

    print("Esperando a que el dashboard este listo...")
    time.sleep(4)
    webbrowser.open(URL)

    print(f"\nListo. El dashboard esta abierto en {URL}")
    print("Puedes cerrar esta ventana; el dashboard seguira funcionando.")
    print(f"(Si algo falla, revisa el log en: {log_path})")
    time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
