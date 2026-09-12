import subprocess
from pathlib import Path

from scripts.diagnose_boss_gacha_startup import diagnose_startup


def _result(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def _runner(outputs):
    values = iter(outputs)
    return lambda command: next(values)


def test_reports_ready_with_resolved_component_and_running_process():
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("HD-Player.exe"), instance="P64",
        path_is_file=lambda _: True,
        run=_runner([_result(stdout="adb"), _result(stdout="device\n"),
                     _result(stdout="jp.co.game/.Main\n"), _result(stdout="123\n")]),
    )
    assert result["status"] == "ready"
    assert result["component"] == "jp.co.game/.Main"
    assert result["input_count"] == 0


def test_reports_needs_launch_without_starting_application():
    calls = []
    outputs = iter([_result(stdout="adb"), _result(stdout="device\n"),
                    _result(stdout="jp.co.game/.Main\n"), _result(code=1)])
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("HD-Player.exe"), instance="P64",
        path_is_file=lambda _: True, run=lambda command: calls.append(command) or next(outputs),
    )
    assert result["status"] == "needs_launch"
    assert result["reason"] == "app_not_running"
    assert all("start" not in command and "monkey" not in command for command in calls)


def test_stops_when_launcher_is_missing_without_adb_call():
    calls = []
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("missing.exe"), instance="P64",
        path_is_file=lambda _: False, run=lambda command: calls.append(command) or _result(),
    )
    assert result["reason"] == "bluestacks_launcher_missing"
    assert calls == []


def test_stops_at_adb_device_stage_when_offline():
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("HD-Player.exe"), instance="P64",
        path_is_file=lambda _: True,
        run=_runner([_result(stdout="adb"), _result(code=1, stderr="offline")]),
    )
    assert result["stage"] == "adb_device"
    assert result["reason"] == "adb_device_not_ready"


def test_stops_when_package_launcher_cannot_be_resolved():
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("HD-Player.exe"), instance="P64",
        path_is_file=lambda _: True,
        run=_runner([_result(stdout="adb"), _result(stdout="device\n"), _result(code=1, stderr="missing")]),
    )
    assert result["stage"] == "android_package"
    assert result["reason"] == "package_launcher_unresolved"


def test_classifies_bluestacks_configuration_read_failure_before_commands():
    calls = []
    result = diagnose_startup(
        serial="emulator-5554", package="jp.co.game", launcher=Path("HD-Player.exe"), instance="P64",
        bluestacks_error_text="Failed to read configuration file.",
        path_is_file=lambda _: True, run=lambda command: calls.append(command) or _result(),
    )
    assert result["stage"] == "bluestacks_configuration"
    assert result["reason"] == "bluestacks_configuration_unreadable"
    assert calls == []
