"""難易度変更画面をテンプレート登録後に操作するための安全停止タスク。"""

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
    parser = argparse.ArgumentParser(description="難易度10を確認して変更する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    source = ROOT / "data/observations/live/task_difficulty_source.png"
    AdbScreenCapture(serial=args.serial).capture(source)
    print(json.dumps({
        "status": "safety_stop",
        "reason": "difficulty_template_missing_manual_verification_required",
        "capture": str(source),
    }, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
