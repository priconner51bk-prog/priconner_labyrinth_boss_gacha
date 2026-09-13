"""現在画面と新規／復帰モードを判定する読み取り専用タスク。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from live_cli_utils import screen_error_message

from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def build_resume_result(screen: str | None, challenge_active: bool = False) -> dict[str, object]:
    # 画面ごとに、現在位置から安全に再開できる最初のタスクを返す。
    # 報酬・ボーナス系ダイアログは閉じる専用タスクへ渡し、出発や撤退を
    # 推測して押さない。
    resume_map = {
        "title": "launch_labyrinth",
        # 起動タスクの正常な遷移先。ここで停止すると自走ループが
        # 起動直後に途切れるため、迷宮起動へ安全に戻す。
        "quest_menu": "launch_labyrinth",
        "notice": "task_close_dialog",
        # ギルド選択画面は、ラビリンス出発直後の正規の再開地点。
        # 前回選択したギルド位置から再走査できるため、安全停止しない。
        "guild_select": "task_select_guild",
        "guild_confirm": "task_boss_gacha",
        "initial_char": "task_boss_gacha",
        "boss_map": "task_boss_gacha",
        "character_join": "task_boss_gacha",
        "withdraw_confirm": "withdraw",
        "bonus": "task_close",
        "item_reward": "task_close_dialog",
    }
    if screen in resume_map:
        return {"status": "ok", "screen_id": screen, "entry_mode": "resume", "resume_task": resume_map[screen]}
    if screen == "labyrinth_top":
        return {"status": "ok", "screen_id": screen, "entry_mode": "resume" if challenge_active else "new", "challenge_active": challenge_active, "resume_task": "task_user_assist" if challenge_active else "launch_labyrinth"}
    return {"status": "safety_stop", "reason": "current_screen_not_safe_for_resume", "screen_id": screen}

def main() -> int:
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args()
    cap=AdbScreenCapture(serial=a.serial)
    try:
        probe = load_template_probe_config(ROOT/"configs/live_screen_templates.json",cap)
        screen = probe.observe_screen()
    except Exception as exc:  # noqa: BLE001 - convert all probe failures to safety_stop
        print(json.dumps({"status":"safety_stop","reason":f"screen_observation_failed:{type(exc).__name__}","error":screen_error_message(exc, a.serial)},ensure_ascii=False)); return 2
    # Template matching is the only live screen-recognition path.  Unknown or
    # unregistered states must stop safely instead of being guessed from text.
    active = bool(probe.target_visible("挑戦中")) if screen == "labyrinth_top" else False
    if screen == "title":
        result = {"status": "ok", "screen_id": screen, "entry_mode": "new", "resume_task": "launch_labyrinth"}
        print(json.dumps(result, ensure_ascii=False)); return 0
    result = build_resume_result(screen, active)
    print(json.dumps(result,ensure_ascii=False)); return 0 if result["status"]=="ok" else 2
if __name__=="__main__": raise SystemExit(main())
