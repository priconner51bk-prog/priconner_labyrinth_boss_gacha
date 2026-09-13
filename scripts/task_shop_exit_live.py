"""ショップ退出確認をテンプレートで検証して確定するタスク。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap)
    if probe.observe_screen() != "shop_exit_confirm" or not probe.target_visible("ショップ終了OK"):
        print(json.dumps({"status":"safety_stop","reason":"shop_exit_dialog_not_confirmed"}, ensure_ascii=False)); return 2
    previous = "shop_exit_confirm"
    try:
        run_adb_coordinate_sequence([(785,495)], serial=a.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
            require_screen_change=True, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_shop_exit")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status":"completed","screen_after":probe.observe_screen()}, ensure_ascii=False)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
