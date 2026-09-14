"""初期処理（task_種別）。初期キャラ画面からマップを開く。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    parser = argparse.ArgumentParser(description="初期キャラ画面でマップを開く")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = None
    for attempt in range(3):
        screen = probe.observe_screen()
        if screen is not None:
            break
        if attempt < 2:
            time.sleep(0.05)
    if screen == "boss_map":
        print(json.dumps({"status": "completed", "screen": screen, "initial_setup_done": True}, ensure_ascii=False))
        return 0
    if screen != "initial_char" or not probe.target_visible("マップ"):
        print(json.dumps({"status": "safety_stop", "reason": "initial_screen_or_map_target_not_confirmed", "screen": screen}, ensure_ascii=False))
        return 2
    try:
        run_adb_coordinate_sequence(
            [(90, 640)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.03, poll_seconds=0.03, timeout_seconds=0.8),
            screen_probe=probe.observe_screen, require_screen_change=True,
            previous_screen_token=screen,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_initial_setup_map",
        )
        after = probe.observe_screen()
        if after != "boss_map":
            raise RuntimeError(f"unexpected_screen_after_map:{after}")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"initial_setup_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "completed", "screen": after, "initial_setup_done": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
