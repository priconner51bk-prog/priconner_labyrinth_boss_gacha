"""撤退確認ダイアログを安全条件付きで確定するタスク。"""
from __future__ import annotations

import argparse
import hashlib
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="撤退確認をテンプレート確認して確定")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    screen_probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    probe = ROOT / "data/observations/live/task_confirm_withdraw_probe.png"
    if screen_probe.observe_screen() != "withdraw_confirm" or not screen_probe.target_visible("撤退確認OK"):
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_confirmation_not_verified"}, ensure_ascii=False)); return 2
    x, y = screen_probe.target_center("撤退確認OK")
    token = lambda: (capture.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=args.serial, healthcheck=True,
                                    timing_policy=AdaptiveWaitPolicy(), screen_probe=token,
                                    require_screen_change=True, previous_screen_token=token(),
                                    debug_capture_dir=ROOT / "data/observations/live",
                                    debug_capture_prefix="task_confirm_withdraw")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    # A changed frame is not sufficient: the dialog can disappear while the
    # labyrinth top is still loading.  Do not let the next gacha inspect a
    # transient boss_map frame and tap the wrong control.
    deadline = time.monotonic() + 8.0
    top_ready = False
    while time.monotonic() < deadline:
        try:
            if screen_probe.observe_screen() == "labyrinth_top":
                top_ready = True
                break
        except Exception as exc:  # noqa: BLE001 - transient probe failure is nonfatal
            print(json.dumps({"nonfatal_probe_error": "withdraw_top", "error_type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        time.sleep(0.15)
    if not top_ready:
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_top_not_confirmed"}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "withdraw_confirmed", "x": x, "y": y}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
