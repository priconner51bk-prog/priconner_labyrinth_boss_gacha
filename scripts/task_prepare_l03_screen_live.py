"""L-03用に現在画面から安全にboss_mapまで遷移する。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.labyrinth_route import navigate_to_screen
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config
from vision.ocr_service import OCRServiceAdapter


def build_screen_observer(capture, probe):
    """テンプレート判定を優先し、未知時だけ画面固有見出しで補完する。"""
    source = ROOT / "data/observations/live/task_prepare_l03_screen_fallback.png"

    def observe() -> str | None:
        screen = probe.observe_screen()
        # ギルド選択画面は難易度バッジを含むため、テンプレートだけでは
        # difficulty_selectに誤分類される。notice/difficulty_select時は
        # OCRで画面固有見出しを再確認する。
        # 固定テンプレートが古い場合、確認ダイアログを withdraw_confirm
        # と誤分類することがある。ギルド確認と初期キャラは常にOCRで
        # 再確認し、撤退操作を推測して実行しない。
        if screen is not None and screen not in {"notice", "difficulty_select", "withdraw_confirm"}:
            return screen
        try:
            capture.capture(source)
            lines = OCRServiceAdapter(language="jpn").recognize(str(source))
            text = "".join(line.text for line in lines if line.confidence >= 0.70)
        except Exception:
            return screen
        # ギルド選択は横並びカードの「選択する」ボタンが3個以上、
        # 画面下部に現れる。難易度バッジを含むためテンプレートが
        # difficulty_selectを返しても、この形状を優先する。
        card_buttons = [
            line for line in lines
            if line.confidence >= 0.70 and line.bbox
            and 500 <= (line.bbox[1] + line.bbox[3]) // 2 <= 620
            and line.bbox[2] - line.bbox[0] >= 50
        ]
        if screen in {None, "difficulty_select"} and len(card_buttons) >= 3:
            return "guild_select"
        if "キャラ選択" in text and ("選択したキャラ" in text or "仲間に勧誘" in text):
            return "initial_char"
        if "ギルド選択確認" in text:
            return "guild_confirm"
        if "難易度変更" in text and "難易度10" in text:
            return "difficulty_select"
        if "フォレスティエ" in text or "美食殿" in text:
            return "guild_select"
        if "黎明界ラビリンス" in text or ("出発" in text and "パスポート" in text):
            return "labyrinth_top"
        if "アイテム報酬" in text:
            return "item_reward"
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
    # place another guild under that point.  The dedicated task OCR-confirms
    # the 美食殿 label before selecting it.
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
