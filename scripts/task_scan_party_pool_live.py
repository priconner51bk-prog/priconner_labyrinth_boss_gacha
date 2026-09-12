"""パーティ編成画面の候補一覧を1回だけ縦スクロールして確認する。"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))
from scripts.labyrinth_route import run_adb_swipe
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device

def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    before=ROOT/"data/observations/live/task_scan_party_pool_before.png"; cap.capture(before); image=cv2.imread(str(before),cv2.IMREAD_COLOR)
    if image is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"},ensure_ascii=False)); return 2
    try: text="".join(x.text.replace(" ","") for x in PaddleOCRAdapter.from_default_models(device=choose_gpu(),language="jpn").recognize(str(before)) if x.confidence>=.70)
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    if "パーティ編成" not in text and "バトル開始" not in text:
        print(json.dumps({"status":"safety_stop","reason":"party_screen_not_confirmed","text":text},ensure_ascii=False)); return 2
    try: run_adb_swipe((1100,450),(1100,220),serial=a.serial,healthcheck=True,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_scan_party_pool")
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"swipe_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"scrolled","direction":"up","input":"party_pool"},ensure_ascii=False)); return 0
def choose_gpu(): return choose_ocr_device("gpu:0")
if __name__=="__main__": raise SystemExit(main())
