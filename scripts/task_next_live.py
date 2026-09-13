"""勝利・報酬画面の登録済み「次へ」テンプレートを確認して進める。"""

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
    parser = argparse.ArgumentParser(description="次へボタンを確認して1回だけ押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = probe.observe_screen()
    if screen not in {"battle_victory", "battle_reward"} or not probe.target_visible("勝利次へ" if screen == "battle_victory" else "報酬次へ"):
        print(json.dumps({"status": "safety_stop", "reason": "next_target_not_confirmed", "screen_id": screen}, ensure_ascii=False))
        return 2
    probe_path = ROOT / "data/observations/live/task_next_probe.png"

    def screen_token() -> str:
        capture.capture(probe_path)
        return hashlib.sha1(probe_path.read_bytes()).hexdigest()

    previous = screen_token()
    try:
        run_adb_coordinate_sequence(
            [(1105, 650)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=screen_token,
            require_screen_change=True, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_next",
        )
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "advanced", "screen_id": screen}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
