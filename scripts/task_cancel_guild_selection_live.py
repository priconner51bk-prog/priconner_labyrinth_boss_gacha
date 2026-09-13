"""ギルド選択確認をキャンセルし、ギルド一覧へ安全に戻る。"""
from __future__ import annotations

import argparse
import hashlib
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    cap = AdbScreenCapture(serial=args.serial)
    probe = ROOT / "data/observations/live/task_cancel_guild_selection_probe.png"
    screen_probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap)
    if screen_probe.observe_screen() != "guild_confirm" or not screen_probe.target_visible("ギルド選択キャンセル"):
        print(json.dumps({"status": "safety_stop", "reason": "guild_confirm_cancel_not_verified"}, ensure_ascii=False))
        return 2
    x, y = screen_probe.target_center("ギルド選択キャンセル")
    token = lambda: (cap.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence(
            [(x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=token,
            require_screen_change=True, previous_screen_token=token(),
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_cancel_guild_selection",
        )
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "cancelled", "screen": "guild_select", "x": x, "y": y}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
