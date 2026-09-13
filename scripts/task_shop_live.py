"""ショップの購入・確認・終了を行う実機タスク（task_種別）。"""

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


def _screen_token(capture: AdbScreenCapture) -> str:
    path = ROOT / "data/observations/live/shop_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def tap(capture, point, serial, previous, prefix):
    run_adb_coordinate_sequence([point], serial=serial, healthcheck=True,
        timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: _screen_token(capture),
        require_screen_change=True, previous_screen_token=previous,
        debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=prefix)
    return _screen_token(capture)


def main() -> int:
    parser = argparse.ArgumentParser(description="ショップで候補を購入して閉じる")
    parser.add_argument("--choice", type=int, choices=(1, 2, 3))
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if probe.observe_screen() != "shop" or not any(probe.target_visible(label) for label in ("ショップ購入1", "ショップ購入2", "ショップ購入3")):
        print(json.dumps({"status": "safety_stop", "reason": "shop_purchase_button_not_confirmed"}, ensure_ascii=False))
        return 2
    if args.choice is None:
        # Choose the first visible affordable card; the deterministic shop
        # policy can supply an explicit index when candidate facts are known.
        choice = 1
    else:
        choice = args.choice
    x = (330, 720, 1110)[choice - 1]
    try:
        screen = _screen_token(capture)
        screen = tap(capture, (x, 350), args.serial, screen, "task_shop_purchase")
        screen = tap(capture, (785, 575), args.serial, screen, "task_shop_confirm")
        screen = tap(capture, (640, 495), args.serial, screen, "task_shop_complete")
        if not probe.target_visible("ショップ閉じる"):
            raise RuntimeError("shop_close_not_confirmed")
        tap(capture, (1090, 635), args.serial, screen, "task_shop_close")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"shop_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "completed", "choice": choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
