"""タイトル画面を確認して1回だけ開始入力を送り、次画面を再判定する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.labyrinth_route import run_adb_coordinate_sequence
from decision.timing import AdaptiveWaitPolicy
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config
from vision.ocr_service import OCRServiceAdapter


def observe_title(capture, probe) -> str | None:
    screen = probe.observe_screen()
    if screen is not None:
        return screen
    source = ROOT / "data/observations/live/task_startup_source.png"
    roi = ROOT / "data/observations/live/task_startup_start_roi.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        return None
    cv2.imwrite(str(roi), image[570:720, 300:980])
    text = "".join(line.text for line in OCRServiceAdapter(language="jpn").recognize(str(roi)))
    return "title" if any(token in text for token in ("Touch", "Start", "スタート", "タップ")) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="タイトル画面から安全に開始する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    before = observe_title(capture, probe)
    if before != "title":
        print(json.dumps({"status": "safety_stop", "reason": "title_screen_not_confirmed", "screen_id": before}, ensure_ascii=False))
        return 2
    try:
        run_adb_coordinate_sequence(
            [(640, 670)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=probe.observe_screen, require_screen_change=True,
            previous_screen_token=before,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_startup",
        )
        after = probe.observe_screen()
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"startup_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if after in {None, "title"}:
        print(json.dumps({"status": "safety_stop", "reason": "startup_transition_unconfirmed", "screen_after": after}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "completed", "screen_before": before, "screen_after": after}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
