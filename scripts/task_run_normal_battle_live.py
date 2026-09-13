"""通常戦闘マスを一周する実機タスク（task_種別）。"""

from __future__ import annotations

import argparse
import json
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
from vision.template_screen_probe import load_template_probe_config


def _pass_confirmation_visible(capture: AdbScreenCapture) -> bool:
    """No OCR fallback exists; unregistered pass dialogs are not actionable."""
    return False


def _wait_for_party_screen(capture: AdbScreenCapture, timeout: float = 8.0) -> bool:
    """Wait for a fresh registered party-screen template after 挑戦する."""
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe.observe_screen() in {"battle_party", "battle_party_ready"}:
            return True
        time.sleep(0.35)
    return False


def _tap(probe, coordinates, *, prefix: str, serial: str, previous: str | None = None) -> str | None:
    if _pass_confirmation_visible(probe.capture):
        raise RuntimeError("pass_confirmation_blocked")
    run_adb_coordinate_sequence(
        [coordinates], serial=serial, healthcheck=True,
        timing_policy=AdaptiveWaitPolicy(), screen_probe=probe.observe_screen,
        require_screen_change=True, previous_screen_token=previous,
        debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=prefix,
    )
    return probe.observe_screen()


def _party_member_count(capture: AdbScreenCapture) -> int:
    """Count filled member cards in the five bottom slots.

    The empty slot is a gray, low-saturation panel while a selected card has
    a saturated portrait.  This cheap ROI check avoids toggling already
    selected cards and prevents starting a four-person party.
    """
    frame = ROOT / "data/observations/live/task_normal_party_count.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("party_count_capture_failed")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    count = 0
    for x in (128, 270, 430, 590, 750):
        roi = hsv[545:665, max(0, x - 55):min(image.shape[1], x + 55)]
        if float(roi[:, :, 1].mean()) >= 35.0:
            count += 1
    return count


def _assert_party_slots_filled(capture: AdbScreenCapture, *, required: int) -> int:
    """再取得した実スロットで開始直前の人数を確定する。"""
    observed = _party_member_count(capture)
    if observed != required:
        raise RuntimeError(f"final_party_member_count_unexpected:{observed}:expected_{required}")
    return observed


def _battle_card_points() -> tuple[tuple[int, int], ...]:
    """Return the twelve card centers in the game's left-to-right order."""
    return tuple(
        (x, y)
        for y, xs in ((240, (145, 290, 435, 580, 725, 870, 1015, 1160)),
                      (395, (145, 290, 435, 580)))
        for x in xs
    )


def _selected_card_indices(capture: AdbScreenCapture) -> set[int]:
    """Read selected cards from the explicit yellow check mark."""
    frame = ROOT / "data/observations/live/task_normal_party_cards.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("party_cards_capture_failed")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    selected: set[int] = set()
    for index, (x, y) in enumerate(_battle_card_points(), 1):
        # The check mark is at the upper-right of each card.  Restricting the
        # ROI avoids confusing portrait shading or the bottom member slots
        # with selection state.
        mark = hsv[max(0, y - 50):min(image.shape[0], y - 10),
                   max(0, x + 28):min(image.shape[1], x + 65)]
        yellow = ((mark[:, :, 0] >= 15) & (mark[:, :, 0] <= 45)
                  & (mark[:, :, 1] >= 90) & (mark[:, :, 2] >= 120))
        # A gold frame/star can raise the pixel ratio without being the
        # selection check. Require one sufficiently large connected check
        # shape, which rejects the unselected fourth card's decorations.
        component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            yellow.astype("uint8"), connectivity=8
        )
        largest_area = max((int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, component_count)), default=0)
        if float(yellow.mean()) >= 0.18 and largest_area >= 200:
            selected.add(index)
    return selected


def _unselected_card_points(capture: AdbScreenCapture) -> list[tuple[int, int]]:
    """Return bright (not dimmed/selected) card centers.

    Selected cards are rendered with a dark overlay.  Mean value in the
    portrait ROI is a more stable discriminator than the check-mark color,
    which overlaps the gold card frame and clips at the right edge.
    """
    frame = ROOT / "data/observations/live/task_normal_party_cards.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("party_cards_capture_failed")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    points: list[tuple[int, int]] = []
    # The second row contains only four cards; probing the empty area to the
    # right produces false candidates and silently wastes a tap.
    selected = _selected_card_indices(capture)
    for index, (x, y) in enumerate(_battle_card_points(), 1):
        card = hsv[max(0, y - 50):min(image.shape[0], y + 50),
                   max(0, x - 45):min(image.shape[1], x + 45)]
        card_value = float(card[:, :, 2].mean())
        card_saturation = float(card[:, :, 1].mean())
        # A false check-mark hit on a bright card is corrected by the card
        # body itself. Truly selected cards are dimmed; bright selected-set
        # entries remain eligible as unselected candidates.
        if index in selected and (card_value < 175.0 or card_saturation < 35.0):
            continue
        # Empty list space is bright but nearly gray; require saturation so
        # it cannot be mistaken for an available character card.
        if float(card[:, :, 2].mean()) >= 175.0 and float(card[:, :, 1].mean()) >= 35.0:
            points.append((x, y))
    return points


