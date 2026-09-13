"""エリアボス戦の1〜3編成確認・開始（task_種別）。"""

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

PARTY_POINTS = ((130, 120), (300, 120), (450, 120))


def _screen_token(capture: AdbScreenCapture) -> str:
    path = ROOT / "data/observations/live/area_boss_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="エリアボスの1〜3編成を確認して開始")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--formations", type=int, choices=(1, 2, 3), default=3,
                        help="使用する編成数。未指定時は安全側に3（各5キャラ）")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = probe.observe_screen()
    # The first entry is a boss tile with a 挑戦する button; open the party
    # screen before selecting the requested 1–3 formations.
    if screen == "battle_tile_normal" and probe.target_visible("挑戦する"):
        try:
            previous = _screen_token(capture)
            run_adb_coordinate_sequence([(1135, 605)], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: _screen_token(capture),
                require_screen_change=True, previous_screen_token=previous,
                debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_area_boss_challenge")
            # Transition animation can briefly leave the boss tile visible;
            # poll the party header instead of treating that transient frame
            # as a failure.
            for _ in range(12):
                if probe.observe_screen() in {"battle_party", "battle_party_ready"}:
                    break
                time.sleep(0.25)
        except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
            print(json.dumps({"status": "safety_stop", "reason": f"area_boss_challenge_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
    if probe.observe_screen() not in {"battle_party", "battle_party_ready"} or not probe.target_visible("バトル開始"):
        print(json.dumps({"status": "safety_stop", "reason": "area_boss_party_screen_not_confirmed"}, ensure_ascii=False))
        return 2
    try:
        for index, point in enumerate(PARTY_POINTS[:args.formations], 1):
            run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: _screen_token(capture),
                require_screen_change=False, previous_screen_token=_screen_token(capture),
                debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=f"task_area_boss_party_{index}")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"area_boss_start_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": "user_assist_required",
        "reason": "area_boss_ex_equipment_manual_required",
        "formations": args.formations,
        "members_per_formation": 5,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
