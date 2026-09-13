"""敗北画面を確認し、終了確認から報酬なし撤退まで実行する。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))

from vision.capture import AdbScreenCapture

def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    before=ROOT/"data/observations/live/task_end_withdraw_before.png"
    cap.capture(before)
    print(json.dumps({"status":"safety_stop","reason":"failed_screen_template_missing_manual_verification_required","capture":str(before)},ensure_ascii=False)); return 2
if __name__=="__main__": raise SystemExit(main())
