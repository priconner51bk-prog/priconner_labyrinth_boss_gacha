"""戦闘開始前のキャラカードを収集するライブタスク。

選択操作は行わず、画面・カード画像・座標メタデータだけを保存する。
構成学習前のユーザー補助で利用する。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config

CARD_POINTS = tuple(
    (x, y)
    for y in (315, 460)
    for x in (145, 290, 435, 580, 725, 870, 1015, 1160)
)


def main() -> int:
    parser = argparse.ArgumentParser(description="戦闘前キャラカードの学習用収集")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/observations/live/battle_candidates")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen_id = probe.observe_screen()
    if screen_id not in {"battle_party", "battle_party_ready"}:
        print(json.dumps({"status": "safety_stop", "reason": "battle_party_screen_not_confirmed", "screen": screen_id}, ensure_ascii=False))
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    full = args.output_dir / f"{stamp}_screen.png"
    capture.capture(full)
    image = cv2.imread(str(full), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    cards = []
    for index, (x, y) in enumerate(CARD_POINTS, 1):
        crop = image[max(0, y - 65):y + 65, max(0, x - 55):x + 55]
        path = args.output_dir / f"{stamp}_card_{index:02d}.png"
        cv2.imwrite(str(path), crop)
        cards.append({"index": index, "x": x, "y": y, "path": str(path.relative_to(ROOT))})
    manifest = args.output_dir / f"{stamp}_manifest.json"
    manifest.write_text(json.dumps({"captured_at": stamp, "screen": str(full.relative_to(ROOT)), "cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "captured", "manifest": str(manifest.relative_to(ROOT)), "cards": len(cards)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
