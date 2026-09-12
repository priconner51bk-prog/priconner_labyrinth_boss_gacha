"""現在画面と新規／復帰モードを判定する読み取り専用タスク。"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config
from vision.ocr_service import OCRServiceAdapter
from vision.title_ocr import centered_title_text
from live_cli_utils import screen_error_message


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
        "guild_confirm": "task_prepare_l03_screen",
        "initial_char": "select_initial_characters",
        "boss_map": "task_boss_name",
        "battle_tile_normal": "start_battle",
        "move_confirm": "confirm_move",
        "battle_party": "prepare_battle",
        "battle_party_ready": "start_battle",
        "priority_status": "set_priority_status",
        "ex_auto_dialog": "set_priority_status",
        "ex_equipment": "prepare_ex_equipment",
        "ex_equipment_conflict": "resolve_ex_equipment_conflict",
        "character_join": "select_character_join",
        "battle_victory": "wait_battle_result",
        "battle_reward": "select_reward",
        "character_bonus": "task_user_assist",
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
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"screen_observation_failed:{type(exc).__name__}","error":screen_error_message(exc, a.serial)},ensure_ascii=False)); return 2
    # A party setup screen can be misclassified as notice because its OCR
    # includes equipment/bonus text. The registered battle-start control is
    # a stronger, screen-specific signal and is checked before notice OCR.
    if screen == "notice":
        # The EX priority-status dialog has the same white/blue chrome as an
        # announcement.  Its title is authoritative and must be recognized
        # before handing the frame to the generic notice closer.
        try:
            priority_path = ROOT / "data/observations/live/task_check_priority_status.png"
            cap.capture(priority_path)
            priority_lines = OCRServiceAdapter(language="jpn").recognize(str(priority_path))
            priority_text = "".join(line.text for line in priority_lines)
            priority_title = centered_title_text(priority_lines)
            if "優先ステータス" in priority_title or "優先ステータス" in priority_text:
                print(json.dumps({"status": "ok", "screen_id": "priority_status",
                                  "entry_mode": "resume", "resume_task": "set_priority_status",
                                  "evidence": "priority_status_title_ocr"}, ensure_ascii=False)); return 0
        except Exception:
            pass
        try:
            invite_path = ROOT / "data/observations/live/task_check_character_join.png"
            cap.capture(invite_path)
            invite_lines = OCRServiceAdapter(language="jpn").recognize(str(invite_path))
            invite_text = "".join(line.text for line in invite_lines)
            if "仲間に勧誘" in invite_text and "勧誘する" in invite_text:
                print(json.dumps({"status": "ok", "screen_id": "character_join",
                                  "entry_mode": "resume", "resume_task": "select_character_join",
                                  "evidence": "invite_character_text_ocr"}, ensure_ascii=False)); return 0
        except Exception:
            pass
        try:
            if probe.target_visible("バトル開始"):
                print(json.dumps({"status": "ok", "screen_id": "battle_party",
                                  "entry_mode": "resume", "resume_task": "start_battle"}, ensure_ascii=False)); return 0
        except Exception:
            pass
        try:
            layout_path = ROOT / "data/observations/live/task_check_party_layout.png"
            cap.capture(layout_path)
            layout = cv2.imread(str(layout_path), cv2.IMREAD_COLOR)
            if layout is not None and layout.shape[0] >= 670 and layout.shape[1] >= 1230:
                hsv = cv2.cvtColor(layout[560:670, 1040:1230], cv2.COLOR_BGR2HSV)
                blue_ratio = float(((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 80)).mean())
                if blue_ratio >= 0.25:
                    print(json.dumps({"status": "ok", "screen_id": "battle_party",
                                      "entry_mode": "resume", "resume_task": "start_battle",
                                      "evidence": "battle_start_layout"}, ensure_ascii=False)); return 0
        except Exception:
            pass
    # Title is a read-only startup state. The artwork changes between app
    # versions, so detect the stable lower-center start label with OCR.
    if screen is None or screen == "notice":
        source = ROOT / "data/observations/live/task_current_screen_source.png"
        roi = ROOT / "data/observations/live/task_current_screen_start_roi.png"
        try:
            cap.capture(source)
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is not None:
                cv2.imwrite(str(roi), image[570:720, 300:980])
                text = "".join(line.text for line in OCRServiceAdapter(language="jpn").recognize(str(roi)))
                full_lines = OCRServiceAdapter(language="jpn").recognize(str(source))
                full_text = "".join(line.text for line in full_lines)
                title_text = centered_title_text(full_lines)
                combined_text = text + full_text
                # Battle result uses a stylized raster "WIN!" title that is
                # not reliable for the template probe.  The title and the
                # lower-right 次へ control together are sufficient evidence.
                if ("WIN" in combined_text.upper() or "ＷＩＮ" in combined_text.upper()) and "次へ" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "battle_victory",
                        "entry_mode": "resume", "resume_task": "wait_battle_result",
                        "evidence": "win_and_next_ocr",
                    }, ensure_ascii=False)); return 0
                # This is distinct from both initial character setup and the
                # battle party screen: selected characters are invited with a
                # dedicated 勧誘する action.  Never route it to battle input.
                if "仲間に勧誘" in combined_text and "勧誘する" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "character_join",
                        "entry_mode": "resume", "resume_task": "select_character_join",
                        "evidence": "invite_character_text_ocr",
                    }, ensure_ascii=False)); return 0
                if "Loading" in combined_text or "CONNECTING" in combined_text or "Now" in combined_text:
                    print(json.dumps({
                        "status": "waiting", "screen_id": "loading",
                        "entry_mode": "resume", "resume_task": "launch_labyrinth",
                        "reason": "startup_loading",
                    }, ensure_ascii=False)); return 0
                if "難易度変更" in title_text and "難易度10" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "difficulty_select",
                        "entry_mode": "resume", "resume_task": "launch_labyrinth",
                    }, ensure_ascii=False)); return 0
                if "ギルド選択確認" in title_text or "ギルド選択確認" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "guild_confirm",
                        "entry_mode": "resume", "resume_task": "task_prepare_l03_screen",
                    }, ensure_ascii=False)); return 0
                # Party setup contains equipment/bonus text that can trigger
                # the generic notice fallback. The centered title is the
                # stronger discriminator and must be checked first.
                if "パーティ編成" in title_text or "パーティ編成" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "battle_party",
                        "entry_mode": "resume", "resume_task": "start_battle",
                    }, ensure_ascii=False)); return 0
                if "キャラ選択" in title_text or "キャラ選択" in combined_text:
                    print(json.dumps({
                        "status": "ok", "screen_id": "initial_char",
                        "entry_mode": "resume", "resume_task": "select_initial_characters",
                    }, ensure_ascii=False)); return 0
                if "クエスト" in combined_text and ("ストーリー" in combined_text or "ギルドハウス" in combined_text):
                    print(json.dumps({
                        "status": "ok", "screen_id": "home",
                        "entry_mode": "new", "resume_task": "launch_labyrinth",
                    }, ensure_ascii=False)); return 0
                if "Touch" in combined_text or "Start" in combined_text or "スタート" in combined_text or "タップ" in combined_text:
                    screen = "title"
        except Exception:
            pass
    active = bool(probe.target_visible("挑戦中")) if screen == "labyrinth_top" else False
    if screen == "title":
        result = {"status": "ok", "screen_id": screen, "entry_mode": "new", "resume_task": "launch_labyrinth"}
        print(json.dumps(result, ensure_ascii=False)); return 0
    result = build_resume_result(screen, active)
    print(json.dumps(result,ensure_ascii=False)); return 0 if result["status"]=="ok" else 2
if __name__=="__main__": raise SystemExit(main())
