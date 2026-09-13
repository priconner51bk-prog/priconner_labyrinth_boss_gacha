"""キャラ加入候補を指定カード位置で選択し、勧誘する。"""
from __future__ import annotations

import argparse
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
    p = argparse.ArgumentParser()
    p.add_argument("--indices", required=True, help="1-based card positions, e.g. 1,2,6")
    p.add_argument("--confirm-only", action="store_true", help="既存の3/3選択を維持し、勧誘だけ実行")
    p.add_argument("--serial", default="127.0.0.1:5555")
    args = p.parse_args()
    try:
        indices = tuple(int(x.strip()) for x in args.indices.split(",") if x.strip())
    except ValueError:
        print(json.dumps({"status": "safety_stop", "reason": "invalid_indices"}, ensure_ascii=False)); return 2
    if len(indices) != 3 or len(set(indices)) != 3 or any(i < 1 or i > 24 for i in indices):
        print(json.dumps({"status": "safety_stop", "reason": "indices_must_be_three_unique_positions_1_to_24"}, ensure_ascii=False)); return 2
    cap = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap)
    if probe.observe_screen() != "character_join" or not probe.target_visible("キャラ加入閉じる"):
        print(json.dumps({"status": "safety_stop", "reason": "character_join_screen_not_confirmed"}, ensure_ascii=False)); return 2
    # Eight cards per row, fixed card centers on the verified 1280x720 layout.
    points = []
    for index in indices:
        row, col = divmod(index - 1, 8)
        points.append((145 + col * 145, 250 + row * 145))
    try:
        if not args.confirm_only:
            for point in points:
                run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                    timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
                    require_screen_change=False, debug_capture_dir=ROOT / "data/observations/live",
                    debug_capture_prefix="task_character_join_select")
        run_adb_coordinate_sequence([(1090, 635)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
            require_screen_change=True, previous_screen_token="character_join",
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_character_join_invite")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"join_failed:{type(exc).__name__}", "indices": indices}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "selected", "indices": indices}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
