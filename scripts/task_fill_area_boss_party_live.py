"""エリアボス用パーティを5人にそろえるライブタスク。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config

TAB_POINTS = {1: (130, 120), 2: (300, 120), 3: (450, 120)}
CARD_POINTS = tuple((x, y) for y, xs in ((315, (145, 290, 435, 580, 725, 870, 1015, 1160)), (460, (145, 290, 435, 580, 725, 870, 1015, 1160))) for x in xs)
SLOT_X = (128, 270, 430, 590, 710)


def _capture(capture: AdbScreenCapture, name: str):
    path = ROOT / "data/observations/live" / name
    capture.capture(path)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("capture_failed")
    return image


def _member_count(capture: AdbScreenCapture) -> int:
    image = _capture(capture, "area_boss_party_count.png")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return sum(float(hsv[545:665, x - 55:x + 55, 1].mean()) >= 25.0 for x in SLOT_X)


def _bright_cards(capture: AdbScreenCapture) -> list[tuple[int, int]]:
    image = _capture(capture, "area_boss_party_cards.png")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    points = []
    for x, y in CARD_POINTS:
        roi = hsv[y - 50:y + 50, x - 45:x + 45]
        if float(roi[:, :, 2].mean()) >= 175.0:
            points.append((x, y))
    return points


def _parse_indices(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise RuntimeError("character_indices_must_be_integers") from exc
    if len(values) != 5 or len(set(values)) != 5 or any(value < 1 or value > len(CARD_POINTS) for value in values):
        raise RuntimeError("character_indices_must_be_five_unique_positions_1_to_16")
    return values


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="エリアボスの指定パーティを5人へ補充")
    parser.add_argument("--party", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--character-indices", help="編成するカード位置(1..16)を5個、カンマ区切り。未指定時は自動選択しない")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if probe.observe_screen() not in {"battle_party", "battle_party_ready"}:
        print(json.dumps({"status": "safety_stop", "reason": "area_boss_party_screen_not_confirmed"}, ensure_ascii=False))
        return 2
    try:
        run_adb_coordinate_sequence([TAB_POINTS[args.party]], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), require_screen_change=False,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=f"task_area_boss_party_tab_{args.party}")
        members = _member_count(capture)
        if members < 5:
            indices = _parse_indices(args.character_indices)
            if indices is None:
                raise RuntimeError("composition_not_configured_safe_stop")
            # Explicit positions are required: brightness alone cannot infer
            # role, element, level, or party synergy.
            points = [CARD_POINTS[index - 1] for index in indices]
            for index, point in enumerate(points, 1):
                run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                    timing_policy=AdaptiveWaitPolicy(), require_screen_change=False,
                    debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=f"task_area_boss_party_{args.party}_{index}")
        members = _member_count(capture)
        if members != 5:
            raise RuntimeError(f"party_member_count_not_five:{members}")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"party_fill_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "filled", "party": args.party, "members": 5}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
