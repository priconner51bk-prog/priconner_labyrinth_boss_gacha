"""敗北画面を確認し、終了確認から報酬なし撤退まで実行する。"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device

def ocr_text(cap, path):
    cap.capture(path); image=cv2.imread(str(path),cv2.IMREAD_COLOR)
    if image is None: return ""
    lines=PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"),language="jpn").recognize(str(path))
    return "".join(x.text.replace(" ","") for x in lines if x.confidence>=.75)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    before=ROOT/"data/observations/live/task_end_withdraw_before.png"
    try: text=ocr_text(cap,before)
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    if "FAILED" not in text or "終了する" not in text:
        print(json.dumps({"status":"safety_stop","reason":"failed_screen_not_confirmed","text":text},ensure_ascii=False)); return 2
    try:
        run_adb_coordinate_sequence([(605,655)],serial=a.serial,healthcheck=True,timing_policy=AdaptiveWaitPolicy(),require_screen_change=False,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_end_withdraw_end")
        time.sleep(1.0)
        confirm=ROOT/"data/observations/live/task_end_withdraw_confirm.png"; confirm_text=ocr_text(cap,confirm)
        if "終了確認" not in confirm_text or "撤退する" not in confirm_text or "報酬なし" not in confirm_text:
            print(json.dumps({"status":"safety_stop","reason":"withdraw_confirm_not_verified","text":confirm_text},ensure_ascii=False)); return 2
        run_adb_coordinate_sequence([(640,495)],serial=a.serial,healthcheck=True,timing_policy=AdaptiveWaitPolicy(),require_screen_change=False,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_end_withdraw_confirm")
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"withdraw_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"withdraw_confirmed","boss_loss_counted":False},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
