import json
from types import SimpleNamespace

import pytest

from scripts import adb_runtime, labyrinth_route
from scripts import ensure_bluestacks_live as ensure
from scripts import task_enter_labyrinth_live as route
from scripts import task_prepare_boss_gacha_live as prepare


def test_adb_diagnostics_reports_serial_mismatch_without_fallback(monkeypatch):
    monkeypatch.setattr(
        ensure,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=("List of devices attached\n"
                    "emulator-5554 device product:SCG02_jp_kdi model:SCG02 device:SCG02\n"),
            stderr="",
        ),
    )

    result = ensure.adb_device_diagnostics("127.0.0.1:5555", adb="test-adb")

    assert result["requested_serial"] == "127.0.0.1:5555"
    assert result["requested_serial_available"] is False
    assert result["available_devices"] == [
        "emulator-5554 device product:SCG02_jp_kdi model:SCG02 device:SCG02"
    ]


def test_launch_emulator_returns_the_player_process_id(monkeypatch, tmp_path):
    launcher = tmp_path / "HD-Player.exe"
    launcher.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        ensure.subprocess, "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(pid=45678),
    )

    result = ensure.launch_emulator(launcher, "Nougat32")

    assert result == 45678
    assert calls[0][0] == [str(launcher), "--instance", "Nougat32"]


def test_prepare_step_timeout_keeps_partial_utf8_diagnostics(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise prepare.subprocess.TimeoutExpired(
            cmd=["child"], timeout=12, output="進行中".encode(), stderr=b"\xff"
        )

    monkeypatch.setattr(prepare, "run_without_console", timeout)

    code, result = prepare._run_step("navigation", ["child"], timeout=12, env={})

    assert code == 2
    assert result["status"] == "safety_stop"
    assert result["reason"] == "step_timeout"
    assert result["timeout_seconds"] == 12
    assert result["stdout"] == "進行中"
    assert result["stderr"] == "�"


def test_android_boot_stops_after_three_failed_tcp_connects(monkeypatch):
    clock = {"now": 0.0}
    connections = []

    def fake_run(command, **_kwargs):
        if command[1] == "connect":
            connections.append(command)
            return SimpleNamespace(returncode=1, stdout="failed to connect", stderr="")
        raise AssertionError(f"unexpected adb call: {command}")

    monkeypatch.setattr(ensure, "device_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ensure, "run", fake_run)
    monkeypatch.setattr(ensure.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(ensure.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))

    with pytest.raises(RuntimeError, match="adb_connection_retries_exhausted"):
        ensure.wait_for_android_boot("127.0.0.1:5555", adb="test-adb", timeout=180)

    assert len(connections) == 3


def test_android_boot_stops_after_three_missing_local_devices(monkeypatch):
    clock = {"now": 0.0}
    checks = []

    def fake_state(serial, **_kwargs):
        checks.append(serial)

    monkeypatch.setattr(ensure, "device_state", fake_state)
    monkeypatch.setattr(ensure.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(ensure.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))

    with pytest.raises(RuntimeError, match="adb_device_unavailable_retries_exhausted"):
        ensure.wait_for_android_boot("emulator-5554", adb="test-adb", timeout=180)

    assert checks == ["emulator-5554"] * 3


def test_adb_client_and_serial_use_persisted_runtime_settings(monkeypatch, tmp_path):
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")
    runtime_config = tmp_path / "runtime.json"
    gui_config = tmp_path / "gui.json"
    runtime_config.write_text(json.dumps({"adb_path": str(adb)}), encoding="utf-8")
    gui_config.write_text('{"serial": "emulator-5554"}', encoding="utf-8")
    monkeypatch.setattr(adb_runtime, "ADB_RUNTIME_CONFIG", runtime_config)
    monkeypatch.setattr(adb_runtime, "GUI_SETTINGS", gui_config)
    monkeypatch.delenv(adb_runtime.ADB_PATH_ENV, raising=False)

    assert adb_runtime.resolve_adb_path() == str(adb.resolve())
    assert adb_runtime.resolve_adb_serial() == "emulator-5554"


def test_device_lock_is_global_across_serial_aliases():
    assert route._device_lock("127.0.0.1:5555") == route._device_lock("emulator-5554")


def test_adb_healthcheck_retries_three_times_without_restarting_server(monkeypatch):
    commands = []

    def timeout(command, **_kwargs):
        commands.append(command)
        raise labyrinth_route.subprocess.TimeoutExpired(cmd=command, timeout=3)

    monkeypatch.setattr(labyrinth_route, "run_without_console", timeout)
    monkeypatch.setattr(labyrinth_route.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="3回失敗"):
        labyrinth_route.ensure_adb_connection(serial="emulator-5554")

    assert len(commands) == 3
    assert all(command[-1] == "get-state" for command in commands)
