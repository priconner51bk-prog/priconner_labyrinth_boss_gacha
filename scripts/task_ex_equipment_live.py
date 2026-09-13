"""EX装備だけを行う実機タスク（task_種別）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def _tap(probe, point, previous: str, prefix: str, serial: str) -> str:
    run_adb_coordinate_sequence(
        [point], serial=serial, healthcheck=True,
        # EX装備画面はアニメーションが短く、長いタイムアウトは
        # 空振り時に不要な待ち時間になる。画面プローブがnoticeへ
        # 誤分類する端末差があるため、ここでは固定座標入力後の
        # 目的画面OCR／後段ガードで確認する。
        timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.03, poll_seconds=0.03, timeout_seconds=0.8),
        screen_probe=probe.observe_screen, require_screen_change=False,
        previous_screen_token=previous, debug_capture_dir=ROOT / "data/observations/live",
        debug_capture_prefix=prefix,
    )
    return probe.observe_screen() or ""


def _checkbox_checked(capture: AdbScreenCapture) -> bool:
    frame = ROOT / "data/observations/live/task_ex_auto_checkbox_state.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        return False
    roi = image[495:575, 390:485]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 55, 100), (135, 255, 255))
    return float((blue > 0).mean()) >= 0.035


def _battle_party_by_layout(capture: AdbScreenCapture) -> bool:
    """Fallback for stylized/garbled OCR on the party screen."""
    frame = ROOT / "data/observations/live/task_battle_party_layout_ex.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 670 or image.shape[1] < 1230:
        return False
    roi = image[560:670, 1040:1230]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 135) & (hsv[:, :, 1] > 80)).mean()) >= 0.25


def _all_priority_is_physical(capture: AdbScreenCapture) -> bool:
    frame = ROOT / "data/observations/live/task_ex_priority_state.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 370 or image.shape[1] < 430:
        return False
    roi = cv2.cvtColor(image[300:365, 355:420], cv2.COLOR_BGR2HSV)
    blue = ((roi[:, :, 0] > 90) & (roi[:, :, 0] < 135)
            & (roi[:, :, 1] > 70) & (roi[:, :, 2] > 100))
    return float(blue.mean()) >= 0.12


def _set_all_priority_physical(capture: AdbScreenCapture, *, serial: str) -> None:
    for attempt in range(12):
        if _all_priority_is_physical(capture):
            return
        run_adb_coordinate_sequence(
            [(778, 243)], serial=serial, healthcheck=True,
            interval_seconds=0.12,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix=f"task_ex_priority_cycle_{attempt + 1}",
        )
    raise RuntimeError("all_priority_physical_not_verified")


def main() -> int:
    parser = argparse.ArgumentParser(description="EX装備のみ実行し、戦闘開始前に停止")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = probe.observe_screen()
    if screen in {"notice", "boss_map"} and _battle_party_by_layout(capture):
        screen = "battle_party"
    if screen == "priority_picker":
        try:
            run_adb_coordinate_sequence(
                [(387, 336)], serial=args.serial, healthcheck=True,
                interval_seconds=0.12,
                debug_capture_dir=ROOT / "data/observations/live",
                debug_capture_prefix="task_ex_priority_resume_select",
            )
            run_adb_coordinate_sequence(
                [(786, 638)], serial=args.serial, healthcheck=True,
                interval_seconds=0.12,
                debug_capture_dir=ROOT / "data/observations/live",
                debug_capture_prefix="task_ex_priority_resume_ok",
            )
            screen = probe.observe_screen()
            if screen != "ex_auto_dialog":
                raise RuntimeError(f"unexpected_ex_auto_after_priority:{screen}")
        except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
            print(json.dumps({"status": "safety_stop", "reason": f"priority_resume_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
    if screen not in {"battle_party", "battle_party_ready", "ex_equipment", "ex_auto_dialog", "ex_equipment_conflict"}:
        print(json.dumps({"status": "safety_stop", "reason": "battle_party_not_confirmed"}, ensure_ascii=False))
        return 2
    try:
        if screen in {"battle_party", "battle_party_ready"}:
            source = ROOT / "data/observations/live/task_ex_equipment_source.png"
            capture.capture(source)
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            button = image[560:665, 770:870] if image is not None else None
            if button is None or button.size == 0 or float(button.std()) < 8.0:
                raise RuntimeError("ex_equipment_target_not_visible")
            screen = _tap(probe, (817, 610), screen, "task_ex_equipment_open", args.serial)
        if screen not in {"ex_equipment", "ex_auto_dialog"}:
            raise RuntimeError(f"unexpected_ex_equipment_screen:{screen}")
        if screen == "ex_equipment":
            screen = _tap(probe, (790, 640), screen, "task_ex_equipment_auto", args.serial)
            if screen != "ex_auto_dialog":
                raise RuntimeError(f"unexpected_ex_auto_dialog:{screen}")
        _set_all_priority_physical(capture, serial=args.serial)
        if not _checkbox_checked(capture):
            run_adb_coordinate_sequence(
                [(434, 535)], serial=args.serial, healthcheck=True,
                interval_seconds=0.12,
                debug_capture_dir=ROOT / "data/observations/live",
                debug_capture_prefix="task_ex_auto_checkbox",
            )
            if not _checkbox_checked(capture):
                raise RuntimeError("other_characters_checkbox_not_checked")
        screen = _tap(probe, (785, 638), screen, "task_ex_equipment_ok", args.serial)
        # 通常は装備画面に戻り、競合がある場合だけ警告画面として
        # 認識される。どちらも安全な出口を明示する。
        if screen == "ex_equipment_conflict":
            screen = _tap(probe, (195, 640), screen, "task_ex_equipment_cancel_conflict", args.serial)
        elif screen == "ex_equipment":
            screen = _tap(probe, (1085, 640), screen, "task_ex_equipment_confirm", args.serial)
        else:
            raise RuntimeError(f"unexpected_ex_equipment_result:{screen}")
        if screen not in {"battle_party", "battle_party_ready"}:
            raise RuntimeError(f"unexpected_party_after_equipment:{screen}")
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "equipment_ready", "screen": screen}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
