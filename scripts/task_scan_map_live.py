"""ラビリンスマップ走査タスク。未登録テンプレート時は安全停止する。"""

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
    parser = argparse.ArgumentParser(description="ラビリンスマップの座標付きノードを取得")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--min-confidence", type=float, default=0.80)
    parser.add_argument("--pan-right", action="store_true")
    parser.add_argument("--full-scan", action="store_true")
    parser.add_argument("--max-swipes", type=int, default=12)
    parser.add_argument("--columns", type=int)
    parser.add_argument("--reuse-scan", type=Path)
    parser.add_argument("--current-node-id")
    args = parser.parse_args()
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("min-confidence must be between 0 and 1")
    if args.columns is not None and args.columns < 2:
        parser.error("columns must be at least 2")
    capture = ROOT / "data/observations/live/task_scan_map_source.png"
    AdbScreenCapture(serial=args.serial).capture(capture)
    print(json.dumps({
        "status": "safety_stop",
        "reason": "map_scan_template_missing_manual_verification_required",
        "capture": str(capture),
    }, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
