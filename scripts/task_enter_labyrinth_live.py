"""アプリ再起動からラビリンス入口までを安全に連結する実機タスク。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, serial: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--serial", serial],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
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


def _wait_for_startup_state(serial: str, timeout: float = 45.0) -> dict[str, object]:
    """遷移中の暗転フレームを越えてから次の操作へ進む。"""
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {"screen_id": None}
    while time.monotonic() < deadline:
        last = _run("task_check_current_screen_live.py", serial)
        if last.get("screen_id") in {"notice", "home", "quest_menu", "labyrinth_top"}:
            return last
        time.sleep(1.0)
    return last


def main() -> int:
    parser = argparse.ArgumentParser(description="アプリ再起動からラビリンス入口まで誘導")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--package", default="jp.co.cygames.princessconnectredive")
    args = parser.parse_args()

    try:
        subprocess.run(
            ["adb", "-s", args.serial, "shell", "am", "force-stop", args.package],
            check=True, capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["adb", "-s", args.serial, "shell", "monkey", "-p", args.package, "1"],
            check=True, capture_output=True, text=True, timeout=15,
        )
        # ADB reports the process before the first stable title frame exists.
        time.sleep(15)
    except (OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "safety_stop", "reason": "app_restart_failed", "error": type(exc).__name__}, ensure_ascii=False))
        return 2

    steps = []
    observed = _run("task_check_current_screen_live.py", args.serial)
    steps.append(observed)
    allowed_startup = {"title", "loading", "startup_splash", "notice", "startup_error"}
    if observed.get("screen_id") not in allowed_startup:
        print(json.dumps({"status": "safety_stop", "failed_step": "startup_state_guard", "reason": "resumed_existing_game_state", "steps": steps}, ensure_ascii=False))
        return 2
    settled = _wait_for_startup_state(args.serial)
    steps.append(settled)
    if settled.get("screen_id") not in {"notice", "home", "quest_menu", "labyrinth_top"}:
        print(json.dumps({"status": "safety_stop", "failed_step": "startup_settle_guard", "steps": steps}, ensure_ascii=False))
        return 2
    for script in ("task_startup_live.py", "task_close_live.py", "task_launch_labyrinth_live.py"):
        step = _run(script, args.serial)
        steps.append(step)
        if int(step.get("returncode", 2)) != 0:
            print(json.dumps({"status": "safety_stop", "failed_step": script, "steps": steps}, ensure_ascii=False))
            return 2
    print(json.dumps({"status": "completed", "screen_after": "labyrinth_top", "steps": steps}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
