"""パーティ編成画面の候補一覧を1回だけ縦スクロールして確認する。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))
from scripts.labyrinth_route import run_adb_swipe
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    before=ROOT/"data/observations/live/task_scan_party_pool_before.png"; cap.capture(before); image=cv2.imread(str(before),cv2.IMREAD_COLOR)
    if image is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"},ensure_ascii=False)); return 2
    probe=load_template_probe_config(ROOT/"configs/live_screen_templates.json",cap)
    if probe.observe_screen() not in {"battle_party", "battle_party_ready"}:
        print(json.dumps({"status":"safety_stop","reason":"party_screen_not_confirmed"},ensure_ascii=False)); return 2
    try: run_adb_swipe((1100,450),(1100,220),serial=a.serial,healthcheck=True,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_scan_party_pool")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status":"safety_stop","reason":f"swipe_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"scrolled","direction":"up","input":"party_pool"},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
