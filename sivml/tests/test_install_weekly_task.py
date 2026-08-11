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
