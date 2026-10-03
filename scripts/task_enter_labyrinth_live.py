"""アプリ再起動からラビリンス入口までを安全に連結する実機タスク。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# JSON reports can include OCR-derived text such as U+FFFD. Keep the standalone
# Windows console from failing to serialize those characters with cp932.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from scripts.process_utils import run_without_console
except ModuleNotFoundError:  # Direct `python scripts/<task>.py` invocation.
    from process_utils import run_without_console

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCK_DIR = ROOT / "data/observations/live"
MAX_COMMUNICATION_ATTEMPTS = 3


def _device_lock(_serial: str) -> Path:
    # ADB's server is host-global, so different serial aliases must not allow
    # two live tasks to mutate its connections or the same emulator in parallel.
    return LOCK_DIR / ".device_global.lock"


def _acquire_device_lock(serial: str) -> Path | None:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = _device_lock(serial)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        try:
            owner = int(path.read_text(encoding="ascii").strip())
            os.kill(owner, 0)
        except (FileNotFoundError, ValueError, OSError):
            path.unlink(missing_ok=True)
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
                stream.write(str(os.getpid()))
        else:
            return None
    return path


def _run(script: str, serial: str, *, timeout: float = 60.0,
         extra_args: tuple[str, ...] = ()) -> dict[str, object]:
    try:
        command = [sys.executable, str(ROOT / "scripts" / script), "--serial", serial, *extra_args]
        result = run_without_console(
            command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"script": script, "returncode": 124, "status": "safety_stop", "reason": "step_timeout"}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    payload: dict[str, object] = {"script": script, "returncode": result.returncode}
    if lines:
        try:
            value = json.loads(lines[-1])
            if isinstance(value, dict):
                payload.update(value)
        except json.JSONDecodeError:
            payload["stdout"] = lines[-1]
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()[-1000:]
    return payload


def _wait_for_navigation_state(serial: str, package: str, timeout: float = 180.0) -> dict[str, object]:
    """起動画面や暗転を待ち、登録済みの遷移先だけを返す。"""
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {"screen_id": None}
    while time.monotonic() < deadline:
        last = _run("task_check_current_screen_live.py", serial, timeout=35.0)
        if last.get("screen_id") in {"title", "notice", "startup_error", "home", "quest_menu", "labyrinth_top"}:
            return last
        time.sleep(1.0)
    last["wait_timed_out"] = True
    last["wait_timeout_seconds"] = timeout
    return last


def _refresh_navigation_entry(serial: str, package: str, steps: list[dict[str, object]]):
    """Re-read the screen before quest navigation and dismiss a late notice."""
    current = _run("task_check_current_screen_live.py", serial)
    steps.append(current)
    if current.get("status") != "ok":
        return None, {"failed_step": "navigation_entry_screen_check",
                      "reason": current.get("reason", "navigation_start_screen_not_confirmed"),
                      "screen_id": current.get("screen_id")}
    screen = current.get("screen_id")
    if screen == "notice":
        closed = _run("task_close_live.py", serial)
        steps.append(closed)
        if closed.get("status") != "closed":
            return None, {"failed_step": "task_close_live.py",
                          "reason": closed.get("reason", "startup_notice_close_unconfirmed"),
                          "screen_id": "notice"}
        settled = _wait_for_navigation_state(serial, package)
        steps.append(settled)
        if settled.get("status") != "ok" or settled.get("screen_id") not in {"home", "quest_menu", "labyrinth_top"}:
            return None, {"failed_step": "post_notice_navigation",
                          "reason": settled.get("reason", "navigation_start_screen_not_confirmed"),
                          "screen_id": settled.get("screen_id")}
        screen = settled["screen_id"]
    if screen == "network_loading":
        settled = _wait_for_navigation_state(serial, package)
        steps.append(settled)
        screen = settled.get("screen_id")
        if settled.get("wait_timed_out") or screen == "network_loading":
            return None, {"failed_step": "network_connection_wait",
                          "reason": "startup_transition_timeout", "screen_id": screen}
        if screen == "startup_error":
            return None, {"failed_step": "network_connection_wait",
                          "reason": "startup_network_timeout", "screen_id": screen}
    if screen not in {"home", "quest_menu", "labyrinth_top"}:
        return None, {"failed_step": "navigation_entry_screen_check",
                      "reason": "navigation_start_screen_not_confirmed", "screen_id": screen}
    return screen, None


def _is_adb_communication_failure(exc: BaseException) -> bool:
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    detail = " ".join(str(value) for value in (
        exc,
        getattr(exc, "output", ""),
        getattr(exc, "stderr", ""),
    )).casefold()
    return any(marker in detail for marker in (
        "device offline", "device not found", "no devices/emulators found",
        "failed to connect", "cannot connect", "connection refused",
        "transport error", "protocol fault", "timed out", "timeout",
    ))


def _run_navigation_attempt(args, attempt: int) -> tuple[dict[str, object], bool]:
    """Run one complete launch-to-labyrinth pass; retry only confirmed game timeouts."""
    steps: list[dict[str, object]] = []
    try:
        run_without_console(
            ["adb", "-s", args.serial, "shell", "am", "force-stop", args.package],
            check=True, capture_output=True, text=True, timeout=10,
        )
        run_without_console(
            ["adb", "-s", args.serial, "shell", "monkey", "-p", args.package,
             "-c", "android.intent.category.LAUNCHER", "1"],
            check=True, capture_output=True, text=True, timeout=15,
        )
        # ADB reports the process before the first stable title frame exists.
        time.sleep(3)
    except (OSError, subprocess.SubprocessError) as exc:
        retryable = _is_adb_communication_failure(exc)
        reason = "adb_communication_error" if retryable else "app_restart_failed"
        return ({"status": "safety_stop", "reason": reason,
                 "error": type(exc).__name__, "detail": str(exc)[:240],
                 "attempt": attempt, "steps": steps}, retryable)

    observed = _run("task_check_current_screen_live.py", args.serial)
    steps.append(observed)
    screen = observed.get("screen_id")
    if screen in {"startup_splash", "loading", "network_loading"} or screen is None:
        settled = _wait_for_navigation_state(args.serial, args.package, timeout=args.timeout)
        steps.append(settled)
        screen = settled.get("screen_id")
        if settled.get("wait_timed_out") or screen in {"startup_splash", "loading"}:
            return ({"status": "safety_stop", "failed_step": "startup_state_wait",
                     "reason": "startup_transition_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)

    allowed = {"title", "startup_error", "notice", "home", "quest_menu", "labyrinth_top"}
    if screen not in allowed:
        return ({"status": "safety_stop", "failed_step": "startup_state_guard",
                 "reason": "screen_not_registered_for_navigation", "screen_id": screen,
                 "attempt": attempt, "steps": steps}, False)

    if screen in {"title", "startup_error"}:
        # The outer pass owns the shared three-attempt budget.
        started = _run("task_startup_live.py", args.serial, timeout=180.0,
                       extra_args=("--max-attempts", "1"))
        steps.append(started)
        if int(started.get("returncode", 2)) != 0 or started.get("status") != "completed":
            retryable = started.get("reason") in {
                "startup_timeout_retries_exhausted", "startup_transition_timeout", "step_timeout",
            }
            return ({"status": "safety_stop", "failed_step": "task_startup_live.py",
                     "reason": started.get("reason"), "attempt": attempt, "steps": steps}, retryable)
        screen = started.get("screen_after")
        if screen not in {"notice", "home", "quest_menu", "labyrinth_top"}:
            settled = _wait_for_navigation_state(args.serial, args.package, timeout=args.timeout)
            steps.append(settled)
            screen = settled.get("screen_id")
            if settled.get("wait_timed_out"):
                return ({"status": "safety_stop", "failed_step": "game_startup",
                         "reason": "startup_transition_timeout", "screen_id": screen,
                         "attempt": attempt, "steps": steps}, True)
            if screen == "startup_error":
                return ({"status": "safety_stop", "failed_step": "game_startup",
                         "reason": "startup_network_timeout", "screen_id": screen,
                         "attempt": attempt, "steps": steps}, True)
            if screen in {"startup_splash", "loading"}:
                return ({"status": "safety_stop", "failed_step": "game_startup",
                         "reason": "startup_transition_timeout", "screen_id": screen,
                         "attempt": attempt, "steps": steps}, True)

    if screen == "notice":
        closed = _run("task_close_live.py", args.serial)
        steps.append(closed)
        if int(closed.get("returncode", 2)) != 0 or closed.get("status") != "closed":
            return ({"status": "safety_stop", "failed_step": "task_close_live.py",
                     "reason": closed.get("reason"), "attempt": attempt, "steps": steps}, False)
        settled = _wait_for_navigation_state(args.serial, args.package, timeout=args.timeout)
        steps.append(settled)
        screen = settled.get("screen_id")
        if settled.get("wait_timed_out"):
            return ({"status": "safety_stop", "failed_step": "post_notice_navigation",
                     "reason": "startup_transition_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)
        if screen == "startup_error":
            return ({"status": "safety_stop", "failed_step": "post_notice_navigation",
                     "reason": "startup_network_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)
        if screen in {"startup_splash", "loading"}:
            return ({"status": "safety_stop", "failed_step": "post_notice_navigation",
                     "reason": "startup_transition_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)

    if screen == "network_loading":
        settled = _wait_for_navigation_state(args.serial, args.package, timeout=args.timeout)
        steps.append(settled)
        screen = settled.get("screen_id")
        if settled.get("wait_timed_out") or screen == "network_loading":
            return ({"status": "safety_stop", "failed_step": "network_connection_wait",
                     "reason": "startup_transition_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)
        if screen == "startup_error":
            return ({"status": "safety_stop", "failed_step": "network_connection_wait",
                     "reason": "startup_network_timeout", "screen_id": screen,
                     "attempt": attempt, "steps": steps}, True)

    if screen in {"home", "quest_menu"}:
        screen, entry_error = _refresh_navigation_entry(args.serial, args.package, steps)
        if entry_error:
            retryable = entry_error.get("reason") in {
                "startup_network_timeout", "startup_transition_timeout", "step_timeout",
            }
            return ({"status": "safety_stop", **entry_error,
                     "attempt": attempt, "steps": steps}, retryable)
    if screen in {"home", "quest_menu"}:
        launched = _run("task_launch_labyrinth_live.py", args.serial, timeout=args.timeout + 180)
        steps.append(launched)
        if int(launched.get("returncode", 2)) != 0 or launched.get("status") != "completed":
            retryable = launched.get("reason") in {
                "startup_network_timeout", "startup_transition_timeout", "step_timeout",
            }
            return ({"status": "safety_stop", "failed_step": "task_launch_labyrinth_live.py",
                     "reason": launched.get("reason"), "screen_id": launched.get("screen_after"),
                     "attempt": attempt, "steps": steps}, retryable)

    verified = _run("task_check_current_screen_live.py", args.serial)
    steps.append(verified)
    if int(verified.get("returncode", 2)) != 0 or verified.get("screen_id") != "labyrinth_top":
        return ({"status": "safety_stop", "failed_step": "final_screen_verification",
                 "screen_id": verified.get("screen_id"), "attempt": attempt, "steps": steps}, False)
    return ({"status": "completed", "screen_after": "labyrinth_top",
             "attempt": attempt, "steps": steps}, False)


def _run_main() -> int:
    from scripts.adb_runtime import (
        pin_adb_environment,
        resolve_adb_path,
        resolve_adb_serial,
    )

    parser = argparse.ArgumentParser(description="アプリ再起動からラビリンス入口まで誘導")
    parser.add_argument("--serial", default=resolve_adb_serial())
    parser.add_argument("--adb", help="この実行全体で使うADB実行ファイル")
    parser.add_argument("--package", default="jp.co.cygames.princessconnectredive")
    parser.add_argument("--timeout", type=float, default=180.0, help="起動画面・遷移先を待つ秒数")
    parser.add_argument("--max-attempts", type=int, default=MAX_COMMUNICATION_ATTEMPTS,
                        help=f"通信タイムアウト時の経路全体の試行上限（1〜{MAX_COMMUNICATION_ATTEMPTS}）")
    parser.add_argument("--lock-held", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not 1 <= args.max_attempts <= MAX_COMMUNICATION_ATTEMPTS:
        parser.error(f"--max-attempts must be between 1 and {MAX_COMMUNICATION_ATTEMPTS}")
    try:
        adb_path = resolve_adb_path(args.adb)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": str(exc), "serial": args.serial}, ensure_ascii=False))
        return 2
    if not adb_path:
        print(json.dumps({"status": "safety_stop", "reason": "adb_not_found", "serial": args.serial}, ensure_ascii=False))
        return 2
    pin_adb_environment(adb_path)

    attempts: list[dict[str, object]] = []
    for attempt in range(1, args.max_attempts + 1):
        result, retryable = _run_navigation_attempt(args, attempt)
        attempts.append(result)
        if result.get("status") == "completed":
            report = dict(result)
            report["attempts"] = list(attempts)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if not retryable:
            report = dict(result)
            report["attempts"] = list(attempts)
            print(json.dumps(report, ensure_ascii=False))
            return 2
    last = attempts[-1]
    print(json.dumps({"status": "safety_stop", "reason": "communication_retries_exhausted",
                      "attempt_count": args.max_attempts, "max_attempts": args.max_attempts,
                      "last_reason": last.get("reason"), "attempts": attempts}, ensure_ascii=False))
    return 2


def main() -> int:
    from scripts.adb_runtime import (
        resolve_adb_serial,
        restore_adb_environment,
        snapshot_adb_environment,
    )

    serial = resolve_adb_serial()
    for index, value in enumerate(sys.argv[:-1]):
        if value == "--serial":
            serial = sys.argv[index + 1]
            break
        if value.startswith("--serial="):
            serial = value.partition("=")[2]
            break
    environment_snapshot = snapshot_adb_environment()
    if "--lock-held" in sys.argv:
        try:
            return _run_main()
        finally:
            restore_adb_environment(environment_snapshot)
    lock = _acquire_device_lock(serial)
    if lock is None:
        print(json.dumps({"status": "safety_stop", "reason": "device_busy", "serial": serial}, ensure_ascii=False))
        return 2
    try:
        return _run_main()
    finally:
        restore_adb_environment(environment_snapshot)
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
