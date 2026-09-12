"""ショップ退出確認をOCRで検証して確定するタスク。"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.template_screen_probe import load_template_probe_config

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--serial", default="127.0.0.1:5555"); a = p.parse_args()
    cap = AdbScreenCapture(serial=a.serial); frame = ROOT / "data/observations/live/shop_exit_verify.png"; cap.capture(frame)
    try:
        lines = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(frame))
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    text = "".join(line.text for line in lines if line.confidence >= 0.80)
    if "ショップ" not in text or "退出" not in text or "OK" not in text:
        print(json.dumps({"status":"safety_stop","reason":"shop_exit_dialog_not_confirmed"}, ensure_ascii=False)); return 2
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", cap); previous = probe.observe_screen()
    try:
        run_adb_coordinate_sequence([(785,495)], serial=a.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
            require_screen_change=True, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_shop_exit")
    except Exception as exc:
        print(json.dumps({"status":"safety_stop","reason":f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status":"completed","screen_after":probe.observe_screen()}, ensure_ascii=False)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
