"""
Registra (o quita) en el Programador de tareas de Windows las tareas que
corren weekly_run.py: la principal (lunes a una hora fija) y una de
respaldo (al iniciar sesion). Uso standalone:
    python scripts/install_weekly_task.py [--hora HH:MM]
Tambien invocado desde el boton "Instalar tarea programada de Windows" del
dashboard (dashboard/app.py::_render_automation_section).

Por que dos tareas: la de los lunes 7am solo corre si hay sesion iniciada
en ese instante exacto (ver gotcha de /ru + /np en la memoria del
proyecto -- requiere una cuenta Windows local con permisos de admin que
este usuario no tiene). Si el usuario no esta con sesion iniciada justo a
esa hora, el lunes completo se pierde sin aviso -- confirmado en vivo 4
semanas seguidas. La tarea de respaldo corre todos los dias a una hora
fija (no "al iniciar sesion": ese tipo de disparador TAMBIEN exige
elevacion -- "Acceso denegado" al crearla sin admin, confirmado en vivo);
weekly_run.py::main() se pone al dia solo si todavia no corrio nada esta
semana (_needs_catchup_run), asi que disparar todos los dias no duplica
trabajo -- simplemente reintenta hasta que un dia si hay sesion iniciada
a esa hora.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SIVML_CorridaSemanal"
CATCHUP_TASK_NAME = "SIVML_CorridaSemanal_Catchup"
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


def build_catchup_schtasks_command(hour_minute: str = "20:00", python_exe: str | None = None) -> list[str]:
    python_exe = python_exe or sys.executable
    script_path = ROOT / "weekly_run.py"
    return [
        "schtasks", "/create",
        "/tn", CATCHUP_TASK_NAME,
        "/tr", f'"{python_exe}" "{script_path}"',
        "/sc", "daily",
        "/st", hour_minute,
        "/f",
    ]


def install_catchup_task(hour_minute: str = "20:00", python_exe: str | None = None) -> tuple[bool, str]:
    cmd = build_catchup_schtasks_command(hour_minute, python_exe)
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def uninstall_catchup_task() -> tuple[bool, str]:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", CATCHUP_TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Instala las tareas programadas semanales de SIVML.")
    parser.add_argument("--hora", default="07:00", help="Hora de ejecucion (HH:MM), default 07:00")
    args = parser.parse_args()

    ok1, output1 = install_task(args.hora)
    print(f"[{TASK_NAME}] {output1}")

    ok2, output2 = install_catchup_task()
    print(f"[{CATCHUP_TASK_NAME}] {output2}")

    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
