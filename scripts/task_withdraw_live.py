"""ラビリンス内の撤退だけを実行する安全タスク。"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.template_screen_probe import load_template_probe_config

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap)
    try:
        current = probe.observe_screen()
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    if current is None:
        # 実機の終了確認はテンプレート差でscreen_idが空になるため、
        # ダイアログ固有文言を補助判定する。
        probe_frame = ROOT / "data/observations/live/task_withdraw_confirm_verify.png"; cap.capture(probe_frame)
        try:
            probe_text = "".join(line.text.replace(" ", "") for line in PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(probe_frame)) if line.confidence >= .75)
        except Exception:
            probe_text = ""
        if "終了確認" in probe_text and "報酬なし" in probe_text:
            current = "withdraw_confirm"
    if current == "withdraw_confirm":
        # 敗北後の終了確認画面では中央の「撤退する（報酬なし）」を選ぶ。
        frame = ROOT / "data/observations/live/task_withdraw_confirm_verify.png"; cap.capture(frame)
        try:
            text = "".join(line.text.replace(" ", "") for line in PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(frame)) if line.confidence >= .75)
        except Exception as exc:
            print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        if "終了確認" not in text or "キャンセル" not in text or not ("報酬を獲得せず" in text or "パスポートは返却" in text):
            print(json.dumps({"status":"safety_stop","reason":"withdraw_confirm_target_not_confirmed","text":text}, ensure_ascii=False)); return 2
        try:
            run_adb_coordinate_sequence([(787, 495)], serial=a.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen, require_screen_change=False, debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_withdraw_confirm")
        except Exception as exc:
            print(json.dumps({"status":"safety_stop","reason":f"withdraw_confirm_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        print(json.dumps({"status":"withdraw_confirmed","x":787,"y":495}, ensure_ascii=False)); return 0
    if current not in {"initial_char", "boss_map"}:
        print(json.dumps({"status":"safety_stop","reason":f"unexpected_screen:{current!r}"}, ensure_ascii=False)); return 2
    if current == "initial_char":
        if not probe.target_visible("マップ"):
            print(json.dumps({"status":"safety_stop","reason":"map_target_not_confirmed"}, ensure_ascii=False)); return 2
        try:
            run_adb_coordinate_sequence([(90, 640)], serial=a.serial, healthcheck=True,
                                        timing_policy=AdaptiveWaitPolicy(),
                                        screen_probe=probe.observe_screen,
                                        require_screen_change=True,
                                        previous_screen_token="initial_char",
                                        debug_capture_dir=ROOT / "data/observations/live",
                                        debug_capture_prefix="task_withdraw_open_map")
        except Exception as exc:
            print(json.dumps({"status":"safety_stop","reason":f"map_open_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        try:
            if probe.observe_screen() != "boss_map":
                print(json.dumps({"status":"safety_stop","reason":"map_screen_not_confirmed"}, ensure_ascii=False)); return 2
        except Exception as exc:
            print(json.dumps({"status":"safety_stop","reason":f"map_screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    frame = ROOT / "data/observations/live/task_withdraw_verify.png"; cap.capture(frame)
    try:
        ocr = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn")
        text = "".join(line.text for line in ocr.recognize(str(frame)) if line.confidence >= 0.80).replace(" ", "")
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    # Return/end controls may be visible beside withdraw; their presence is
    # not permission to tap them. Only the withdraw label is accepted target.
    if "撤退する" not in text:
        print(json.dumps({"status":"safety_stop","reason":"withdraw_target_not_confirmed"}, ensure_ascii=False)); return 2
    try:
        run_adb_coordinate_sequence([(910,650)], serial=a.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), require_screen_change=False, debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_withdraw")
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status":"withdraw_selected","x":910,"y":650}, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
