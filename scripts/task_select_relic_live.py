"""迷宮遺物選択（登録テンプレート確認付き）。"""

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
    path = ROOT / "data/observations/live/relic_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="遺物候補をテンプレート確認して選択")
    parser.add_argument("--choice", type=int, choices=(1, 2, 3))
    parser.add_argument("--auto", action="store_true", help="廃止済み。手動choiceを指定する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    if (args.choice is None) == (not args.auto):
        parser.error("choiceまたはautoのどちらか一方が必要です")
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if probe.observe_screen() != "relic_choice" or not probe.target_visible("遺物選択"):
        print(json.dumps({"status": "safety_stop", "reason": "relic_buttons_not_confirmed"}, ensure_ascii=False))
        return 2
    if args.auto:
        print(json.dumps({"status": "user_assist_required", "reason": "auto_choice_requires_manual_selection_without_ocr"}, ensure_ascii=False))
        return 0
    else:
        choice = args.choice
    x = (270, 640, 1010)[choice - 1]
    try:
        run_adb_coordinate_sequence([(x, 620)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: _screen_token(capture),
            require_screen_change=True, previous_screen_token=_screen_token(capture),
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_relic_select")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "choice": choice}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "selected", "choice": choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
