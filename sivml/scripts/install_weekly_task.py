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
semanas seguidas.

La tarea de respaldo corre cada 30 minutos (intervalo, no un disparador de
evento): "al iniciar sesion" y "al arrancar la PC" (/sc onlogon, /sc
onstart) TAMBIEN exigen elevacion -- "Acceso denegado" al crear cualquiera
de las dos sin admin, confirmado en vivo -- pero un intervalo de minutos
(/sc minute /mo N) no la necesita. weekly_run.py::main() se pone al dia
solo si todavia no corrio nada esta semana (_needs_catchup_run), asi que
disparar cada 30 min no duplica trabajo -- en el caso comun (ya corrio
esta semana) solo abre la BD, revisa una fecha y sale, practicamente
gratis. Efecto practico: como mucho 30 min despues de prender la PC o
iniciar sesion, si hace falta ponerse al dia, se pone al dia sola.
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


def build_catchup_schtasks_command(interval_minutes: int = 30, python_exe: str | None = None) -> list[str]:
    python_exe = python_exe or sys.executable
    script_path = ROOT / "weekly_run.py"
    return [
        "schtasks", "/create",
        "/tn", CATCHUP_TASK_NAME,
        "/tr", f'"{python_exe}" "{script_path}"',
        "/sc", "minute",
        "/mo", str(interval_minutes),
        "/f",
    ]


def install_catchup_task(interval_minutes: int = 30, python_exe: str | None = None) -> tuple[bool, str]:
    cmd = build_catchup_schtasks_command(interval_minutes, python_exe)
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
