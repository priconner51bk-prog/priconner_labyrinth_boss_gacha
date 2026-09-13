"""コネクトサイン候補をテンプレート確認して選択する。"""

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
    parser = argparse.ArgumentParser(description="コネクトサイン候補を安全に選択")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--choice", type=int, choices=(1, 2, 3))
    group.add_argument("--auto", action="store_true", help="テンプレート登録後に自動選択")
    args = parser.parse_args()

    capture = AdbScreenCapture(serial=args.serial)
    frame = ROOT / "data/observations/live/connect_sign_candidates.png"
    capture.capture(frame)
    if args.auto:
        print(json.dumps({"status": "safety_stop", "reason": "connect_sign_template_missing_manual_verification_required", "capture": str(frame)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "safety_stop", "reason": "connect_sign_template_missing_manual_verification_required", "capture": str(frame)}, ensure_ascii=False))
    return 2
if __name__ == "__main__":
    raise SystemExit(main())
