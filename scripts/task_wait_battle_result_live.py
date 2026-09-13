"""戦闘結果をテンプレートでポーリングする実機タスク（入力なし）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    # Windows consoles may default to cp932; JSON contains OCR text such as
    # emoji/rare kanji, so keep task output machine-readable in UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="戦闘結果を画面変化までOCR監視")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.timeout <= 0 or args.interval <= 0:
        parser.error("timeout/interval must be positive")
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    started = time.monotonic()
    poll = 0
    while time.monotonic() - started < args.timeout:
        poll += 1
        screen = probe.observe_screen()
        if screen in {"battle_victory", "battle_reward"}:
            print(json.dumps({"status": "result_detected", "screen_id": screen, "poll": poll,
                              "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False))
            return 0
        time.sleep(args.interval)
    print(json.dumps({"status": "safety_stop", "reason": "battle_result_timeout", "poll": poll}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
