"""ボス確認後のマップから初期キャラ画面へ安全に戻る。"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import navigate_to_screen
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    parser = argparse.ArgumentParser(description="ボス確認後に初期キャラ画面へ戻る")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    try:
        screen = probe.observe_screen()
        # ボス名確認後にゲーム側が自動で初期キャラ画面へ戻した場合は、
        # 追加操作をせず、その画面を到達済みとして扱う。
        if screen == "initial_char":
            print(json.dumps({"status": "ready", "screen_id": "initial_char"}, ensure_ascii=False))
            return 0
        if screen == "boss_map":
            subprocess.run(
                ["adb", "-s", args.serial, "shell", "input", "keyevent", "4"],
                check=True,
                capture_output=True,
                text=True,
            )
            policy = AdaptiveWaitPolicy(timeout_seconds=2.0, poll_seconds=0.08)
            policy.wait_for_change_checked("boss_map", probe.observe_screen)
        if probe.observe_screen() == "notice":
            # The post-gacha notice is a known transient overlay.  Its
            # close target is fixed and the transition is still guarded by a
            # screen-change check; no arbitrary map action is issued.
            subprocess.run(
                ["adb", "-s", args.serial, "shell", "input", "tap", "640", "640"],
                check=True,
                capture_output=True,
                text=True,
            )
            policy = AdaptiveWaitPolicy(timeout_seconds=2.0, poll_seconds=0.08)
            policy.wait_for_change_checked("notice", probe.observe_screen)
            for _ in range(20):
                if probe.observe_screen() == "initial_char":
                    print(json.dumps({"status": "ready", "screen_id": "initial_char"}, ensure_ascii=False))
                    return 0
                time.sleep(0.10)
        navigation = navigate_to_screen(
            "initial_char",
            serial=args.serial,
            screen_probe=probe.observe_screen,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_return_initial_char",
        )
        after = str(navigation.get("screen_id", ""))
        # navigate_to_screen が遷移途中の通知を返す場合もある。通知を
        # 閉じてから初期キャラ画面を再確認し、画面が変わらなければ
        # 成功扱いにしない。
        notice_after = after == "notice" or probe.observe_screen() == "notice" or any(
            str(item.get("screen", "")) == "notice"
            for item in navigation.get("trace", [])
            if isinstance(item, dict)
        )
        if notice_after:
            subprocess.run(
                ["adb", "-s", args.serial, "shell", "input", "tap", "640", "640"],
                check=True,
                capture_output=True,
                text=True,
            )
            for _ in range(25):
                try:
                    detected = subprocess.run(
                        [sys.executable, str(ROOT / "scripts/determine_current_state_live.py"), "--serial", args.serial],
                        cwd=ROOT, capture_output=True, text=True, check=False,
                    )
                    payload = json.loads(detected.stdout.strip().splitlines()[-1])
                    detected_screen = payload.get("screen", {}).get("screen_id", "")
                except (OSError, json.JSONDecodeError, IndexError, AttributeError):
                    detected_screen = probe.observe_screen()
                if detected_screen == "initial_char":
                    print(json.dumps({"status": "ready", "screen_id": "initial_char"}, ensure_ascii=False))
                    return 0
                time.sleep(0.10)
        if navigation.get("status") != "ready" or after != "initial_char":
            print(json.dumps({
                "status": "safety_stop",
                "reason": "initial_character_screen_not_confirmed",
                "screen": after or probe.observe_screen(),
                "trace": navigation.get("trace", []),
            }, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "ready", "screen_id": after}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"return_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
