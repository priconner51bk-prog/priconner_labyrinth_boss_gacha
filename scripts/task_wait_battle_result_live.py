"""戦闘結果をOCRポーリングする実機タスク（入力なし）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.ocr_service import OCRServiceAdapter


def main() -> int:
    # Windows consoles may default to cp932; JSON contains OCR text such as
    # emoji/rare kanji, so keep task output machine-readable in UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="戦闘結果を画面変化までOCR監視")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.timeout <= 0 or args.interval <= 0:
        parser.error("timeout/interval must be positive")
    capture = AdbScreenCapture(serial=args.serial)
    ocr = OCRServiceAdapter(language="jpn")
    started = time.monotonic()
    poll = 0
    while time.monotonic() - started < args.timeout:
        poll += 1
        path = ROOT / "data/observations/live" / f"battle_result_poll_{poll}.png"
        capture.capture(path)
        text = "".join(line.text for line in ocr.recognize(str(path)))
        compact = text.replace(" ", "")
        outcome = any(token in compact for token in ("勝利", "敗北", "WIN", "FAILED", "LOSE", "LOSE!"))
        result_button = any(token in compact for token in (
            "次へ", "終了する", "リトライ", "再挑戦", "撤退", "帰還"
        ))
        # 戦闘中の一時表示や結果タイトルだけでは進めない。
        # 勝敗表示と、結果画面の操作ボタンが同じ取得フレームに出た時だけ確定する。
        if outcome and result_button:
            print(json.dumps({"status": "result_detected", "text": text, "poll": poll,
                              "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False))
            return 0
        time.sleep(args.interval)
    print(json.dumps({"status": "safety_stop", "reason": "battle_result_timeout", "poll": poll}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
