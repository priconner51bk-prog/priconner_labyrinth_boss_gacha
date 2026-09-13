"""敗北画面の「終了する」を確認して1回だけ押す。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from vision.capture import AdbScreenCapture


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial); source = ROOT / "data/observations/live/task_end_failed_battle_source.png"
    cap.capture(source)
    print(json.dumps({"status":"safety_stop","reason":"failed_screen_template_missing_manual_verification_required","capture":str(source)}, ensure_ascii=False)); return 2
if __name__ == "__main__": raise SystemExit(main())
