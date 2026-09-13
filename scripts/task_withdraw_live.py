"""ラビリンス内の撤退だけを実行する安全タスク。"""
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap)
    try:
        current = probe.observe_screen()
    except Exception as exc:  # noqa: BLE001 - convert failures to safety_stop
        print(json.dumps({"status":"safety_stop","reason":f"screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    if current == "withdraw_confirm":
        if not probe.target_visible("撤退確認OK"):
            print(json.dumps({"status":"safety_stop","reason":"withdraw_confirm_target_not_confirmed"}, ensure_ascii=False)); return 2
        try:
            run_adb_coordinate_sequence([(787, 495)], serial=a.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen, require_screen_change=False, debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_withdraw_confirm")
        except Exception as exc:  # noqa: BLE001 - convert failures to safety_stop
            print(json.dumps({"status":"safety_stop","reason":f"withdraw_confirm_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        print(json.dumps({"status":"withdraw_confirmed","x":787,"y":495}, ensure_ascii=False)); return 0
    if current not in {"initial_char", "boss_map"}:
        print(json.dumps({"status":"safety_stop","reason":f"unexpected_screen:{current!r}"}, ensure_ascii=False)); return 2
    if current == "initial_char":
        if not probe.target_visible("マップ"):
            print(json.dumps({"status":"safety_stop","reason":"map_target_not_confirmed"}, ensure_ascii=False)); return 2
        try:
            run_adb_coordinate_sequence([(90, 640)], serial=a.serial, healthcheck=True,
                                        timing_policy=AdaptiveWaitPolicy(),
                                        screen_probe=probe.observe_screen,
                                        require_screen_change=True,
                                        previous_screen_token="initial_char",
                                        debug_capture_dir=ROOT / "data/observations/live",
                                        debug_capture_prefix="task_withdraw_open_map")
        except Exception as exc:  # noqa: BLE001 - convert failures to safety_stop
            print(json.dumps({"status":"safety_stop","reason":f"map_open_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        try:
            if probe.observe_screen() != "boss_map":
                print(json.dumps({"status":"safety_stop","reason":"map_screen_not_confirmed"}, ensure_ascii=False)); return 2
        except Exception as exc:  # noqa: BLE001 - convert failures to safety_stop
            print(json.dumps({"status":"safety_stop","reason":f"map_screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    if not probe.target_visible("撤退する"):
        print(json.dumps({"status":"safety_stop","reason":"withdraw_target_not_confirmed"}, ensure_ascii=False)); return 2
    try:
        run_adb_coordinate_sequence([(910,650)], serial=a.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), require_screen_change=False, debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_withdraw")
    except Exception as exc:  # noqa: BLE001 - convert failures to safety_stop
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status":"withdraw_selected","x":910,"y":650}, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
