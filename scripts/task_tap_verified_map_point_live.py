"""画像確認済みの現在画面マスを一点だけタップして遷移を確認する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture


def detected_screen(serial: str) -> str | None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "determine_current_state_live.py"), "--serial", serial],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return payload.get("screen_id") or payload.get("screen", {}).get("screen_id")
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    screen = detected_screen(args.serial)
    if screen != "boss_map":
        print(json.dumps({"status": "safety_stop", "reason": "map_not_confirmed", "screen": screen}, ensure_ascii=False))
        return 2
    frame = ROOT / "data" / "observations" / "live" / "task_tap_verified_map_point.png"
    capture.capture(frame)
    previous_token = hashlib.sha1(frame.read_bytes()).hexdigest()
    try:
        run_adb_coordinate_sequence(
            [(args.x, args.y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.05, poll_seconds=0.03, timeout_seconds=2.0),
            # The move-confirm dialog is sometimes classified as boss_map by
            # the legacy template probe.  Use the captured image token for the
            # transition guard; the follow-up confirmation task performs the
            # screen-specific template check.
            screen_probe=lambda: (capture.capture(frame), hashlib.sha1(frame.read_bytes()).hexdigest())[1],
            previous_screen_token=previous_token,
            require_screen_change=True, debug_capture_dir=frame.parent,
            debug_capture_prefix="task_tap_verified_map_point",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "x": args.x, "y": args.y}, ensure_ascii=False))
        return 2
    after = detected_screen(args.serial)
    print(json.dumps({"status": "transitioned", "x": args.x, "y": args.y, "screen_after": after}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
