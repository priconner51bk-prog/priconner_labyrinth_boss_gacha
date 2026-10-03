import ctypes
from types import SimpleNamespace

from scripts import task_boss_gacha_live as cli


def test_terminate_bluestacks_targets_visible_player_window_pid(monkeypatch):
    class FakeUser32:
        def IsWindowVisible(self, _hwnd):
            return 1

        def GetWindowTextW(self, _hwnd, title, _capacity):
            title.value = "BlueStacks App Player"

        def GetWindowThreadProcessId(self, _hwnd, process_id):
            ctypes.cast(process_id, ctypes.POINTER(ctypes.c_ulong)).contents.value = 12345

        def EnumWindows(self, callback, lparam):
            callback(321, lparam)
            return 1

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.ctypes, "windll", SimpleNamespace(user32=FakeUser32()), raising=False)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = cli.terminate_bluestacks_process()

    assert result == {"status": "terminated", "pids": [12345]}
    assert calls[0][0] == ["taskkill", "/PID", "12345", "/T", "/F"]


def test_terminate_bluestacks_uses_validated_foreground_player_pid(monkeypatch):
    class FakeUser32:
        def IsWindowVisible(self, _hwnd):
            return 1

        def GetWindowTextW(self, _hwnd, title, _capacity):
            title.value = "Sim"

        def GetWindowThreadProcessId(self, _hwnd, process_id):
            ctypes.cast(process_id, ctypes.POINTER(ctypes.c_ulong)).contents.value = 23456

        def GetForegroundWindow(self):
            return 321

        def EnumWindows(self, callback, lparam):
            callback(321, lparam)
            return 1

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.ctypes, "windll", SimpleNamespace(user32=FakeUser32()), raising=False)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "tasklist":
            return SimpleNamespace(returncode=0, stdout='"HD-Player.exe","23456","Console","1","1 K"', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = cli.terminate_bluestacks_process()

    assert result == {"status": "terminated", "pids": [23456]}
    assert calls == [
        ["tasklist", "/FI", "PID eq 23456", "/FO", "CSV", "/NH"],
        ["taskkill", "/PID", "23456", "/T", "/F"],
    ]


def test_terminate_bluestacks_uses_explicit_pid_from_preparation(monkeypatch):
    class FakeUser32:
        pass

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.ctypes, "windll", SimpleNamespace(user32=FakeUser32()), raising=False)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "tasklist":
            return SimpleNamespace(returncode=0, stdout='"HD-Player.exe","34567","Console","1","1 K"', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = cli.terminate_bluestacks_process(34567)

    assert result == {"status": "terminated", "pids": [34567]}
    assert calls == [
        ["tasklist", "/FI", "PID eq 34567", "/FO", "CSV", "/NH"],
        ["taskkill", "/PID", "34567", "/T", "/F"],
    ]


def test_terminate_bluestacks_skips_non_windows(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")

    assert cli.terminate_bluestacks_process() == {"status": "skipped", "reason": "windows_only"}


def test_shutdown_is_skipped_when_gacha_safety_stops(monkeypatch):
    def unexpected_shutdown():
        raise AssertionError("BlueStacks must remain open after an aborted run")

    monkeypatch.setattr(cli, "terminate_bluestacks_process", unexpected_shutdown)
    result = {"status": "safety_stop", "reason": "screen_transition_timeout"}

    assert cli.shutdown_bluestacks_after_gacha(result) == {
        "status": "safety_stop",
        "reason": "screen_transition_timeout",
        "bluestacks_shutdown": {
            "status": "skipped",
            "reason": "gacha_not_completed",
            "gacha_status": "safety_stop",
        },
    }


def test_shutdown_runs_after_completed_gacha(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "terminate_bluestacks_process",
        lambda: calls.append(True) or {"status": "terminated", "pids": [12345]},
    )
    result = {"status": "matched"}

    assert cli.shutdown_bluestacks_after_gacha(result) == {
        "status": "matched",
        "bluestacks_shutdown": {"status": "terminated", "pids": [12345]},
    }
    assert calls == [True]


def test_shutdown_runs_after_attempt_budget_is_consumed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "terminate_bluestacks_process",
        lambda: calls.append(True) or {"status": "terminated", "pids": [12345]},
    )
    result = {"status": "max_attempts"}

    cli.shutdown_bluestacks_after_gacha(result)

    assert result["bluestacks_shutdown"]["status"] == "terminated"
    assert calls == [True]