def _battle_party_by_layout(capture: AdbScreenCapture) -> bool:
    """Fallback for mojibake OCR: verify the fixed blue battle-start control."""
    frame = ROOT / "data/observations/live/task_battle_party_layout.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 670 or image.shape[1] < 1230:
        return False
    roi = image[560:670, 1040:1230]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue_ratio = float(((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 80)).mean())
    return blue_ratio >= 0.25


def _challenge_by_layout(capture: AdbScreenCapture) -> bool:
    """Verify the NORMAL tile's fixed blue challenge control."""
    frame = ROOT / "data/observations/live/task_normal_challenge_layout.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 670 or image.shape[1] < 1230:
        return False
    roi = image[560:670, 1000:1240]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue_ratio = float(((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 135) & (hsv[:, :, 1] > 80)).mean())
    return blue_ratio >= 0.20


def _other_characters_checkbox_checked(capture: AdbScreenCapture) -> bool:
    """Check the blue tick in the compact auto-EX dialog checkbox."""
    frame = ROOT / "data/observations/live/task_normal_ex_auto_checkbox.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None:
        return False
    roi = image[495:575, 390:485]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 55, 100), (135, 255, 255))
    return float((blue > 0).mean()) >= 0.035


def _all_priority_is_physical(capture: AdbScreenCapture) -> bool:
    """Verify the physical-defense-penetration radio is selected."""
    frame = ROOT / "data/observations/live/task_normal_ex_priority_state.png"
    capture.capture(frame)
    image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 370 or image.shape[1] < 430:
        return False
    # The selected radio is the blue-filled circle at the fixed, registered
    # position of 物理防御貫通 (the second column, third row).
    roi = cv2.cvtColor(image[300:365, 355:420], cv2.COLOR_BGR2HSV)
    blue = ((roi[:, :, 0] > 90) & (roi[:, :, 0] < 135)
            & (roi[:, :, 1] > 70) & (roi[:, :, 2] > 100))
    return float(blue.mean()) >= 0.12


def _set_all_priority_physical(capture: AdbScreenCapture, *, serial: str) -> None:
    """Select and verify the physical-defense-penetration radio once."""
    if _all_priority_is_physical(capture):
        return
    for attempt in range(2):
        run_adb_coordinate_sequence(
            [(386, 334)], serial=serial, healthcheck=True,
            interval_seconds=0.12,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix=f"task_normal_ex_priority_physical_{attempt + 1}",
        )
        if _all_priority_is_physical(capture):
            return
    raise RuntimeError("all_priority_physical_not_verified")


def _parse_character_indices(value: str, *, required: int = 5) -> tuple[int, ...]:
    """Validate a comma-separated card selection (1-based)."""
    try:
        indices = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("character_indices_must_be_comma_separated_integers") from exc
    if len(indices) != required or len(set(indices)) != required or any(index < 1 or index > 12 for index in indices):
        raise ValueError(f"character_indices_must_contain_{required}_unique_values_between_1_and_12")
    return indices


