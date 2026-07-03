"""
Instalador de SIVML -- doble click para preparar todo lo necesario antes de
usar SIVML.exe: instala las dependencias de Python (requirements.txt) y el
navegador Chromium que usa Playwright para el scraping.

No inicia el dashboard -- solo prepara el entorno. Al terminar, ejecuta
SIVML.exe para abrir el programa. Pensado para poder correrse de nuevo sin
problema (pip / playwright install son idempotentes).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        # El .exe vive en la raiz de sivml/, junto a SIVML.exe, requirements.txt, etc.
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


def main() -> int:
    base_dir = app_dir()
    print("=" * 60)
    print("  Instalador de SIVML")
    print("  Sistema Inteligente de Vigilancia del Mercado Laboral")
    print("=" * 60)

    python_exe = find_python()
    if not python_exe:
        print("\n[ERROR] No se encontro Python instalado en esta PC.")
        print("Instala Python 3.11+ desde https://python.org/downloads")
        print("(Marca la casilla 'Add python.exe to PATH' durante la instalacion)")
        input("\nPresiona Enter para cerrar...")
        return 1

    requirements = os.path.join(base_dir, "requirements.txt")
    if not os.path.exists(requirements):
        print(f"\n[ERROR] No se encontro requirements.txt en:\n  {base_dir}")
        print("Este instalador debe estar en la misma carpeta que SIVML.exe.")
        input("\nPresiona Enter para cerrar...")
        return 1

    print("\n[1/2] Instalando dependencias de Python (puede tardar varios minutos)...")
    rc = run(python_exe, ["-m", "pip", "install", "-r", requirements], cwd=base_dir)
    if rc != 0:
        print("\n[ERROR] No se pudieron instalar las dependencias de Python.")
        print("Revisa tu conexion a internet e intenta de nuevo.")
        input("\nPresiona Enter para cerrar...")
        return 1

    print("\n[2/2] Instalando navegador Chromium para el scraping (una sola vez)...")
    rc = run(python_exe, ["-m", "playwright", "install", "chromium"], cwd=base_dir)
    marker = os.path.join(base_dir, ".playwright_installed")
    if rc == 0:
        open(marker, "w").close()
    else:
        print("\n[WARN] No se pudo instalar Chromium. El scraping podria fallar.")
        print("       Puedes reintentar ejecutando este instalador de nuevo.")

    print("\n" + "=" * 60)
    print("  Instalacion completa. Ya puedes ejecutar SIVML.exe")
    print("=" * 60)
    input("\nPresiona Enter para cerrar...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
