"""タイトル画面を確認して1回だけ開始入力を送り、次画面を再判定する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def observe_title(capture, probe) -> str | None:
    return "title" if probe.observe_screen() == "title" else None


def observe_notice(capture) -> bool:
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="タイトル画面から安全に開始する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    before = observe_title(capture, probe)
    if before != "title":
        print(json.dumps({"status": "safety_stop", "reason": "title_screen_not_confirmed", "screen_id": before}, ensure_ascii=False))
        return 2
    try:
        run_adb_coordinate_sequence(
            [(640, 670)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=probe.observe_screen, require_screen_change=True,
            previous_screen_token=before,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_startup",
        )
        after = probe.observe_screen()
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"startup_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if after is None and observe_notice(capture):
        after = "notice"
    if after in {None, "title"}:
        print(json.dumps({"status": "safety_stop", "reason": "startup_transition_unconfirmed", "screen_after": after}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "completed", "screen_before": before, "screen_after": after}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
