"""コネクトサイン候補をOCR確認して選択する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr_service import OCRServiceAdapter


def _token(capture: AdbScreenCapture) -> str:
    path = ROOT / "data/observations/live/connect_sign_screen_probe.png"
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="コネクトサイン候補を安全に選択")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--choice", type=int, choices=(1, 2, 3))
    group.add_argument("--auto", action="store_true", help="OCRした属性優先度で候補を選択")
    args = parser.parse_args()

    capture = AdbScreenCapture(serial=args.serial)
    frame = ROOT / "data/observations/live/connect_sign_candidates.png"
    capture.capture(frame)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(frame))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2

    trusted = [line for line in lines if line.confidence >= 0.80]
    text = "".join(line.text for line in trusted)
    # ユーザー指定の優先順位。候補の位置ではなく属性と備考をOCR確認して選ぶ。
    attributes = ("光", "火", "闇", "水", "風")
    found = [attribute for attribute in attributes if attribute in text]
    sign_count = sum("ランダムサイン" in line.text for line in trusted)
    title_confirmed = "選択" in text and (sign_count >= 2 or len(found) >= 3)
    if not title_confirmed:
        print(json.dumps({
            "status": "safety_stop",
            "reason": "connect_sign_candidates_not_confirmed",
            "ocr": text,
            "attributes": found,
        }, ensure_ascii=False))
        return 2

    priority = {attribute: index for index, attribute in enumerate(attributes)}
    selected_attribute = None
    choice = args.choice
    if args.auto:
        candidates: list[tuple[int, int, str]] = []
        for line in trusted:
            if not line.bbox:
                continue
            center_x = (line.bbox[0] + line.bbox[2]) / 2
            candidate = 1 if center_x < 430 else 2 if center_x < 850 else 3
            for attribute in attributes:
                if attribute in line.text:
                    candidates.append((priority[attribute], candidate, attribute))
        if not candidates:
            print(json.dumps({"status": "safety_stop", "reason": "connect_sign_attribute_not_confirmed", "ocr": text}, ensure_ascii=False))
            return 2
        _, choice, selected_attribute = min(candidates)
    # The selected card is still user/AI supplied; report the observed
    # priority order so the decision is auditable without guessing candidates.
    card_x = (270, 640, 1010)[choice - 1]
    try:
        before = _token(capture)
        run_adb_coordinate_sequence(
            [(card_x, 590)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=lambda: _token(capture),
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_connect_sign_select",
            require_screen_change=True, previous_screen_token=before,
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2

    print(json.dumps({
        "status": "selected",
        "choice": choice,
        "observed_attributes": found,
        "attribute_priority": list(attributes),
        "selected_attribute": selected_attribute,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
