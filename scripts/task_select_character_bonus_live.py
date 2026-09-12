"""キャラ加入ボーナス選択（task_種別、画面確認付き）。"""

from __future__ import annotations

import argparse
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


def _character_bonus_by_ocr(capture: AdbScreenCapture) -> bool:
    frame = ROOT / "data/observations/live/character_bonus_screen_ocr.png"
    capture.capture(frame)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(frame))
    except Exception:
        return False
    text = "".join(line.text.replace(" ", "") for line in lines if line.confidence >= 0.75)
    return "キャラ加入ボーナス" in text and text.count("選択する") >= 3


def _character_bonus_by_layout(capture: AdbScreenCapture) -> bool:
    frame = ROOT / "data/observations/live/character_bonus_layout.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ratios = []
    for left, right in ((170, 370), (540, 740), (910, 1110)):
        roi = hsv[545:650, left:right]
        ratios.append(float(((roi[:, :, 0] > 90) & (roi[:, :, 0] < 135) & (roi[:, :, 1] > 80)).mean()))
    return min(ratios) >= 0.20


def main() -> int:
    parser = argparse.ArgumentParser(description="キャラ加入ボーナス候補を選択")
    parser.add_argument("--choice", type=int, choices=(1, 2, 3))
    parser.add_argument("--auto", action="store_true", help="OCRで最初に読めた候補を選ぶ")
    parser.add_argument("--manual-confirmed", action="store_true", help="指定番号をテンプレート確認だけで高速選択")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    if (args.choice is None) == (not args.auto):
        parser.error("choiceまたはautoのどちらか一方が必要です")
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    detected = probe.observe_screen()
    layout_confirmed = _character_bonus_by_layout(capture)
    if detected != "character_bonus" and not (_character_bonus_by_ocr(capture) or layout_confirmed):
        print(json.dumps({"status": "safety_stop", "reason": "unexpected_screen"}, ensure_ascii=False))
        return 2
    frame = ROOT / "data/observations/live/character_bonus_candidates.png"
    capture.capture(frame)
    if args.manual_confirmed and args.choice is not None:
        if not probe.target_visible("キャラボーナス選択"):
            print(json.dumps({"status": "safety_stop", "reason": "selection_target_not_confirmed", "choice": args.choice}, ensure_ascii=False))
            return 2
        lines = []
        names = []
    else:
        ocr = OCRServiceAdapter(language="jpn")
        lines = ocr.recognize(str(frame))
        names = [line for line in lines if line.confidence >= 0.80 and line.bbox and 180 <= (line.bbox[1] + line.bbox[3]) / 2 <= 530]
    if args.auto:
        if not names:
            print(json.dumps({"status": "safety_stop", "reason": "character_bonus_candidates_not_recognized"}, ensure_ascii=False))
            return 2
        # Candidate cards are left-to-right; use the first confidently read name.
        center_x = (names[0].bbox[0] + names[0].bbox[2]) / 2
        choice = 1 if center_x < 430 else 2 if center_x < 850 else 3
    else:
        choice = args.choice
    if not args.manual_confirmed and not layout_confirmed and not any("選択する" in line.text for line in lines if line.confidence >= 0.80):
        print(json.dumps({"status": "safety_stop", "reason": "selection_target_not_confirmed", "choice": choice}, ensure_ascii=False))
        return 2
    x = (270, 640, 1010)[choice - 1]
    try:
        run_adb_coordinate_sequence([(x, 590)], serial=args.serial, healthcheck=True,
                                    timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
                                    debug_capture_dir=ROOT / "data/observations/live",
                                    debug_capture_prefix="task_character_bonus_select",
                                    require_screen_change=True, previous_screen_token="character_bonus")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "choice": choice}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "selected", "choice": choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
