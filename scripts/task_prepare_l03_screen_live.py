"""L-03用に現在画面から安全にboss_mapまで遷移する。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.labyrinth_route import navigate_to_screen
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def build_screen_observer(capture, probe):
    """登録済みテンプレートだけで画面を判定する。"""

    def observe() -> str | None:
        screen = probe.observe_screen()
        return screen

    return observe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    observe_screen = build_screen_observer(capture, probe)
    # 難易度変更ダイアログは共通遷移表の座標タップでは扱わず、
    # ボタン色を判定する専用タスクへ委譲する。
    if observe_screen() == "difficulty_select":
        difficulty = subprocess.run(
            [sys.executable, str(ROOT / "scripts/task_difficulty_live.py"), "--serial", args.serial],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        try:
            difficulty_result = json.loads(difficulty.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            difficulty_result = {"status": "safety_stop", "reason": "difficulty_task_invalid_output"}
        after_difficulty = observe_screen()
        if difficulty_result.get("status") == "canceled":
            # 目的値が既に選択済みのためキャンセルした場合は、
            # キャンセル後の画面を再判定して通常遷移へ戻す。
            pass
        elif difficulty_result.get("status") != "completed":
            print(json.dumps({"status": "safety_stop", "reason": "difficulty_task_failed", "detail": difficulty_result}, ensure_ascii=False))
            return 2
        elif after_difficulty == "difficulty_select":
            print(json.dumps({"status": "safety_stop", "reason": "difficulty_screen_unchanged_after_action", "detail": difficulty_result}, ensure_ascii=False))
            return 2
    # Do not use the generic guild_select coordinate here: card ordering can
    # place another guild under that point.  Delegate to the dedicated
    # template-based task, which verifies the 美食殿 card before selecting it.
    if observe_screen() == "guild_select":
        guild = subprocess.run(
            [sys.executable, str(ROOT / "scripts/task_select_guild_live.py"), "--serial", args.serial],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        try:
            guild_result = json.loads(guild.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            guild_result = {"status": "safety_stop", "reason": "guild_task_invalid_output"}
        if guild_result.get("status") != "selected" or guild_result.get("guild") != "美食殿":
            print(json.dumps({"status": "safety_stop", "reason": "guild_selection_failed", "detail": guild_result}, ensure_ascii=False))
            return 2
    result = navigate_to_screen(
        "boss_map", serial=args.serial, screen_probe=observe_screen,
        max_steps=args.max_steps, debug_capture_dir=ROOT / "data/observations/live",
        debug_capture_prefix="task_prepare_l03",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
