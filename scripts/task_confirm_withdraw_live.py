"""撤退確認ダイアログを安全条件付きで確定するタスク。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="撤退確認をOCR確認して確定")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    screen_probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    source = ROOT / "data/observations/live/task_confirm_withdraw_source.png"
    probe = ROOT / "data/observations/live/task_confirm_withdraw_probe.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
    try:
        ocr = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn")
        lines = ocr.recognize(str(source))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    text = "".join(line.text for line in lines if line.confidence >= 0.70).replace(" ", "")
    # 「終了確認」はゲーム内の撤退確認ダイアログのタイトル。本文の
    # 「返却されます」は表示領域やOCR結果から欠落することがあるため、
    # タイトルだけを必須条件にする。
    if "終了確認" not in text:
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_confirmation_not_verified", "text": text}, ensure_ascii=False)); return 2
    candidates = [line for line in lines if line.bbox and line.confidence >= 0.70 and line.text.strip().upper() in {"OK", "ＯＫ"}]
    if not candidates:
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_ok_not_found", "text": text}, ensure_ascii=False)); return 2
    box = candidates[0].bbox
    x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    if not (620 <= x <= 930 and 430 <= y <= 560):
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_ok_out_of_bounds", "x": x, "y": y}, ensure_ascii=False)); return 2
    token = lambda: (capture.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=args.serial, healthcheck=True,
                                    timing_policy=AdaptiveWaitPolicy(), screen_probe=token,
                                    require_screen_change=True, previous_screen_token=token(),
                                    debug_capture_dir=ROOT / "data/observations/live",
                                    debug_capture_prefix="task_confirm_withdraw")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    # A changed frame is not sufficient: the dialog can disappear while the
    # labyrinth top is still loading.  Do not let the next gacha inspect a
    # transient boss_map frame and tap the wrong control.
    deadline = time.monotonic() + 8.0
    top_ready = False
    while time.monotonic() < deadline:
        try:
            if screen_probe.observe_screen() == "labyrinth_top":
                top_ready = True
                break
        except Exception:
            pass
        time.sleep(0.15)
    if not top_ready:
        print(json.dumps({"status": "safety_stop", "reason": "withdraw_top_not_confirmed"}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "withdraw_confirmed", "x": x, "y": y}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
