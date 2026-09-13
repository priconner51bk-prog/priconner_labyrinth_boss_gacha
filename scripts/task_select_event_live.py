"""イベント発生画面の戦闘種別選択（task_種別、安全確認付き）。"""

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
    path = ROOT / "data/observations/live/event_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="イベントのEXTREMEを選択")
    parser.add_argument("--choice", choices=("extreme",), default="extreme")
    parser.add_argument("--guild-choice", choices=("booster", "buffer", "attacker", "breaker", "debuffer", "jammer"),
                        help="ギルド加入イベント専用の候補。難易度選択には使わない")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if probe.observe_screen() != "event_battle_choice" or not probe.target_visible("イベント通常選択"):
        print(json.dumps({"status": "safety_stop", "reason": "event_choices_not_confirmed"}, ensure_ascii=False))
        return 2
    # ``EXTREME`` is a user-confirmed rule for difficulty choices only.  A
    # guild-recruit screen has a different semantic choice (role/candidates),
    # so it must never inherit the right-card coordinate from battle events.
    if args.guild_choice is not None:
        print(json.dumps({
            "status": "safety_stop",
            "reason": "guild_choice_on_non_guild_event",
        }, ensure_ascii=False))
        return 2
    x = 470 if args.choice == "normal" else 830
    selected_choice = args.choice
    try:
        run_adb_coordinate_sequence(
            [(x, 590)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=lambda: _screen_token(capture),
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_event_choice", require_screen_change=True,
            previous_screen_token=_screen_token(capture),
        )
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "selected", "choice": selected_choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
