"""ボスガチャを再抽選せず、現在のボス詳細を閉じて出発準備へ戻す。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence, navigate_to_screen
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    parser = argparse.ArgumentParser(description="現在のボスガチャを再抽選せずにスキップ")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    live_dir = ROOT / "data" / "observations" / "live"
    source = live_dir / "task_skip_boss_gacha_source.png"
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs" / "live_screen_templates.json", capture)
    screen = probe.observe_screen()
    if screen is None:
        detected = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "determine_current_state_live.py"), "--serial", args.serial],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        try:
            payload = json.loads(detected.stdout.strip().splitlines()[-1])
            screen = payload.get("screen", {}).get("screen_id")
        except (json.JSONDecodeError, IndexError, AttributeError):
            screen = None
    if screen not in {"boss_detail", "boss_map"}:
        print(json.dumps({"status": "safety_stop", "reason": "boss_detail_not_confirmed", "screen": screen}, ensure_ascii=False))
        return 2
    if screen == "boss_detail":
        capture.capture(source)
        before = hashlib.sha1(source.read_bytes()).hexdigest()
        try:
            run_adb_coordinate_sequence(
                [(640, 640)], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: hashlib.sha1(source.read_bytes()).hexdigest(),
                previous_screen_token=before, require_screen_change=True,
                debug_capture_dir=live_dir, debug_capture_prefix="task_skip_boss_gacha",
            )
            after = probe.observe_screen()
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"close_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
        if after != "boss_map":
            print(json.dumps({"status": "safety_stop", "reason": "boss_map_not_confirmed_after_skip", "screen": after}, ensure_ascii=False))
            return 2
    # boss_map is already the post-gacha state; use the dedicated guarded
    # return flow because generic navigation has no safe boss_map tap target.
    if screen == "boss_map":
        returned = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_return_initial_char_live.py"), "--serial", args.serial],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        try:
            navigation = json.loads(returned.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            navigation = {"status": "safety_stop", "reason": "return_result_invalid"}
    else:
        navigation = navigate_to_screen(
            "initial_char", serial=args.serial, screen_probe=probe.observe_screen,
            debug_capture_dir=live_dir, debug_capture_prefix="task_skip_boss_gacha_return",
        )
    if navigation.get("status") != "ready" or navigation.get("screen_id") != "initial_char":
        # The navigation helper may miss the final frame even though the
        # guarded return already reached the active labyrinth entry screen.
        # Reconcile once with the shared checker before reporting failure.
        try:
            checked = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "task_check_current_screen_live.py"), "--serial", args.serial],
                cwd=ROOT, capture_output=True, text=True, check=False, timeout=10,
            )
            payload = json.loads(checked.stdout.strip().splitlines()[-1])
            if payload.get("status") == "ok" and payload.get("screen_id") in {"initial_char", "labyrinth_top"}:
                print(json.dumps({"status": "skipped", "boss_result": "unconfirmed",
                                  "screen_after": payload.get("screen_id"), "reconciled": True}, ensure_ascii=False))
                return 0
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, AttributeError):
            pass
        print(json.dumps({"status": "safety_stop", "reason": "initial_char_not_confirmed", "navigation": navigation}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "skipped", "boss_result": "unconfirmed", "screen_after": "initial_char"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
