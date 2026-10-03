"""タイトル画面から開始し、通信タイムアウトを上限付きで再試行する。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_START_ATTEMPTS = 3
START_TIMEOUT_SECONDS = 60.0
RETURN_TIMEOUT_SECONDS = 20.0
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def observe_title(capture, probe) -> str | None:
    del capture  # The probe owns the configured capture source.
    for attempt in range(20):
        screen = probe.observe_screen()
        if screen is not None:
            return screen
        if attempt < 19:
            time.sleep(0.25)
    return None


def _tap_and_wait(point, *, args, probe, previous_screen: str, timeout: float, prefix: str,
                  expected_screens: set[str]) -> str | None:
    run_adb_coordinate_sequence(
        [point], serial=args.serial, healthcheck=True,
        timing_policy=AdaptiveWaitPolicy(timeout_seconds=timeout, poll_seconds=0.5),
        screen_probe=probe.observe_screen, require_screen_change=True,
        previous_screen_token=previous_screen,
        debug_capture_dir=ROOT / "data/observations/live",
        debug_capture_prefix=prefix,
    )
    deadline = time.monotonic() + timeout
    last_screen = None
    while time.monotonic() < deadline:
        last_screen = probe.observe_screen()
        if last_screen in expected_screens:
            return last_screen
        if last_screen not in {None, "startup_splash", "loading", previous_screen}:
            return last_screen
        time.sleep(0.5)
    return last_screen


def main() -> int:
    parser = argparse.ArgumentParser(description="タイトル画面から安全に開始する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--max-attempts", type=int, default=MAX_START_ATTEMPTS)
    args = parser.parse_args()
    if not 1 <= args.max_attempts <= MAX_START_ATTEMPTS:
        parser.error(f"--max-attempts must be between 1 and {MAX_START_ATTEMPTS}")
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = observe_title(capture, probe)
    if screen not in {"title", "startup_error"}:
        print(json.dumps({"status": "safety_stop", "reason": "title_or_timeout_screen_not_confirmed", "screen_id": screen}, ensure_ascii=False))
        return 2
    try:
        if screen == "startup_error":
            label = "タイトルへ"
            point = probe.target_center(label) if probe.target_visible(label) else None
            if point is None:
                print(json.dumps({"status": "safety_stop", "reason": "timeout_return_button_not_confirmed", "screen_id": screen}, ensure_ascii=False))
                return 2
            screen = _tap_and_wait(point, args=args, probe=probe, previous_screen=screen,
                                   timeout=RETURN_TIMEOUT_SECONDS, prefix="task_startup_return",
                                   expected_screens={"title"})
            if screen != "title":
                print(json.dumps({"status": "safety_stop", "reason": "timeout_return_unconfirmed", "screen_after": screen}, ensure_ascii=False))
                return 2

        for attempt in range(1, args.max_attempts + 1):
            label = "Touch To Start"
            point = probe.target_center(label) if probe.target_visible(label) else None
            if point is None:
                print(json.dumps({"status": "safety_stop", "reason": "title_start_button_not_confirmed", "attempt": attempt}, ensure_ascii=False))
                return 2
            try:
                after = _tap_and_wait(point, args=args, probe=probe, previous_screen="title",
                                      timeout=START_TIMEOUT_SECONDS, prefix=f"task_startup_{attempt}",
                                      expected_screens={"startup_error", "notice", "home", "quest_menu", "labyrinth_top"})
            except RuntimeError as exc:
                if "タップ後に画面変化がないため停止" not in str(exc):
                    raise
                after = probe.observe_screen()
                if after != "startup_error":
                    print(json.dumps({"status": "safety_stop", "reason": "startup_transition_unconfirmed",
                                      "screen_after": after, "attempt": attempt}, ensure_ascii=False))
                    return 2
            if after == "startup_error":
                if attempt == args.max_attempts:
                    print(json.dumps({"status": "safety_stop", "reason": "startup_timeout_retries_exhausted",
                                      "screen_after": after, "attempts": attempt,
                                      "max_attempts": args.max_attempts, "retry": False}, ensure_ascii=False))
                    return 2
                return_point = probe.target_center("タイトルへ") if probe.target_visible("タイトルへ") else None
                if return_point is None:
                    print(json.dumps({"status": "safety_stop", "reason": "timeout_return_button_not_confirmed",
                                      "attempt": attempt}, ensure_ascii=False))
                    return 2
                screen = _tap_and_wait(return_point, args=args, probe=probe, previous_screen="startup_error",
                                       timeout=RETURN_TIMEOUT_SECONDS, prefix=f"task_startup_return_{attempt}",
                                       expected_screens={"title"})
                if screen != "title":
                    print(json.dumps({"status": "safety_stop", "reason": "timeout_return_unconfirmed",
                                      "screen_after": screen, "attempt": attempt}, ensure_ascii=False))
                    return 2
                continue
            if after in {None, "title"}:
                print(json.dumps({"status": "safety_stop", "reason": "startup_transition_unconfirmed",
                                  "screen_after": after, "attempt": attempt}, ensure_ascii=False))
                return 2
            print(json.dumps({"status": "completed", "screen_before": "title", "screen_after": after,
                              "start_button_point": list(point), "attempts": attempt}, ensure_ascii=False))
            return 0
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"startup_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