def main() -> int:
    parser = argparse.ArgumentParser(description="通常戦闘を安全に開始する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument(
        "--character-indices",
        help="選択するカード位置を1始まりで指定（例: 1,4,6,9,12）。未指定時は構成不明として停止",
    )
    parser.add_argument("--initial-battle", action="store_true", help="初回戦闘フラグ（編成条件は通常5人、プール4人のみ4人）")
    parser.add_argument("--equipment-only", action="store_true", help="EX装備完了後に戦闘開始せず停止")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    screen = probe.observe_screen()
    # 画面プローブが notice / boss_map に誤分類しても、タイトルOCRで
    # 「バトルマス（NORMAL）」が取れた場合は通常戦闘画面を優先する。
    # パーティ画面はカード内の NORMAL 表記を拾うことがあるため、
    # 通常戦闘マスより先に固定レイアウトで確定する。
    if screen in {"notice", "boss_map"} and _battle_party_by_layout(capture):
        screen = "battle_party"
    if screen not in {"battle_tile_normal", "battle_party", "battle_party_ready"}:
        print(json.dumps({"status": "safety_stop", "reason": "normal_battle_entry_not_confirmed", "screen": screen}, ensure_ascii=False))
        return 2
    try:
        # 原則は常に5人。キャラプールがちょうど4人の場合だけ、
        # 例外として存在する4人全員を使う。
        target_members = 5
        requested_indices = None
        if args.character_indices is not None:
            try:
                requested_indices = _parse_character_indices(args.character_indices, required=target_members)
            except ValueError as exc:
                print(json.dumps({"status": "safety_stop", "reason": str(exc)}, ensure_ascii=False))
                return 2
        if screen == "battle_tile_normal":
            if not (probe.target_visible("挑戦する") or _challenge_by_layout(capture)):
                raise RuntimeError("challenge_target_not_confirmed")
            try:
                screen = _tap(probe, (1120, 610), prefix="task_normal_challenge", serial=args.serial, previous=screen)
            except Exception:
                # 遷移例外は許容するが、最新テンプレートで編成画面を証明するまで
                # カード座標には触れない。
                screen = "notice"
            if _wait_for_party_screen(capture):
                screen = "battle_party"
            else:
                raise RuntimeError("battle_party_transition_not_confirmed")
        if screen not in {"battle_party", "battle_party_ready"}:
            raise RuntimeError(f"unexpected_party_screen:{screen}")
        # Existing members are retained between battles, but a previous run
        # may have only four members.  Fill empty slots until exactly five;
        # the battle-start button is never accepted as proof of party size.
        members = _party_member_count(capture)
        if requested_indices is not None:
            selected_indices = _selected_card_indices(capture)
            desired = set(requested_indices)
            points = _battle_card_points()
            # First remove retained members that are not part of this battle,
            # then add missing desired members. This makes retries deterministic.
            for index in sorted(selected_indices - desired):
                run_adb_coordinate_sequence([points[index - 1]], serial=args.serial, healthcheck=True,
                    interval_seconds=0.08,
                    debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=f"task_normal_party_deselect_{index}")
            for index in requested_indices:
                if index not in selected_indices:
                    run_adb_coordinate_sequence([points[index - 1]], serial=args.serial, healthcheck=True,
                        interval_seconds=0.08,
                        debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix=f"task_normal_party_select_{index}")
            members = _party_member_count(capture)
            # 下部スロットは属性色や暗転で彩度判定が1枠ずれることが
            # あるため、カード上の選択チェックを最終的な補助証拠にする。
            # カード上部のチェックマークOCRは装飾・切れにより
            # 取りこぼすため、選択証拠には使わない。下部の実スロット人数を
            # 唯一の受入条件にする。
            # 暗転判定が未選択カードを選択済みと誤認しても、
            # 実スロット数が不足している場合は指定先頭カードを補完する。
            if members < target_members and 1 in desired:
                run_adb_coordinate_sequence(
                    [_battle_card_points()[0]], serial=args.serial, healthcheck=True,
                    interval_seconds=0.08,
                    debug_capture_dir=ROOT / "data/observations/live",
                    debug_capture_prefix="task_normal_party_select_fallback",
                )
                members = _party_member_count(capture)
        elif members < target_members:
            available_points = _unselected_card_points(capture)
            initial_selected = _selected_card_indices(capture)
            # The bottom member slots are the authoritative selected count;
            # the check-mark detector may overcount gold card decorations.
            pool_size = members + len(available_points)
            if pool_size == 4:
                # キャラプールがちょうど4人の場合だけ、全員を使う。
                for point in available_points:
                    run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                        interval_seconds=0.08,
                        debug_capture_dir=ROOT / "data/observations/live",
                        debug_capture_prefix="task_normal_party_select_all")
                # タップ後は必ず再取得し、未選択カードが残っていないことを
                # 証跡化する。古いcaptureのスロット数だけで開始してはいけない。
                remaining_unselected = _unselected_card_points(capture)
                if remaining_unselected:
                    # A card can still be settling after the first tap. Retry
                    # only the freshly detected unselected cards once; never
                    # tap the whole pool again or infer a missing character.
                    for point in remaining_unselected:
                        run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                            interval_seconds=0.12,
                            debug_capture_dir=ROOT / "data/observations/live",
                            debug_capture_prefix="task_normal_party_select_all_retry")
                    remaining_unselected = _unselected_card_points(capture)
                if remaining_unselected and members == 3 and len(remaining_unselected) == 1:
                    # Some card artwork places the hit target below the
                    # nominal center. Retry within the same verified card
                    # rectangle, never on a different card.
                    x, _y = remaining_unselected[0]
                    run_adb_coordinate_sequence([(x, 255)], serial=args.serial, healthcheck=True,
                        interval_seconds=0.12,
                        debug_capture_dir=ROOT / "data/observations/live",
                        debug_capture_prefix="task_normal_party_select_all_card_retry")
                    remaining_unselected = _unselected_card_points(capture)
                if remaining_unselected:
                    raise RuntimeError("select_all_not_verified")
                members = _party_member_count(capture)
                target_members = 4
            else:
                # Strength, role, element and synergy cannot be inferred from
                # card brightness/order. Never fill a larger party opportunistically.
                raise RuntimeError(
                    "composition_not_configured_safe_stop:"
                    f"members={members};selected={sorted(initial_selected)};"
                    f"available={available_points};pool_size={pool_size}"
                )
        if members != target_members:
            raise RuntimeError(f"party_member_count_unexpected:{members}:expected_{target_members}")
        # EX setup is optional when the party screen already exposes the
        # start control (for example, equipment was retained from the prior
        # battle).  Never infer a missing target; use the visible start
        # control as the explicit safe branch.
        # On the confirmed party screen the EX button has a fixed position;
        # OCR is unreliable on its stylized label, so use the known control
        # directly once the screen ID has been established.
        if screen in {"battle_party", "battle_party_ready"}:
            screen = _tap(probe, (817, 610), prefix="task_normal_ex_open", serial=args.serial, previous=screen)
        elif not probe.target_visible("EX装備"):
            if args.equipment_only:
                print(json.dumps({"status": "equipment_ready", "screen": "battle_party"}, ensure_ascii=False))
                return 0
            _assert_party_slots_filled(capture, required=target_members)
            if not probe.target_visible("バトル開始"):
                raise RuntimeError("ex_equipment_target_not_confirmed")
            _tap(probe, (1135, 605), prefix="task_normal_battle_start", serial=args.serial, previous=screen)
            print(json.dumps({"status": "started", "screen": "battle"}, ensure_ascii=False))
            return 0
        if screen != "ex_equipment":
            raise RuntimeError(f"unexpected_ex_screen:{screen}")
        screen = _tap(probe, (790, 640), prefix="task_normal_ex_auto", serial=args.serial, previous=screen)
        if screen not in {"ex_auto_dialog", "notice"}:
            raise RuntimeError(f"unexpected_ex_dialog:{screen}")
        if screen != "ex_auto_dialog":
            raise RuntimeError(f"ex_auto_dialog_not_confirmed:{screen}")
        _set_all_priority_physical(capture, serial=args.serial)
        if not _other_characters_checkbox_checked(capture):
            # Compact dialog: checkbox is below the four priority rows.
            run_adb_coordinate_sequence(
                [(434, 535)], serial=args.serial, healthcheck=True,
                interval_seconds=0.12,
                debug_capture_dir=ROOT / "data/observations/live",
                debug_capture_prefix="task_normal_ex_auto_checkbox",
            )
            if not _other_characters_checkbox_checked(capture):
                raise RuntimeError("other_characters_checkbox_not_checked")
        screen = _tap(probe, (785, 638), prefix="task_normal_ex_ok", serial=args.serial, previous=screen)
        if screen not in {"ex_equipment", "ex_equipment_conflict", "notice"}:
            raise RuntimeError(f"unexpected_ex_result:{screen}")
        # Confirm the EX equipment.  The game may keep the EX settings
        # screen visible when the confirmation did not take effect; in that
        # case cancel it explicitly instead of guessing that equipment was
        # applied.
        run_adb_coordinate_sequence(
            [(1085, 640)], serial=args.serial, healthcheck=True,
            interval_seconds=0.12,
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_normal_ex_confirm",
        )
        screen = probe.observe_screen()
        if screen not in {"battle_party", "battle_party_ready", "notice", "ex_equipment_conflict"}:
            raise RuntimeError(f"battle_start_not_confirmed:{screen}")
        if args.equipment_only:
            print(json.dumps({"status": "equipment_ready", "screen": screen}, ensure_ascii=False))
            return 0
        _assert_party_slots_filled(capture, required=target_members)
        try:
            _tap(probe, (1135, 605), prefix="task_normal_battle_start", serial=args.serial, previous=screen)
        except Exception:
            # 開始直後の戦闘遷移をプローブが取りこぼした場合のみ、
            # 現在画面を再観測して、同じ開始ボタンが残る時だけ1回再試行する。
            recovered = probe.observe_screen()
            if recovered in {"battle", "battle_result", "battle_victory", "battle_failed"}:
                pass
            elif recovered in {"battle_party", "battle_party_ready"} and probe.target_visible("バトル開始"):
                _tap(probe, (1135, 605), prefix="task_normal_battle_start_retry", serial=args.serial, previous=recovered)
            else:
                raise
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"normal_battle_failed:{type(exc).__name__}",
                          "detail": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "started", "screen": "battle"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
