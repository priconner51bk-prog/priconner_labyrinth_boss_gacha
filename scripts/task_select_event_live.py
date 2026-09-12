"""イベント発生画面の戦闘種別選択（task_種別、安全確認付き）。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr_service import OCRServiceAdapter


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
    # Dynamic event artwork is not stable enough for a template screen ID;
    # identify the scene from its two selection buttons and event text below.
    frame = ROOT / "data/observations/live/event_battle_choice.png"
    capture.capture(frame)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(frame))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    text = "".join(line.text for line in lines if line.confidence >= 0.80)
    battle_choice = "NORMAL" in text and "EXTREME" in text
    # Recruit events vary the role pair (tank/healer, booster/buffer, etc.).
    # The two card descriptions consistently include ``ロール``.
    # Guild-recruit events may OCR the two blue buttons inconsistently, but
    # the two role headings are stable and uniquely identify this screen.
    guild_choice = (
        text.count("ロール") >= 2
        or ("タンク" in text and "ヒーラー" in text and "選" in text)
        or ("アタッカー" in text and "ブレイカー" in text)
        or ("デバッファー" in text and "ジャマー" in text)
    )
    selection_count = sum("選択する" in line.text for line in lines if line.confidence >= 0.80)
    janken_choice = selection_count >= 2 and not battle_choice and not guild_choice
    if selection_count < 2 or not (battle_choice or guild_choice or janken_choice):
        print(json.dumps({"status": "safety_stop", "reason": "event_choices_not_confirmed"}, ensure_ascii=False))
        return 2
    # ``EXTREME`` is a user-confirmed rule for difficulty choices only.  A
    # guild-recruit screen has a different semantic choice (role/candidates),
    # so it must never inherit the right-card coordinate from battle events.
    if guild_choice:
        if args.guild_choice is not None:
            x = 470 if args.guild_choice in {"booster", "attacker", "debuffer"} else 830
            selected_choice = args.guild_choice
        else:
            print(json.dumps({
                "status": "waiting_input",
                "reason": "guild_recruit_choice_requires_context",
                "required_input": "選択する加入候補または編成方針",
            }, ensure_ascii=False))
            return 0
    elif args.guild_choice is not None:
        print(json.dumps({
            "status": "safety_stop",
            "reason": "guild_choice_on_non_guild_event",
        }, ensure_ascii=False))
        return 2
    else:
        # The remaining supported variant is a NORMAL/EXTREME battle choice.
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
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "selected", "choice": selected_choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
