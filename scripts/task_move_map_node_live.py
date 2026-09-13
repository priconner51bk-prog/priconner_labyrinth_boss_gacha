"""マップノード移動タスク。未登録テンプレート時は安全停止する。"""

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
    parser = argparse.ArgumentParser(description="マップノードをテンプレート確認して移動")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--type", required=True, choices=("normal", "extreme", "hell", "relic", "connect_sign", "shop", "event", "area_boss", "area_exit"))
    args = parser.parse_args()
    capture = ROOT / "data/observations/live/task_move_map_node_source.png"
    AdbScreenCapture(serial=args.serial).capture(capture)
    print(json.dumps({
        "status": "safety_stop",
        "reason": "map_node_template_missing_manual_verification_required",
        "node_type": args.type,
        "capture": str(capture),
    }, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
