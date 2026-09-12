"""敗北画面の「終了する」を確認して1回だけ押す。"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import cv2
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial); source = ROOT / "data/observations/live/task_end_failed_battle_source.png"; probe = ROOT / "data/observations/live/task_end_failed_battle_probe.png"
    cap.capture(source); image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"}, ensure_ascii=False)); return 2
    try:
        lines = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(source))
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    text = "".join(line.text.replace(" ", "") for line in lines if line.confidence >= .75)
    target = [line for line in lines if line.bbox and line.confidence >= .75 and "終了する" in line.text.replace(" ", "")]
    if "FAILED" not in text or not target:
        print(json.dumps({"status":"safety_stop","reason":"failed_end_target_not_confirmed","text":text}, ensure_ascii=False)); return 2
    box = target[0].bbox; x = int((box[0] + box[2]) / 2); y = int((box[1] + box[3]) / 2)
    token = lambda: (cap.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=a.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), screen_probe=token, require_screen_change=True, previous_screen_token=token(), debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_end_failed_battle")
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status":"ended_failed_battle","x":x,"y":y}, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
