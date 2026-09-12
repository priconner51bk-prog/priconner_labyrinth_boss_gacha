"""ギルド選択画面で、美食殿をOCR確認して選択する。"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device

def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    # Never run guild OCR against a stale/incorrect screen (for example the
    # withdrawal confirmation dialog). Use the shared classifier as the
    # authoritative precondition before capturing or tapping.
    try:
        checked = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_check_current_screen_live.py"), "--serial", a.serial],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=10,
        )
        payload = json.loads(checked.stdout.strip().splitlines()[-1])
        if payload.get("status") != "ok" or payload.get("screen_id") != "guild_select":
            print(json.dumps({"status":"safety_stop","reason":"guild_select_screen_not_confirmed",
                              "screen":payload.get("screen_id")},ensure_ascii=False)); return 2
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, AttributeError) as exc:
        print(json.dumps({"status":"safety_stop","reason":f"guild_select_screen_check_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    source=ROOT/"data/observations/live/task_select_guild_source.png"; probe=ROOT/"data/observations/live/task_select_guild_probe.png"; cap.capture(source)
    image=cv2.imread(str(source),cv2.IMREAD_COLOR)
    if image is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"},ensure_ascii=False)); return 2
    try: lines=PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"),language="jpn").recognize(str(source))
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    guild=[x for x in lines if x.bbox and x.confidence>=.80 and x.text.replace(" ","").replace("　","") == "美食殿"]
    if not guild: print(json.dumps({"status":"safety_stop","reason":"美食殿_not_confirmed"},ensure_ascii=False)); return 2
    box=guild[0].bbox; x=int((box[0]+box[2])/2); y=min(590,max(520,int((box[1]+box[3])/2)+85))
    token=lambda:(cap.capture(probe),hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x,y)],serial=a.serial,healthcheck=True,timing_policy=AdaptiveWaitPolicy(),screen_probe=token,require_screen_change=False,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_select_guild")
    except Exception as exc: print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"selected","guild":"美食殿","x":x,"y":y},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
