"""迷宮遺物選択（task_種別、OCR候補確認付き）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device


EFFECT_PRIORITY = ("会心", "守備", "強化", "加速", "弱体")


def _effect_value(text: str) -> int:
    """Parse an effect stage such as 加速＋3 or 加速+３."""
    normalized = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # The bracketed header (e.g. 【加速+3】) is the stage-equivalent value.
    # Ignore description magnitudes such as 回復強化+10 or 500ダメージ.
    headers = re.findall(r"[【\[]([^】\]]+)[】\]]", normalized)
    header_values = [int(value) for header in headers for value in re.findall(r"[＋+]\s*([0-9]+)", header)]
    if header_values:
        return max(header_values)
    fallback = re.findall(r"[＋+]\s*([0-9]+)", normalized)
    return int(fallback[0]) if fallback else 0


def _auto_choice(lines) -> int | None:
    """Use effect value as the star-equivalent primary ranking."""
    ranked: list[tuple[int, int, int]] = []
    for index, (left, right) in enumerate(((100, 440), (470, 810), (840, 1180)), 1):
        card_lines = [line for line in lines if line.bbox and left <= (line.bbox[0] + line.bbox[2]) / 2 <= right]
        text = "".join(line.text for line in card_lines)
        value = _effect_value(text)
        effect_rank = next((len(EFFECT_PRIORITY) - EFFECT_PRIORITY.index(effect) for effect in EFFECT_PRIORITY if effect in text), 0)
        if value > 0:
            ranked.append((value, effect_rank, -index))
    if not ranked:
        return None
    best = max(range(len(ranked)), key=lambda i: ranked[i])
    return best + 1


def _screen_token(capture: AdbScreenCapture) -> str:
    path = ROOT / "data/observations/live/relic_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="遺物候補をOCR確認して選択")
    parser.add_argument("--choice", type=int, choices=(1, 2, 3))
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    if (args.choice is None) == (not args.auto):
        parser.error("choiceまたはautoのどちらか一方が必要です")
    capture = AdbScreenCapture(serial=args.serial)
    # Relic artwork varies by area; OCR of the three buttons is the primary
    # guard instead of a brittle template screen ID.
    frame = ROOT / "data/observations/live/relic_candidates.png"
    capture.capture(frame)
    try:
        lines = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(frame))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    buttons = [line for line in lines if line.confidence >= 0.80 and "選択する" in line.text]
    if len(buttons) < 3:
        print(json.dumps({"status": "safety_stop", "reason": "relic_buttons_not_confirmed"}, ensure_ascii=False))
        return 2
    if args.auto:
        choice = _auto_choice(lines)
        if choice is None:
            print(json.dumps({"status": "safety_stop", "reason": "relic_effect_value_not_confirmed"}, ensure_ascii=False))
            return 2
    else:
        choice = args.choice
    x = (270, 640, 1010)[choice - 1]
    try:
        run_adb_coordinate_sequence([(x, 620)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=lambda: _screen_token(capture),
            require_screen_change=True, previous_screen_token=_screen_token(capture),
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_relic_select")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "choice": choice}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "selected", "choice": choice}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
