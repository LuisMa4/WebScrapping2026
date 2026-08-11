"""
Registra (o quita) en el Programador de tareas de Windows la tarea que
corre weekly_run.py cada lunes. Uso standalone:
    python scripts/install_weekly_task.py [--hora HH:MM]
Tambien invocado desde el boton "Instalar tarea programada de Windows" del
dashboard (dashboard/app.py::_render_automation_section).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SIVML_CorridaSemanal"
ROOT = Path(__file__).parent.parent


def _current_username() -> str:
    try:
        return os.getlogin()
    except OSError:
        return os.environ.get("USERNAME", "")


def build_schtasks_command(hour_minute: str = "07:00", python_exe: str | None = None) -> list[str]:
    python_exe = python_exe or sys.executable
    script_path = ROOT / "weekly_run.py"
    return [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python_exe}" "{script_path}"',
        "/sc", "weekly",
        "/d", "MON",
        "/st", hour_minute,
        "/ru", _current_username(), "/np",  # corre haya o no un usuario con sesion iniciada
        "/f",  # sobreescribe si ya existe -- permite re-instalar tras cambiar la hora
    ]


def install_task(hour_minute: str = "07:00", python_exe: str | None = None) -> tuple[bool, str]:
    cmd = build_schtasks_command(hour_minute, python_exe)
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def uninstall_task() -> tuple[bool, str]:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Instala la tarea programada semanal de SIVML.")
    parser.add_argument("--hora", default="07:00", help="Hora de ejecucion (HH:MM), default 07:00")
    args = parser.parse_args()
    ok, output = install_task(args.hora)
    print(output)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
