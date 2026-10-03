"""The live route retries only confirmed communication timeouts, at most three times."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import task_enter_labyrinth_live as route


def test_direct_script_entrypoint_loads_shared_adb_runtime():
    script = Path(route.__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(script), "--help"], cwd=script.parents[1],
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
    )

    assert result.returncode == 0
    assert "--adb" in result.stdout


def test_navigation_entry_refresh_closes_late_startup_notice(monkeypatch):
    commands = []
    results = iter([
        {"status": "ok", "screen_id": "notice"},
        {"status": "closed"},
    ])

    def fake_run(script, serial, **_kwargs):
        commands.append((script, serial))
        return next(results)

    monkeypatch.setattr(route, "_run", fake_run)
    monkeypatch.setattr(route, "_wait_for_navigation_state",
                        lambda *_args, **_kwargs: {"status": "ok", "screen_id": "home"})
    steps = []

    screen, error = route._refresh_navigation_entry("127.0.0.1:5555", "game", steps)

    assert screen == "home"
    assert error is None
    assert [command[0] for command in commands] == [
        "task_check_current_screen_live.py", "task_close_live.py",
    ]


def test_navigation_wait_does_not_treat_connecting_as_ready(monkeypatch):
    observed = iter([
        {"status": "ok", "screen_id": "network_loading"},
        {"status": "ok", "screen_id": "home"},
    ])
    calls = []
    monkeypatch.setattr(route, "_run", lambda *_args, **_kwargs: (calls.append(True), next(observed))[1])
    monkeypatch.setattr(route.time, "sleep", lambda _seconds: None)

    result = route._wait_for_navigation_state("serial", "game", timeout=2)

    assert result["screen_id"] == "home"
    assert len(calls) == 2


def test_communication_timeout_stops_after_three_route_attempts(monkeypatch, capsys):
    attempts = [
        ({"status": "safety_stop", "reason": "startup_transition_timeout"}, True),
        ({"status": "safety_stop", "reason": "startup_network_timeout"}, True),
        ({"status": "safety_stop", "reason": "startup_timeout_retries_exhausted"}, True),
    ]
    run_attempt = iter(attempts)
    monkeypatch.setattr(route, "_run_navigation_attempt", lambda _args, _attempt: next(run_attempt))
    monkeypatch.setattr("sys.argv", ["task_enter_labyrinth_live.py", "--timeout", "1"])

    assert route.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "communication_retries_exhausted"
    assert payload["attempt_count"] == route.MAX_COMMUNICATION_ATTEMPTS == 3
    assert len(payload["attempts"]) == 3


def test_non_communication_failure_stops_without_retry(monkeypatch, capsys):
    calls = []

    def fail_fast(_args, attempt):
        calls.append(attempt)
        return {"status": "safety_stop", "reason": "screen_not_registered"}, False

    monkeypatch.setattr(route, "_run_navigation_attempt", fail_fast)
    monkeypatch.setattr("sys.argv", ["task_enter_labyrinth_live.py"])

    assert route.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "screen_not_registered"
    assert calls == [1]


def test_attempt_limit_can_be_lowered_but_not_raised(monkeypatch, capsys):
    monkeypatch.setattr(
        route, "_run_navigation_attempt",
        lambda _args, attempt: ({"status": "safety_stop", "reason": "startup_transition_timeout",
                                 "attempt": attempt}, True),
    )
    monkeypatch.setattr("sys.argv", ["task_enter_labyrinth_live.py", "--max-attempts", "1"])

    assert route.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "communication_retries_exhausted"
    assert payload["attempt_count"] == payload["max_attempts"] == 1


def test_adb_transport_timeouts_are_retryable_with_three_attempt_limit(monkeypatch, capsys):
    attempts = []

    def fail_at_adb(_args, attempt):
        attempts.append(attempt)
        return {"status": "safety_stop", "reason": "adb_communication_error", "attempt": attempt}, True

    monkeypatch.setattr(route, "_run_navigation_attempt", fail_at_adb)
    monkeypatch.setattr("sys.argv", ["task_enter_labyrinth_live.py"])

    assert route.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "communication_retries_exhausted"
    assert payload["attempt_count"] == 3
    assert attempts == [1, 2, 3]


def test_adb_command_timeout_is_classified_as_retryable(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise route.subprocess.TimeoutExpired(cmd=["adb"], timeout=10)

    monkeypatch.setattr(route, "run_without_console", timeout)

    result, retryable = route._run_navigation_attempt(
        SimpleNamespace(serial="127.0.0.1:5555", package="game", timeout=1), 1
    )

    assert result["reason"] == "adb_communication_error"
    assert retryable is True


def test_success_after_retry_reports_attempt_history(monkeypatch, capsys):
    results = iter([
        ({"status": "safety_stop", "reason": "startup_transition_timeout"}, True),
        ({"status": "completed", "screen_after": "labyrinth_top"}, False),
    ])
    monkeypatch.setattr(route, "_run_navigation_attempt", lambda _args, _attempt: next(results))
    monkeypatch.setattr("sys.argv", ["task_enter_labyrinth_live.py"])

    assert route.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["screen_after"] == "labyrinth_top"
    assert payload["attempts"] == [
        {"status": "safety_stop", "reason": "startup_transition_timeout"},
        {"status": "completed", "screen_after": "labyrinth_top"},
    ]
