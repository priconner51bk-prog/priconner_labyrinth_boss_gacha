"""戦闘開始前のキャラカードを収集するライブタスク。

選択操作は行わず、画面・カード画像・座標メタデータだけを保存する。
構成学習前のユーザー補助で利用する。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
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
    parser.add_argument("--ocr-cards", action="store_true", help="カードごとのOCRも実行（通常は画像収集のみ）")
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
    try:
        ocr = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn")
        text = "".join(line.text for line in ocr.recognize(str(full)) if line.confidence >= 0.75)
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    compact = text.replace(" ", "")
    if not (("パーティ" in compact and "編成" in compact) or "バトル開始" in compact or "EX装備" in compact):
        print(json.dumps({"status": "safety_stop", "reason": "battle_party_screen_not_confirmed"}, ensure_ascii=False))
        return 2
    cards = []
    for index, (x, y) in enumerate(CARD_POINTS, 1):
        crop = image[max(0, y - 65):y + 65, max(0, x - 55):x + 55]
        path = args.output_dir / f"{stamp}_card_{index:02d}.png"
        cv2.imwrite(str(path), crop)
        card_text = []
        if args.ocr_cards:
            try:
                card_text = [{"text": line.text, "confidence": line.confidence}
                             for line in ocr.recognize(str(path)) if line.confidence >= 0.60]
            except Exception:
                card_text = []
        cards.append({"index": index, "x": x, "y": y, "path": str(path.relative_to(ROOT)), "ocr": card_text})
    manifest = args.output_dir / f"{stamp}_manifest.json"
    manifest.write_text(json.dumps({"captured_at": stamp, "screen": str(full.relative_to(ROOT)), "ocr_text": text, "cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "captured", "manifest": str(manifest.relative_to(ROOT)), "cards": len(cards)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
