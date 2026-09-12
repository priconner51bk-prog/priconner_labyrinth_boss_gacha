"""撤退確認をキャンセルし、挑戦を維持する安全タスク。"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args()
    cap=AdbScreenCapture(serial=a.serial); source=ROOT/"data/observations/live/task_cancel_withdraw_source.png"; probe=ROOT/"data/observations/live/task_cancel_withdraw_probe.png"; cap.capture(source)
    if cv2.imread(str(source),cv2.IMREAD_COLOR) is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"},ensure_ascii=False)); return 2
    try:
        lines=PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"),language="jpn").recognize(str(source))
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    text="".join(x.text for x in lines if x.confidence>=.70).replace(" ","")
    # 通常戦闘画面の「パス確認」も、誤操作から安全に戻すためキャンセル対象。
    is_withdraw = "終了確認" in text and "返却" in text
    is_pass = "パス確認" in text and "パス" in text
    if not (is_withdraw or is_pass): print(json.dumps({"status":"safety_stop","reason":"withdraw_dialog_not_verified","text":text},ensure_ascii=False)); return 2
    found=[x for x in lines if x.bbox and x.confidence>=.70 and "キャンセル" in x.text.replace(" ","")]
    if not found: print(json.dumps({"status":"safety_stop","reason":"cancel_not_found","text":text},ensure_ascii=False)); return 2
    b=found[0].bbox; x,y=(b[0]+b[2])//2,(b[1]+b[3])//2
    if not (300<=x<=650 and 430<=y<=560): print(json.dumps({"status":"safety_stop","reason":"cancel_out_of_bounds","x":x,"y":y},ensure_ascii=False)); return 2
    token=lambda:(cap.capture(probe),hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try: run_adb_coordinate_sequence([(x,y)],serial=a.serial,healthcheck=True,timing_policy=AdaptiveWaitPolicy(),screen_probe=token,require_screen_change=True,previous_screen_token=token(),debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_cancel_withdraw")
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"withdraw_cancelled" if is_withdraw else "pass_cancelled","x":x,"y":y},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
