"""移動先確認ダイアログの登録済みテンプレートを確認して押す。"""

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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="移動確認のOKボタンを押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if probe.observe_screen() != "move_confirm" or not probe.target_visible("移動先確認OK"):
        print(json.dumps({"status": "safety_stop", "reason": "move_confirm_template_not_confirmed"}, ensure_ascii=False))
        return 2
    x, y = probe.target_center("移動先確認OK")
    probe_path = ROOT / "data/observations/live/task_confirm_move_probe.png"
    token = lambda: (capture.capture(probe_path), hashlib.sha1(probe_path.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=args.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), screen_probe=token, require_screen_change=True, previous_screen_token=token(), debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_confirm_move")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "confirmed", "x": x, "y": y}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
