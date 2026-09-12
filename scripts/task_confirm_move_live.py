"""移動先確認ダイアログのOKをROI OCR確認して押す。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.ocr_service import OCRServiceAdapter
from vision.template_screen_probe import load_template_probe_config


MOVE_TITLE_ROI = (300, 130, 980, 230)
MOVE_BUTTON_ROI = (300, 430, 950, 550)


def _crop(image, roi: tuple[int, int, int, int]):
    left, top, right, bottom = roi
    return image[top:bottom, left:right]


def _has_move_title(lines) -> bool:
    return any(
        line.bbox and line.confidence >= 0.75
        and "移動先確認" in line.text.replace(" ", "")
        for line in lines
    )


def _find_compact_move_ok(lines):
    # The compact dialog places Cancel on the left and OK on the right.
    # Never accept an arbitrary OK outside the right-hand button lane.
    candidates = [
        line for line in lines
        if line.bbox and line.confidence >= 0.75
        and ("OK" in line.text.upper() or "ＯＫ" in line.text)
        and line.bbox[0] >= 320
    ]
    return candidates[0] if candidates else None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="移動確認のOKボタンを押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    screen_probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    # The compact move dialog is occasionally classified as withdraw_confirm
    # because both screens share the same bottom button geometry.  The
    # dedicated title OCR below is the authoritative discriminator; do not
    # tap anything until it confirms the exact 移動先確認 title.
    source = ROOT / "data/observations/live/task_confirm_move_source.png"
    roi_path = ROOT / "data/observations/live/task_confirm_move_roi.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    title_roi = _crop(image, MOVE_TITLE_ROI)
    title_path = ROOT / "data/observations/live/task_confirm_move_title_roi.png"
    cv2.imwrite(str(title_path), title_roi)
    try:
        title_lines = OCRServiceAdapter(language="jpn").recognize(str(title_path))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"title_ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if not _has_move_title(title_lines):
        print(json.dumps({"status": "safety_stop", "reason": "move_confirm_title_not_confirmed"}, ensure_ascii=False))
        return 2
    roi = _crop(image, MOVE_BUTTON_ROI)
    cv2.imwrite(str(roi_path), roi)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(roi_path))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    ok_line = _find_compact_move_ok(lines)
    if ok_line is None:
        print(json.dumps({"status": "safety_stop", "reason": "move_ok_not_confirmed"}, ensure_ascii=False))
        return 2
    box = ok_line.bbox
    x = int((box[0] + box[2]) / 2) + 300
    y = int((box[1] + box[3]) / 2) + 430
    probe = ROOT / "data/observations/live/task_confirm_move_probe.png"
    token = lambda: (capture.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=args.serial, healthcheck=True, timing_policy=AdaptiveWaitPolicy(), screen_probe=token, require_screen_change=True, previous_screen_token=token(), debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_confirm_move")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "confirmed", "x": x, "y": y}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
