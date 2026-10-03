"""Tests de construccion del comando schtasks (sin ejecutarlo de verdad)."""
from scripts import install_weekly_task


class TestBuildSchtasksCommand:
    def test_includes_task_name(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert install_weekly_task.TASK_NAME in cmd

    def test_defaults_to_7am(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert "07:00" in cmd

    def test_custom_hour_is_used(self):
        cmd = install_weekly_task.build_schtasks_command(hour_minute="09:30")
        assert "09:30" in cmd
        assert "07:00" not in cmd

    def test_schedules_weekly_on_monday(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert "weekly" in cmd
        assert "MON" in cmd

    def test_uses_given_python_exe_and_script_path(self):
        cmd = install_weekly_task.build_schtasks_command(python_exe="C:\\fake\\python.exe")
        tr_index = cmd.index("/tr")
        tr_value = cmd[tr_index + 1]
        assert "C:\\fake\\python.exe" in tr_value
        assert "weekly_run.py" in tr_value

    def test_runs_whether_or_not_a_user_is_logged_on(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert "/ru" in cmd
        ru_index = cmd.index("/ru")
        ru_value = cmd[ru_index + 1]
        assert ru_value  # non-empty username
        assert "/np" in cmd


class TestBuildCatchupSchtasksCommand:
    def test_includes_catchup_task_name(self):
        cmd = install_weekly_task.build_catchup_schtasks_command()
        assert install_weekly_task.CATCHUP_TASK_NAME in cmd

    def test_triggers_daily_not_weekly(self):
        # "onlogon" se probo primero pero tambien exige elevacion
        # ("Acceso denegado" al crearla sin admin, confirmado en vivo) --
        # "daily" no la necesita y logra el mismo objetivo: reintentar
        # hasta que un dia si haya sesion iniciada a esa hora.
        cmd = install_weekly_task.build_catchup_schtasks_command()
        assert "daily" in cmd
        assert "weekly" not in cmd
        assert "onlogon" not in cmd

    def test_defaults_to_8pm(self):
        cmd = install_weekly_task.build_catchup_schtasks_command()
        assert "20:00" in cmd

    def test_custom_hour_is_used(self):
        cmd = install_weekly_task.build_catchup_schtasks_command(hour_minute="18:30")
        assert "18:30" in cmd
        assert "20:00" not in cmd

    def test_does_not_require_ru_or_np(self):
        # /sc daily no necesita correr sin sesion iniciada -- a diferencia
        # de la tarea principal, esta no deberia necesitar elevacion.
        cmd = install_weekly_task.build_catchup_schtasks_command()
        assert "/ru" not in cmd
        assert "/np" not in cmd

    def test_uses_given_python_exe_and_script_path(self):
        cmd = install_weekly_task.build_catchup_schtasks_command(python_exe="C:\\fake\\python.exe")
        tr_index = cmd.index("/tr")
        tr_value = cmd[tr_index + 1]
        assert "C:\\fake\\python.exe" in tr_value
        assert "weekly_run.py" in tr_value

    def test_task_names_are_distinct(self):
        assert install_weekly_task.TASK_NAME != install_weekly_task.CATCHUP_TASK_NAME
