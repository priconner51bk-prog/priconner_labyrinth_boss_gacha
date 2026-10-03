"""ホーム画面から固定ROIテンプレートでラビリンス入口へ進む。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
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


def _wait_for_screen(probe, expected: str, timeout: float = 90.0) -> str | None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = probe.observe_screen()
        if last in {expected, "startup_error"}:
            return last
        time.sleep(1.0)
    return last


def _wait_for_interactable_screen(probe, timeout: float = 180.0) -> str | None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = probe.observe_screen()
        if last in {"home", "quest_menu", "labyrinth_top", "startup_error"}:
            return last
        time.sleep(1.0)
    return last


def _pixel_token(capture, path: Path) -> str:
    capture.capture(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="ホーム画面からクエスト入口を開く")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    probe_path = ROOT / "data/observations/live/task_launch_probe.png"
    screen_token = lambda: _pixel_token(capture, probe_path)
    current_screen = probe.observe_screen()
    if current_screen == "network_loading":
        current_screen = _wait_for_interactable_screen(probe)
        if current_screen == "startup_error":
            print(json.dumps({"status": "safety_stop", "reason": "startup_network_timeout",
                              "screen_after": current_screen}, ensure_ascii=False))
            return 2
        if current_screen == "network_loading":
            print(json.dumps({"status": "safety_stop", "reason": "startup_transition_timeout",
                              "screen_after": current_screen}, ensure_ascii=False))
            return 2
        if current_screen not in {"home", "quest_menu", "labyrinth_top"}:
            print(json.dumps({"status": "safety_stop", "reason": "startup_transition_timeout",
                              "screen_after": current_screen}, ensure_ascii=False))
            return 2
    if current_screen == "labyrinth_top":
        print(json.dumps({"status": "completed", "screen_before": current_screen,
                          "screen_after": current_screen, "already_there": True}, ensure_ascii=False))
        return 0
    if current_screen not in {"home", "quest_menu"}:
        print(json.dumps({"status": "safety_stop", "reason": "navigation_start_screen_not_confirmed",
                          "screen_id": current_screen}, ensure_ascii=False))
        return 2
    source = ROOT / "data/observations/live/task_launch_source.png"
    taps = []
    screen = current_screen
    if screen == "home":
        capture.capture(source)
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
            return 2
        point = _locate(image, ROOT / "data/observations/live/template_quest_nav_text.png",
                        left=560, top=630, right=900, bottom=720)
        if point is None:
            print(json.dumps({"status": "safety_stop", "reason": "quest_target_not_confirmed",
                              "screen_id": screen}, ensure_ascii=False))
            return 2
        try:
            run_adb_coordinate_sequence(
                [point], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(timeout_seconds=60.0, poll_seconds=0.5),
                screen_probe=screen_token, require_screen_change=True, previous_screen_token=screen_token(),
                debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch_quest",
            )
        except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
            after_error = probe.observe_screen()
            if after_error == "startup_error":
                reason = "startup_network_timeout"
            elif after_error in {"startup_splash", "loading"}:
                reason = "startup_transition_timeout"
            else:
                reason = f"quest_launch_failed:{type(exc).__name__}"
            print(json.dumps({"status": "safety_stop", "reason": reason,
                              "screen_after": after_error}, ensure_ascii=False))
            return 2
        taps.append({"target": "クエスト", "point": list(point)})
        screen = _wait_for_screen(probe, "quest_menu")
        if screen == "startup_error":
            print(json.dumps({"status": "safety_stop", "reason": "startup_network_timeout",
                              "screen_after": screen, "retry": False, "taps": taps}, ensure_ascii=False))
            return 2
        if screen != "quest_menu":
            reason = "startup_transition_timeout" if screen in {"startup_splash", "loading", "network_loading"} else "quest_screen_transition_unconfirmed"
            print(json.dumps({"status": "safety_stop", "reason": reason,
                              "screen_after": screen, "taps": taps}, ensure_ascii=False))
            return 2

    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed", "screen_id": screen}, ensure_ascii=False))
        return 2
    point = _locate(image, ROOT / "data/observations/live/template_quest_labyrinth_text.png",
                    left=1050, top=420, right=1280, bottom=485)
    if point is None:
        print(json.dumps({"status": "safety_stop", "reason": "labyrinth_target_not_confirmed",
                          "screen_id": screen, "taps": taps}, ensure_ascii=False))
        return 2
    try:
        run_adb_coordinate_sequence(
            [point], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(timeout_seconds=60.0, poll_seconds=0.5),
            screen_probe=screen_token, require_screen_change=True, previous_screen_token=screen_token(),
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch_labyrinth",
        )
    except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
        after_error = probe.observe_screen()
        if after_error == "startup_error":
            reason = "startup_network_timeout"
        elif after_error in {"startup_splash", "loading"}:
            reason = "startup_transition_timeout"
        else:
            reason = f"labyrinth_launch_failed:{type(exc).__name__}"
        print(json.dumps({"status": "safety_stop", "reason": reason, "screen_after": after_error,
                          "screen_id": screen, "taps": taps}, ensure_ascii=False))
        return 2
    taps.append({"target": "ラビリンス", "point": list(point)})
    after = _wait_for_screen(probe, "labyrinth_top")
    if after == "startup_error":
        print(json.dumps({"status": "safety_stop", "reason": "startup_network_timeout",
                          "screen_after": after, "retry": False,
                          "taps": taps + [{"target": "ラビリンス", "point": list(point)}]}, ensure_ascii=False))
        return 2
    if after != "labyrinth_top":
        reason = "startup_transition_timeout" if after in {"startup_splash", "loading", "network_loading"} else "labyrinth_screen_transition_unconfirmed"
        print(json.dumps({"status": "safety_stop", "reason": reason,
                          "screen_after": after, "taps": taps}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "completed", "screen_before": current_screen,
                      "screen_after": after, "taps": taps}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
