"""ホーム画面から固定ROIテンプレートでラビリンス入口へ進む。"""

from __future__ import annotations

import argparse
import hashlib
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


def _locate(image, template_path: Path, *, left: int, top: int, right: int, bottom: int) -> tuple[int, int] | None:
    roi = image[top:bottom, left:right]
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None or roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
        return None
    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(result)
    if score < 0.75:
        return None
    return (left + point[0] + template.shape[1] // 2, top + point[1] + template.shape[0] // 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="ホーム画面からクエスト入口を開く")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    current_screen = probe.observe_screen()
    if current_screen == "labyrinth_top":
        print(json.dumps({"status": "safety_stop", "reason": "already_in_labyrinth", "screen_id": current_screen}, ensure_ascii=False))
        return 2
    source = ROOT / "data/observations/live/task_launch_source.png"
    # quest_menu is already inside the quest screen.  Its safe target is the
    # dedicated lower-right labyrinth card, not the bottom navigation label
    # 「クエスト」 used by the home-screen flow.
    if probe.observe_screen() == "quest_menu":
        capture.capture(source)
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
        point = _locate(image, ROOT / "data/observations/live/template_quest_labyrinth_text.png", left=1000, top=450, right=1280, bottom=630)
        if point is None:
            print(json.dumps({"status": "safety_stop", "reason": "labyrinth_target_not_confirmed"}, ensure_ascii=False)); return 2
        x, y = point
        try:
            run_adb_coordinate_sequence(
                [(x, y)], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(), require_screen_change=False,
                debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch_labyrinth",
            )
            after = probe.observe_screen()
        except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
            print(json.dumps({"status": "safety_stop", "reason": f"launch_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        print(json.dumps({"status": "completed", "screen_after": after, "tap": [x, y]}, ensure_ascii=False)); return 0
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
    point = _locate(image, ROOT / "data/observations/live/template_quest_nav_text.png", left=560, top=640, right=900, bottom=720)
    if point is None:
        print(json.dumps({"status": "safety_stop", "reason": "quest_target_not_confirmed"}, ensure_ascii=False)); return 2
    x, y = point
    before_path = ROOT / "data/observations/live/task_launch_before.png"
    capture.capture(before_path)
    previous = hashlib.sha1(before_path.read_bytes()).hexdigest()
    try:
        run_adb_coordinate_sequence(
            [(x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=lambda: hashlib.sha1(before_path.read_bytes()).hexdigest(),
            require_screen_change=False, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch",
        )
        after = probe.observe_screen()
    except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
        print(json.dumps({"status": "safety_stop", "reason": f"launch_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "completed", "screen_after": after, "tap": [x, y]}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
