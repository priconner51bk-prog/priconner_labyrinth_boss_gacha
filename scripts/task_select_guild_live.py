"""ギルド選択画面で、登録済みカード画像を照合して選択する。"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cv2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture

GUILD_TEMPLATES = {
    "美食殿": "mishoku",
    "トゥインクルウィッシュ": "twinkle_wish",
    "サレンディア救護院": "salendia",
    "王宮騎士団（NIGHTMARE）": "royal_nightmare",
    "自警団（カォン）": "kaon",
    "悪魔偽王国軍（ディアボロス）": "diabolos",
    "牧場（エリザベスパーク）": "ranch_elizabeth",
    "ルーセント学院": "lucent_academy",
    "メルクリウス財団": "mercurius",
    "カルミナ": "carmina",
    "リトルリリカル": "little_lyrical",
    "トワイライトキャラバン": "twilight_caravan",
    "フォレスティエ": "forestier",
}


def _card_center(image, template_path: Path) -> tuple[int, int] | None:
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    roi = image[150:635, 0:1280]
    if template is None or roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
        return None
    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(result)
    if score < 0.72:
        return None
    return (point[0] + template.shape[1] // 2, 150 + point[1] + 150)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--serial",default="127.0.0.1:5555"); p.add_argument("--guild",default="美食殿"); a=p.parse_args(); cap=AdbScreenCapture(serial=a.serial)
    checked = subprocess.run([sys.executable, str(ROOT / "scripts" / "task_check_current_screen_live.py"), "--serial", a.serial], cwd=ROOT, capture_output=True, text=True, check=False, timeout=10)
    payload = json.loads(checked.stdout.strip().splitlines()[-1])
    if payload.get("status") != "ok" or payload.get("screen_id") != "guild_select":
        print(json.dumps({"status":"safety_stop","reason":"guild_select_screen_not_confirmed","screen":payload.get("screen_id")},ensure_ascii=False)); return 2
    source=ROOT/"data/observations/live/task_select_guild_source.png"; probe=ROOT/"data/observations/live/task_select_guild_probe.png"; cap.capture(source)
    image=cv2.imread(str(source),cv2.IMREAD_COLOR)
    if image is None: print(json.dumps({"status":"safety_stop","reason":"capture_failed"},ensure_ascii=False)); return 2
    wanted = a.guild.strip()
    template_name = GUILD_TEMPLATES.get(wanted)
    if template_name is None:
        print(json.dumps({"status":"safety_stop","reason":"guild_template_not_registered","guild":wanted},ensure_ascii=False)); return 2
    point = _card_center(image, ROOT / "data/template_migration/templates/guild_names" / f"{template_name}.png")
    if point is None:
        print(json.dumps({"status":"safety_stop","reason":"guild_card_not_confirmed","guild":wanted},ensure_ascii=False)); return 2
    x, y = point
    token=lambda:(cap.capture(probe),hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x,y)],serial=a.serial,healthcheck=True,timing_policy=AdaptiveWaitPolicy(),screen_probe=token,require_screen_change=False,debug_capture_dir=ROOT/"data/observations/live",debug_capture_prefix="task_select_guild")
    except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"},ensure_ascii=False)); return 2
    print(json.dumps({"status":"selected","guild":wanted,"x":x,"y":y},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
