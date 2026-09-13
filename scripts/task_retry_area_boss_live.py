"""エリアボス敗北画面で「再挑戦する」だけを安全に選択する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from vision.capture import AdbScreenCapture


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="敗北時のエリアボス再挑戦")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_area_boss_retry_source.png"
    capture.capture(source)
    print(json.dumps({"status": "safety_stop", "reason": "retry_screen_template_missing_manual_verification_required", "capture": str(source)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
