"""座標付きマップOCR候補を再確認して1マス移動する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Callable

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence, run_adb_swipe
from scripts.task_scan_map_live import _map_fingerprint, _same_panel
from vision.capture import AdbScreenCapture
from vision.labyrinth_map_ocr import detect_event_nodes, detect_relic_node, detect_terminal_chest, extract_map_nodes
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.ocr_service import OCRServiceAdapter
from vision.template_screen_probe import load_template_probe_config
from diagnostics.safety_stop_analysis import analyze_safety_stop

MAP_SCAN_OCR_Y_OFFSET = 100

# task_scan_map_live OCRs a map-only ROI beginning at y=100 and persists
# coordinates in full-screen space.  This mover OCRs the whole frame; label
# candidates must therefore be normalized before comparison, while the
# persisted scan coordinate remains the deliberate tap coordinate.
# The map scanner OCRs the ROI starting at full-screen y=100 and persists
# those node positions in full-screen coordinates.  Live mover OCR is done
# against the full frame, so normalize its ROI-relative labels by this offset
# before comparing them with the saved scan.


def _matches_scan_position(node: dict, *, node_type: str, expected_x: int, expected_y: int, radius: int) -> bool:
    """Compare a live node using the coordinate convention of saved scans."""
    observed_y = int(node["y"])
    y_candidates = [observed_y]
    if node_type in {"normal", "event", "extreme", "hell", "shop", "area_boss", "area_start"} and not str(node.get("label", "")).endswith("_VISUAL"):
        # Support both ROI-relative fixtures and live full-frame OCR.  Use
        # whichever representation is actually nearest to the saved target;
        # never widen the x/y radius or accept an ambiguous second tile.
        y_candidates.append(observed_y + MAP_SCAN_OCR_Y_OFFSET)
    y_delta = min(abs(candidate - expected_y) for candidate in y_candidates)
    return abs(int(node["x"]) - expected_x) <= radius and y_delta <= radius


class PanelNavigationError(RuntimeError):
    """A guarded panel move could not prove the requested destination."""


def _safety_stop(reason: str, **extra: object) -> dict[str, object]:
    return {"status": "safety_stop", "reason": reason, "analysis": analyze_safety_stop(reason), **extra}


def _select_revalidated_node(
    nodes: list[dict], *, node_type: str, expected_x: int, expected_y: int,
    x_tolerance: int = 180, y_tolerance: int = 100,
) -> dict | None:
    """Select a node conservatively despite horizontal animation/scroll drift.

    Prefer the scan-time X neighbourhood.  If scrolling changed X more than
    expected, accept the Y lane only when exactly one node of the requested
    type is visible; ambiguity always remains a safety stop.
    """
    same_lane = [node for node in nodes if node.get("type") == node_type
                 and abs(int(node["y"]) - expected_y) <= y_tolerance]
    nearby = [node for node in same_lane if abs(int(node["x"]) - expected_x) <= x_tolerance]
    if nearby:
        return min(nearby, key=lambda node: abs(int(node["y"]) - expected_y)
                   + abs(int(node["x"]) - expected_x) * 0.25)
    return same_lane[0] if len(same_lane) == 1 else None


def _navigate_to_panel(
    target_panel: int,
    target_fingerprint: bytes,
    *,
    capture_hash,
    swipe_left,
    swipe_right,
    screen_is_map,
    max_swipes: int = 12,
    verify_panel: Callable[[], bool] | None = None,
) -> bytes:
    """Return on the requested panel, or stop before any node tap.

    The current scroll position is not trusted.  Navigation first proves the
    left edge, then advances exactly ``target_panel`` positions.  The final
    panel fingerprint is revalidated against the scan-time observation.
    """
    if target_panel < 0 or max_swipes < 1 or not target_fingerprint:
        raise PanelNavigationError("invalid_panel_navigation_request")
    if not screen_is_map():
        raise PanelNavigationError("map_screen_lost_before_panel_navigation")
    current = capture_hash()
    if _same_panel(current, target_fingerprint):
        return current

    for _ in range(max_swipes):
        before = current
        swipe_left()
        if not screen_is_map():
            raise PanelNavigationError("map_screen_lost_during_panel_navigation")
        current = capture_hash()
        if _same_panel(current, before):
            break
    else:
        raise PanelNavigationError("map_left_edge_not_confirmed")

    # Panel indices are scan observations, not a promise about the number of
    # pixels moved by a live swipe.  Replaying exactly ``target_panel`` swipes
    # can land on a neighbouring panel when the game coalesces a drag. Walk
    # right from the proven left edge and accept a panel only when its
    # fingerprint or the requested node is visible there.
    if _same_panel(current, target_fingerprint):
        return current
    for _ in range(max_swipes):
        before = current
        swipe_right()
        if not screen_is_map():
            raise PanelNavigationError("map_screen_lost_during_panel_navigation")
        current = capture_hash()
        if _same_panel(current, target_fingerprint):
            return current
        if verify_panel is not None and verify_panel():
            return current
        if _same_panel(current, before):
            raise PanelNavigationError("map_right_edge_before_target_panel")
    raise PanelNavigationError("destination_panel_not_confirmed")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="OCR確認済みマスを選択")
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--type", required=True, choices=("normal", "extreme", "hell", "relic", "connect_sign", "shop", "event", "area_boss", "area_exit"))
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--radius", type=int, default=65)
    parser.add_argument("--panel", type=int)
    parser.add_argument("--panel-x", type=int)
    parser.add_argument("--panel-fingerprint")
    parser.add_argument("--max-panel-swipes", type=int, default=12)
    parser.add_argument(
        "--no-confirm", action="store_true",
        help="選択後の移動先確認を省略する（明示指定時のみ）",
    )
    args = parser.parse_args()
    if args.radius < 10 or args.radius > 120:
        parser.error("radius must be 10..120")
    panel_values = (args.panel, args.panel_x, args.panel_fingerprint)
    if any(value is not None for value in panel_values) and not all(value is not None for value in panel_values):
        parser.error("panel, panel-x and panel-fingerprint must be provided together")
    if args.max_panel_swipes < 1:
        parser.error("max-panel-swipes must be positive")
    capture = AdbScreenCapture(serial=args.serial)
    frame = ROOT / "data/observations/live/task_move_map.png"
    screen_probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    ocr = OCRServiceAdapter(language="jpn")
    capture.capture(frame)
    requested_x = args.x
    resolved_panel_x: int | None = None
    if args.panel is not None:
        try:
            target_fingerprint = bytes.fromhex(args.panel_fingerprint)
        except ValueError:
            print(json.dumps({"status": "safety_stop", "reason": "invalid_panel_fingerprint"}, ensure_ascii=False))
            return 2

        def capture_panel_hash() -> bytes:
            capture.capture(frame)
            image = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise PanelNavigationError("panel_capture_failed")
            return _map_fingerprint(image)

        def swipe(start, end, task_name: str) -> None:
            run_adb_swipe(
                start,
                end,
                serial=args.serial,
                healthcheck=True,
                screen_guard=lambda: screen_probe.observe_screen() == "boss_map",
                task_name=task_name,
            )
            time.sleep(0.25)

        def locate_target_on_current_panel() -> dict | None:
            capture.capture(frame)
            if args.type == "area_exit":
                reference = cv2.imread(str(ROOT / "data/observations/live/area_exit_reference.png"))
                image = cv2.imread(str(frame))
                terminal = detect_terminal_chest(image, reference) if reference is not None else None
                if terminal is not None and abs(terminal["x"] - args.panel_x) <= 240:
                    return terminal
                return None
            image = cv2.imread(str(frame))
            if args.type in {"relic", "connect_sign"}:
                reference_name = "relic_reference.png" if args.type == "relic" else "connect_sign_reference.png"
                reference = cv2.imread(str(ROOT / "data/observations/live" / reference_name))
                threshold = 0.60 if args.type == "connect_sign" else 0.82
                visual_relic = detect_relic_node(image, reference, threshold=threshold) if reference is not None else None
                if visual_relic is not None and args.type == "connect_sign":
                    visual_relic = {**visual_relic, "type": "connect_sign", "label": "CONNECT_SIGN_VISUAL"}
                return visual_relic if (
                    visual_relic is not None
                    and abs(visual_relic["y"] - args.y) <= 100
                    and abs(visual_relic["x"] - args.panel_x) <= 220
                ) else None
            try:
                lines = ocr.recognize(str(frame))
            except Exception:
                return None
            detected = extract_map_nodes(lines, min_confidence=0.75)
            if args.type == "event":
                detected.extend(detect_event_nodes(
                    image, [node for node in detected if node.get("type") == "event"]
                ))
            return _select_revalidated_node(
                detected, node_type=args.type, expected_x=args.panel_x,
                expected_y=args.y,
            )

        def verify_target_panel() -> bool:
            nonlocal resolved_panel_x
            target = locate_target_on_current_panel()
            if target is None:
                return False
            resolved_panel_x = int(target["x"])
            return True

        try:
            _navigate_to_panel(
                args.panel,
                target_fingerprint,
                capture_hash=capture_panel_hash,
                # Keep the drag below the lowest map row. A centre-line drag
                # can cross a node and be interpreted as a tile tap.
                swipe_left=lambda: swipe((600, 605), (900, 605), "map_move_return_left"),
                swipe_right=lambda: swipe((900, 605), (600, 605), "map_move_pan_right"),
                screen_is_map=lambda: screen_probe.observe_screen() == "boss_map",
                max_swipes=args.max_panel_swipes,
                verify_panel=verify_target_panel,
            )
            target = locate_target_on_current_panel()
            if target is None:
                raise PanelNavigationError("destination_node_not_confirmed")
            resolved_panel_x = int(target["x"])
        except PanelNavigationError as exc:
            print(json.dumps(_safety_stop(str(exc)), ensure_ascii=False))
            return 2
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"panel_navigation_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
        requested_x = resolved_panel_x if resolved_panel_x is not None else args.panel_x
    try:
        lines = ocr.recognize(str(frame))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    nodes = extract_map_nodes(lines, min_confidence=0.75)
    if args.type == "event":
        destination = cv2.imread(str(frame))
        nodes.extend(detect_event_nodes(
            destination, [node for node in nodes if node.get("type") == "event"]
        ))
    if args.type == "area_exit":
        reference = cv2.imread(str(ROOT / "data/observations/live/area_exit_reference.png"))
        destination = cv2.imread(str(frame))
        terminal = detect_terminal_chest(destination, reference) if reference is not None else None
        if terminal is not None:
            nodes.append(terminal)
    if args.type in {"relic", "connect_sign"}:
        reference_name = "relic_reference.png" if args.type == "relic" else "connect_sign_reference.png"
        reference = cv2.imread(str(ROOT / "data/observations/live" / reference_name))
        # The relic icon is stable, but live animation/compression lowers the
        # correlation slightly; position and type matching remain mandatory.
        threshold = 0.60 if args.type == "connect_sign" else 0.70
        visual_relic = detect_relic_node(cv2.imread(str(frame)), reference, threshold=threshold) if reference is not None else None
        if visual_relic is not None:
            if args.type == "connect_sign":
                visual_relic = {**visual_relic, "type": "connect_sign", "label": "CONNECT_SIGN_VISUAL"}
            nodes.append(visual_relic)
    matching = [
        node for node in nodes
        if node["type"] == args.type
        and _matches_scan_position(
            node, node_type=args.type, expected_x=requested_x,
            expected_y=args.y,
            radius=args.radius,
        )
    ]
    if not matching:
        print(json.dumps(_safety_stop("map_node_not_confirmed", requested={"x": requested_x, "y": args.y, "type": args.type, "panel": args.panel}, nodes=nodes), ensure_ascii=False))
        return 2
    if screen_probe.observe_screen() != "boss_map":
        print(json.dumps({"status": "safety_stop", "reason": "map_screen_lost"}, ensure_ascii=False))
        return 2
    # Panel navigation may change the viewport origin.  The revalidated node
    # is expressed in the current screen frame, so use that coordinate for
    # the actual tap instead of the persisted world coordinate.
    tap_x = int(matching[0]["x"])
    if args.type == "shop":
        # SHOPはOCRラベルが平台上端に出るため、文字列ではなく
        # 実際に選択できる平台中央をタップする。
        tap_y = int(matching[0]["y"]) + 75
    else:
        tap_y = int(matching[0]["y"]) + (35 if str(matching[0].get("label", "")).endswith("_VISUAL") else -15)
    def movement_token() -> str | None:
        """Detect both map-to-map movement and map-to-battle transitions."""
        screen_id = screen_probe.observe_screen()
        if screen_id != "boss_map":
            return screen_id
        capture.capture(frame)
        image = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return "boss_map"
        return f"boss_map:{_map_fingerprint(image).hex()}"
    before_movement = movement_token()
    try:
        run_adb_coordinate_sequence([(tap_x, tap_y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.05, poll_seconds=0.03, timeout_seconds=1.5),
            # マップの粒子・発光アニメーションで fingerprint が変わるため、
            # 画像差分を遷移証拠にしない。タップ後の遷移可否は、直後の
            # task_confirm_move_live.py による「移動先確認」タイトルOCRで判定する。
            screen_probe=movement_token, require_screen_change=False,
            previous_screen_token=before_movement, debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_move_map")
    except Exception as exc:
        # Some builds use the first tap to highlight a node and the second
        # tap to open its confirmation/battle screen.  Retry only the exact
        # revalidated point; no alternate node or offset is introduced.
        retry_ok = False
        for retry_index, retry_y in enumerate((int(matching[0]["y"]), int(matching[0]["y"]) + 15, int(matching[0]["y"]) - 45), start=1):
            try:
                retry_before = movement_token()
                run_adb_coordinate_sequence([(tap_x, retry_y)], serial=args.serial, healthcheck=True,
                    timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.05, poll_seconds=0.03, timeout_seconds=1.5),
                    screen_probe=movement_token, require_screen_change=False,
                    previous_screen_token=retry_before, debug_capture_dir=ROOT / "data/observations/live",
                    debug_capture_prefix=f"task_move_map_retry_{retry_index}")
                retry_ok = True
                break
            except Exception:
                continue
        if not retry_ok:
            print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "node": matching[0], "retry": "same_tile_points"}, ensure_ascii=False))
            return 2
    if not args.no_confirm:
        confirm = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_confirm_move_live.py"),
             "--serial", args.serial],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        confirm_result: dict[str, object] | None = None
        if confirm.stdout.strip():
            try:
                parsed = json.loads(confirm.stdout.strip().splitlines()[-1])
                if isinstance(parsed, dict):
                    confirm_result = parsed
            except (json.JSONDecodeError, IndexError):
                confirm_result = None
        if confirm.returncode != 0 or not confirm_result or confirm_result.get("status") != "confirmed":
            print(json.dumps({
                "status": "safety_stop",
                "reason": "move_destination_confirmation_failed",
                "selected_node": matching[0],
                "confirmation": confirm_result or {"stdout": confirm.stdout[-500:]},
            }, ensure_ascii=False))
            return 2
        print(json.dumps({
            "status": "confirmed_move",
            "node": matching[0],
            "panel": args.panel,
            "confirmation": confirm_result,
        }, ensure_ascii=False))
        return 0
    print(json.dumps({"status": "moved", "node": matching[0], "panel": args.panel}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
