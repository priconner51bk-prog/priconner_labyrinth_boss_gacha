"""初期キャラ選択の実機タスク（task_種別）。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.character_icon_matcher import compare_registered_position
from vision.template_screen_probe import load_template_probe_config


def _observe_initial_char(capture, probe, evidence_path: Path) -> str | None:
    # A transition frame can make this probe disagree with the shared screen
    # checker. Require one stable positive observation, but never infer the
    # screen from a single negative frame before allowing input.
    current = None
    for attempt in range(3):
        try:
            current = probe.observe_screen()
        except Exception:  # noqa: BLE001 - transient probe failure is treated as unknown
            current = None
        if current == "initial_char":
            return current
        if attempt < 2:
            time.sleep(0.15)
    # Use the shared authoritative checker once when the local template probe
    # disagrees. This avoids rejecting a valid screen because two captures
    # landed on different transition frames; it never authorizes input for a
    # screen the checker does not explicitly identify as initial_char.
    try:
        checked = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_check_current_screen_live.py")],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=8,
        )
        payload = json.loads(checked.stdout.strip().splitlines()[-1])
        if payload.get("screen_id") == "initial_char" and payload.get("status") == "ok":
            return "initial_char"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, AttributeError):
        pass
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR確認済みカードだけを初期選択")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--indices", help="選択するカード番号（例: 6,7,8）")
    group.add_argument("--auto", action="store_true", help="OCR確認済みカードから決定論的に3枚選ぶ")
    parser.add_argument("--manual-confirmed", action="store_true",
                        help="ユーザーが画面で確認済みの番号を、カード画像の存在だけ検証して選択")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--guild", default="美食殿")
    parser.add_argument("--verify-boss-after-selection", action="store_true",
                        help="選択後にマップを開き、ボス名確認・対象外撤退・再抽選まで続ける")
    parser.add_argument("--output", type=Path, default=ROOT / "data/observations/live/initial_characters_selected.png")
    args = parser.parse_args()
    selection_reason = "specified_indices"
    if args.auto:
        print(json.dumps({"status": "user_assist_required", "reason": "auto_selection_requires_manual_indices"}, ensure_ascii=False))
        return 0
    indices: list[int] = []
    if args.indices:
        try:
            indices = [int(value.strip()) for value in args.indices.split(",")]
        except ValueError:
            print(json.dumps({"status": "safety_stop", "reason": "indices_invalid"}, ensure_ascii=False))
            return 2
        card_count = len(json.loads((ROOT / "configs/labyrinth_ocr_regions.json").read_text(encoding="utf-8"))["regions"]["initial_character_cards"])
        if len(indices) != 3 or len(set(indices)) != 3 or not all(1 <= value <= card_count for value in indices):
            print(json.dumps({"status": "safety_stop", "reason": "indices_must_be_three_unique_cards"}, ensure_ascii=False))
            return 2
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    current_screen = _observe_initial_char(
        capture, probe, args.output.with_name("initial_character_screen_check.png")
    )
    if current_screen != "initial_char":
        print(json.dumps({"status": "safety_stop", "reason": "unexpected_screen"}, ensure_ascii=False))
        return 2
    capture.capture(args.output)
    image = cv2.imread(str(args.output), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    config = json.loads((ROOT / "configs/labyrinth_ocr_regions.json").read_text(encoding="utf-8"))
    regions = config["regions"]["initial_character_cards"]
    registry = json.loads((ROOT / "configs/character_icon_registry.json").read_text(encoding="utf-8"))
    reference_path = ROOT / "data/observations/live/initial_character_candidates.png"
    reference_image = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    known_positions = registry.get("guilds", {}).get(args.guild, {}).get("selectable_character_ids_by_position", {})
    if args.manual_confirmed and reference_image is not None:
        for index in indices:
            expected_name = known_positions.get(str(index))
            if not expected_name:
                print(json.dumps({"status": "safety_stop", "reason": "character_position_not_registered", "index": index}, ensure_ascii=False))
                return 2
            center = tuple(registry["screen_settings"]["card_centers"][str(index)])
            character = registry.get("character_pool", {}).get("characters", {}).get(expected_name, {})
            # A user-confirmed new guild position is safe to use before its
            # reusable icon reference has been captured.  Once features are
            # confirmed, retain the strict multi-metric match.
            if character.get("features_confirmed") and reference_image is not None:
                match = compare_registered_position(image, reference_image, center)
                if not match["matched"]:
                    print(json.dumps({"status": "safety_stop", "reason": "character_icon_mismatch", "index": index, "name": expected_name, "match": match}, ensure_ascii=False))
                    return 2
    if args.manual_confirmed:
        # OCR is intentionally skipped only after the user has supplied the
        # exact three card numbers.  A non-flat crop prevents taps on an
        # empty/obscured slot while avoiding the 10-second OCR model startup.
        candidates = []
        for index, region in enumerate(regions, start=1):
            if index not in indices:
                continue
            normalized = region.get("normalized", {})
            x = int(float(normalized.get("x", 0)) * image.shape[1])
            y = int(float(normalized.get("y", 0)) * image.shape[0])
            width = int(float(normalized.get("width", 0)) * image.shape[1])
            height = int(float(normalized.get("height", 0)) * image.shape[0])
            crop = image[max(0, y):y + height, max(0, x):x + width]
            if crop.size == 0 or float(crop.std()) < 8.0:
                print(json.dumps({"status": "safety_stop", "reason": "manual_card_slot_not_visible", "index": index}, ensure_ascii=False))
                return 2
            candidates.append({"index": index, "name": f"manual_confirmed_{index}",
                               "confidence": 1.0, "x": int(region.get("center", {}).get("x", x + width // 2)),
                               "y": int(region.get("center", {}).get("y", y + height // 2))})
    else:
        print(json.dumps({"status": "user_assist_required", "reason": "manual_confirmed_required_without_ocr"}, ensure_ascii=False))
        return 0
    by_index = {item["index"]: item for item in candidates}
    if any(index not in by_index for index in indices):
        print(json.dumps({"status": "safety_stop", "reason": "requested_card_not_recognized", "candidates": candidates}, ensure_ascii=False))
        return 2
    points = [(by_index[index]["x"], by_index[index]["y"]) for index in indices]
    try:
        # 候補カードの選択中は同一画面のままなので、各タップ後の画面変化
        # 待ちは行わない。最後の勧誘ボタンだけを遷移確認する。
        run_adb_coordinate_sequence(points, serial=args.serial, healthcheck=True,
                                    interval_seconds=0.08,
                                    debug_capture_dir=ROOT / "data/observations/live",
                                    debug_capture_prefix="task_initial_character_select",
                                    require_screen_change=False)
        # The tap itself changes the debug image, so image-token change is not
        # sufficient proof of a screen transition.  The map button is also at
        # the bottom of this screen; accepting the old screen here could make
        # the next preparation step press it accidentally.
        run_adb_coordinate_sequence([(1090, 635)], serial=args.serial, healthcheck=True,
                                    timing_policy=AdaptiveWaitPolicy(),
                                    debug_capture_dir=ROOT / "data/observations/live",
                                    debug_capture_prefix="task_initial_character_recruit",
                                    require_screen_change=False)
        deadline = time.monotonic() + 8.0
        after_screen = None
        while time.monotonic() < deadline:
            after_screen = probe.observe_screen()
            if after_screen in {"character_join", "boss_map"}:
                break
            time.sleep(0.15)
        if after_screen not in {"character_join", "boss_map"}:
            print(json.dumps({"status": "safety_stop", "reason": "recruit_screen_not_confirmed",
                              "screen_after": after_screen}, ensure_ascii=False))
            return 2
    except Exception as exc:  # noqa: BLE001 - convert input failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "candidates": candidates}, ensure_ascii=False))
        return 2
    result = {"status": "selected", "indices": indices, "candidates": candidates,
              "selection_reason": selection_reason,
              "priority_credit": selection_reason != "pool_under_five_all"}
    if args.verify_boss_after_selection:
        prepare = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_prepare_l03_screen_live.py"),
             "--serial", args.serial], cwd=ROOT, capture_output=True, text=True, check=False)
        try:
            prepare_result = json.loads(prepare.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            prepare_result = {"status": "safety_stop", "reason": "initial_map_prepare_invalid_output"}
        if prepare_result.get("status") != "ready":
            result.update({"status": "safety_stop", "reason": "initial_map_prepare_failed",
                           "detail": prepare_result})
        else:
            gacha = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "task_boss_gacha_live.py"),
                 "--execute", "--default-models", "--resume-screen", "boss_map",
                 "--serial", args.serial, "--guild", args.guild],
                cwd=ROOT, capture_output=True, text=True, check=False)
            try:
                gacha_result = json.loads(gacha.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                gacha_result = {"status": "safety_stop", "reason": "boss_check_invalid_output"}
            result["boss_check"] = gacha_result
            if gacha_result.get("status") != "matched":
                result.update({"status": "safety_stop", "reason": "boss_check_failed"})
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
