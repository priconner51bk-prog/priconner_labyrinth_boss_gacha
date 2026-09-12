"""マップをOCRし、座標付きマス候補をオーケストレータへ渡す。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from vision.capture import AdbScreenCapture
from vision.labyrinth_map_ocr import (
    detect_event_nodes,
    detect_player_node,
    detect_relic_node,
    detect_terminal_chest,
    extract_map_nodes,
)
from vision.labyrinth_connectors import connection_score
from vision.ocr import choose_ocr_device
from vision.ocr_service import OCRServiceAdapter
from vision.roi import NormalizedROI
from vision.template_screen_probe import load_template_probe_config
from scripts.labyrinth_route import run_adb_swipe


# 一度に複数列を跨がないよう、1列相当の小刻みなスクロールにする。
# 300pxドラッグでは列重複の補正が不安定になったため、200pxへ縮小。
MAP_PAN_START = (850, 605)
MAP_PAN_END = (650, 605)
MAP_PAN_LEFT_START = MAP_PAN_END
MAP_PAN_LEFT_END = MAP_PAN_START
MAP_RETURN_START = MAP_PAN_END
MAP_RETURN_END = MAP_PAN_START
# The game map shifts by about one column for the guarded 200px drag.
MAP_PAN_WORLD_SHIFT = 350
EDGE_SCORE_THRESHOLD = 0.50
# ヘッダー、所持数、撤退・帰還ボタンを除き、マスと接続線がある領域だけをOCRする。
MAP_OCR_ROI = NormalizedROI(x=0.0, y=100 / 720, width=1.0, height=500 / 720)


def _recognize_map(ocr: OCRServiceAdapter, frame: Path):
    """マップROIだけをOCRし、元画像座標へbboxを戻す。"""
    lines = ocr.recognize(str(frame), roi=MAP_OCR_ROI)
    # OCRServiceAdapter returns absolute screen coordinates even when an ROI
    # is supplied.  Do not add the ROI top offset a second time.
    return lines


def _detect_area_number(ocr: OCRServiceAdapter, frame: Path) -> int | None:
    """Read the area header separately from the map-only OCR ROI."""
    try:
        lines = ocr.recognize(str(frame))
    except Exception:
        return None
    header = "".join(
        str(getattr(line, "text", ""))
        for line in lines
        if getattr(line, "bbox", None) and int(line.bbox[1]) < 110
    )
    normalized = header.replace(" ", "").replace("　", "")
    match = re.search(r"エリア[^0-9]*([1-5])[^0-9]*[/／][^0-9]*5", normalized)
    if match:
        return int(match.group(1))
    # Some OCR models omit the label but retain the header fraction.
    match = re.search(r"([1-5])[^0-9]*[/／][^0-9]*5", normalized)
    if match:
        return int(match.group(1))
    return None


def _connector_anchor(node: dict) -> dict[str, int]:
    """Return the platform anchor above the OCR label."""
    offset = {"normal": 55, "event": 110, "area_boss": 55,
              "area_start": 55,
              "area_exit": 70}.get(str(node.get("type", "")), 55)
    return {
        "x": int(node.get("panel_x", node["x"])),
        "y": int(node["y"]) - offset,
    }


def _map_fingerprint(image) -> bytes:
    """Return a motion-tolerant horizontal difference hash for the map area."""
    map_area = image[100:600, 0:1280]
    reduced = cv2.resize(map_area, (17, 8), interpolation=cv2.INTER_AREA)
    reduced = cv2.GaussianBlur(reduced, (5, 5), 0)
    comparisons = cv2.compare(reduced[:, 1:], reduced[:, :-1], cv2.CMP_GT)
    return bytes((comparisons.reshape(-1) > 0).tolist())


def _same_panel(first: bytes, second: bytes, max_changed_bits: int = 12) -> bool:
    """Treat animated-frame changes as the same scroll position.

    Live captures include moving particles and UI effects. Larger differences
    are handled by the guarded mover's semantic OCR fallback rather than by
    weakening this panel identity check.
    """
    return len(first) == len(second) and sum(a != b for a, b in zip(first, second)) <= max_changed_bits


def _unique_start_id(nodes: list[dict]) -> str | None:
    """Return a start only when exactly one detected node proves it."""
    starts = [node for node in nodes if node.get("type") == "area_start" and node.get("id")]
    return str(starts[0]["id"]) if len(starts) == 1 else None


def _left_edge_visual_start(image) -> bool:
    """Recognize the unlabelled S/player platform on the left-edge panel."""
    if image is None or getattr(image, "ndim", 0) != 3:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 160), (180, 255, 255))
    mask[:120] = 0
    mask[620:] = 0
    _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    # On the left-edge panel the player platform is around x=220..360;
    # the former 450..700 range described a middle-panel position and caused
    # valid starts to be swiped away before scanning.
    return any(150 <= int(x) <= 450 and 220 <= int(y) <= 380
               and 100 <= int(w) <= 260 and 80 <= int(h) <= 220
               and 3000 <= int(area) <= 15000
               for x, y, w, h, area in stats[1:])


def _labyrinth_anchor_visible(capture: AdbScreenCapture, probe=None) -> bool:
    # The live boss-map template is a stronger safety signal than OCR here:
    # the current map screen often contains no readable "ラビリンス/迷宮"
    # label even though the screen identity is unambiguous.
    if probe is not None:
        try:
            if probe.observe_screen() == "boss_map":
                return True
        except Exception:
            pass
    path = ROOT / "data/observations/live/map_anchor_probe.png"
    capture.capture(path)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(path))
    except Exception:
        return False
    text = "".join(line.text for line in lines if line.confidence >= 0.75)
    return "ラビリンス" in text or "迷宮" in text


def _stable_boss_map(probe, attempts: int = 5) -> bool:
    """Allow brief probe jitter, but never authorize a different screen."""
    for _ in range(attempts):
        if probe.observe_screen() == "boss_map":
            return True
        time.sleep(0.08)
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ラビリンスマップの座標付きノードを取得")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--min-confidence", type=float, default=0.80)
    parser.add_argument("--pan-right", action="store_true", help="1画面分右へ移動して再スキャン")
    parser.add_argument("--full-scan", action="store_true", help="右端まで走査し、同じ操作で左端へ戻る")
    parser.add_argument("--max-swipes", type=int, default=12)
    parser.add_argument(
        "--columns", type=int,
        help="既知の列数。Sを1列目とする場合、列移動(columns-1)＋端確認1回に自動設定",
    )
    parser.add_argument("--reuse-scan", type=Path,
                        help="検証済みスキャンJSONを再利用し、ADBスワイプ/OCRを省略")
    parser.add_argument("--current-node-id",
                        help="再開時にAIが補填する現在ノードID（reuse-scan時のみ）")
    args = parser.parse_args()
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("min-confidence must be between 0 and 1")
    if args.columns is not None and args.columns < 2:
        parser.error("columns must be at least 2")
    if args.columns is not None:
        args.max_swipes = args.columns
    if args.max_swipes < 1:
        parser.error("max-swipes must be positive")
    # A full scan is allowed up to three complete attempts.  The child
    # process owns one attempt so every retry starts from a fresh OCR/capture
    # lifecycle; a failed attempt never becomes reusable scan data.
    if args.full_scan and os.environ.get("L03_FULL_SCAN_ATTEMPT") != "1":
        last_stdout = ""
        last_stderr = ""
        for attempt in range(1, 4):
            child_env = os.environ.copy()
            child_env["L03_FULL_SCAN_ATTEMPT"] = "1"
            try:
                completed = subprocess.run(
                    [sys.executable, *sys.argv],
                    cwd=str(ROOT),
                    env=child_env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
            except subprocess.TimeoutExpired as exc:
                last_stdout = exc.stdout or ""
                last_stderr = (exc.stderr or "") + f"full_scan_attempt_timeout:{attempt}:90s\n"
                continue
            last_stdout = completed.stdout
            last_stderr = completed.stderr
            if completed.returncode == 0:
                print(last_stdout, end="")
                return 0
        if last_stdout:
            try:
                result = json.loads(last_stdout.strip().splitlines()[-1])
                if isinstance(result, dict):
                    result["full_scan_attempts"] = 3
                    print(json.dumps(result, ensure_ascii=False))
                else:
                    print(last_stdout, end="")
            except (json.JSONDecodeError, IndexError):
                print(last_stdout, end="")
        if last_stderr:
            print(last_stderr, file=sys.stderr, end="")
        return 2
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    if args.reuse_scan is not None:
        try:
            reused = json.loads(args.reuse_scan.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"reuse_scan_read_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
        if not isinstance(reused, dict) or not isinstance(reused.get("nodes"), list) or not isinstance(reused.get("verified_edges"), list):
            print(json.dumps({"status": "safety_stop", "reason": "reuse_scan_schema_invalid"}, ensure_ascii=False))
            return 2
        if probe.observe_screen() != "boss_map":
            print(json.dumps({"status": "safety_stop", "reason": "reuse_scan_requires_boss_map"}, ensure_ascii=False))
            return 2
        result = dict(reused)
        result["status"] = "scanned"
        result["mode"] = "reused"
        result["reused_from"] = str(args.reuse_scan)
        if args.current_node_id is not None:
            node_ids = {str(node.get("id")) for node in result["nodes"] if isinstance(node, dict)}
            if args.current_node_id not in node_ids:
                print(json.dumps({"status": "safety_stop", "reason": "reuse_current_node_not_in_scan"}, ensure_ascii=False))
                return 2
            result["current_node_id"] = args.current_node_id
            result["start_id"] = args.current_node_id
            # Older snapshots can retain edges to deduplicated area_start
            # nodes.  Reused graphs must obey the same endpoint integrity gate
            # as fresh scans.
            result["verified_edges"] = [
                edge for edge in result["verified_edges"]
                if str(edge.get("from")) in node_ids and str(edge.get("to")) in node_ids
            ]
        (ROOT / "output").mkdir(parents=True, exist_ok=True)
        (ROOT / "output" / "l03_map_scan_live_current.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    frame = ROOT / "data/observations/live/task_scan_map.png"
    def capture_hash() -> bytes:
        capture.capture(frame)
        image = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError("capture_failed")
        return _map_fingerprint(image)
    capture.capture(frame)
    try:
        ocr = OCRServiceAdapter(language="jpn")
        lines = _recognize_map(ocr, frame)
        area_number = _detect_area_number(ocr, frame)
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    all_text = "".join(line.text for line in lines)
    if probe.observe_screen() != "boss_map" and "ラビリンス" not in all_text and "迷宮" not in all_text:
        print(json.dumps({"status": "safety_stop", "reason": "labyrinth_map_anchor_not_confirmed"}, ensure_ascii=False))
        return 2
    if args.full_scan:
        # Keep one OCR instance for all panels; the screen guard is template
        # based and therefore does not initialize OCR for every swipe.
        try:
            # Start from the actual left edge.  A resume can begin in the
            # middle of the map, so the first scan must not be treated as S.
            left_edge_confirmed = False
            # The left edge is authoritative when the only area_start node is
            # visible.  This is stronger than waiting for a pixel-difference
            # plateau, which can fail with animated map backgrounds.
            initial_image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
            if (_unique_start_id(extract_map_nodes(lines, min_confidence=args.min_confidence)) is not None
                    or _left_edge_visual_start(initial_image)):
                left_edge_confirmed = True
            for _ in range(args.max_swipes):
                if left_edge_confirmed:
                    break
                previous = capture_hash()
                run_adb_swipe(MAP_PAN_LEFT_START, MAP_PAN_LEFT_END, serial=args.serial, healthcheck=True,
                              screen_guard=lambda: _stable_boss_map(probe),
                              task_name="map_scan_pan_left_to_edge")
                time.sleep(0.25)
                current = capture_hash()
                candidate_lines = _recognize_map(ocr, frame)
                candidate_nodes = extract_map_nodes(candidate_lines, min_confidence=args.min_confidence)
                candidate_image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
                player_start = (detect_player_node(candidate_image, candidate_image)
                                if candidate_image is not None else None)
                if (_unique_start_id(candidate_nodes) is not None
                        or _left_edge_visual_start(candidate_image)
                        or (player_start is not None and 450 <= int(player_start.get("x", 0)) <= 700)
                        or _same_panel(current, previous)):
                    left_edge_confirmed = True
                    break
            if not left_edge_confirmed:
                print(json.dumps({"status": "safety_stop", "reason": "map_scan_left_edge_not_confirmed"}, ensure_ascii=False))
                return 2

            # Re-capture and OCR the confirmed left edge.  This is the only
            # panel eligible to contain S; a resume screen may have nodes on
            # the left, but those remain ordinary prior-progress nodes.
            left_edge_hash = capture_hash()
            left_edge_image = cv2.imread(str(frame))
            left_edge_lines = _recognize_map(ocr, frame)
            panel_hashes = [left_edge_hash]
            cv2.imwrite(str(ROOT / "data/observations/live/task_scan_map_panel_0.png"), left_edge_image)
            panel_lines = [left_edge_lines]
            for _ in range(args.max_swipes):
                # When the caller supplies the authoritative column count,
                # the requested right edge is reached after that many
                # panels.  Do not perform an extra swipe and rely on an
                # animated-background pixel plateau.
                if args.columns is not None and len(panel_lines) >= args.columns:
                    break
                previous = panel_hashes[-1]
                run_adb_swipe(MAP_PAN_START, MAP_PAN_END, serial=args.serial, healthcheck=True,
                              screen_guard=lambda: _stable_boss_map(probe),
                              task_name="map_scan_pan_right")
                time.sleep(0.25)
                current = capture_hash()
                if _same_panel(current, previous):
                    break
                panel_hashes.append(current)
                panel_lines.append(_recognize_map(ocr, frame))
                cv2.imwrite(
                    str(ROOT / f"data/observations/live/task_scan_map_panel_{len(panel_lines) - 1}.png"),
                    cv2.imread(str(frame)),
                )
            else:
                if args.columns is None or len(panel_lines) < args.columns:
                    print(json.dumps({"status": "safety_stop", "reason": "map_scan_right_edge_not_confirmed"}, ensure_ascii=False))
                    return 2
            returned_left = False
            for _ in range(args.max_swipes):
                if _same_panel(capture_hash(), left_edge_hash):
                    returned_left = True
                    break
                run_adb_swipe(MAP_RETURN_START, MAP_RETURN_END, serial=args.serial, healthcheck=True,
                              screen_guard=lambda: _stable_boss_map(probe),
                              task_name="map_scan_return_left")
                time.sleep(0.25)
                capture_hash()
            if not returned_left:
                print(json.dumps({"status": "safety_stop", "reason": "map_scan_left_edge_not_confirmed"}, ensure_ascii=False))
                return 2
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"map_scan_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
        nodes = []
        player_reference = left_edge_image
        for panel, lines_for_panel in enumerate(panel_lines):
            panel_nodes_from_ocr = extract_map_nodes(lines_for_panel, min_confidence=args.min_confidence)
            for node in panel_nodes_from_ocr:
                # The fixed progress bar contains BOSS labels near y=50 and is
                # not a tappable map node.  Panel-local OCR IDs and x positions
                # must also be made unique/global before graph derivation.
                # ROI OCR includes the fixed progress bar.  Exclude only its
                # BOSS labels; top-row EVENT/NORMAL tiles remain valid map nodes.
                if str(node.get("type", "")) == "area_boss" and int(node["y"]) < 210:
                    continue
                nodes.append({
                    **node,
                    "id": f"panel_{panel}_{node['id']}",
                    "x": int(node["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                    "panel_x": int(node["x"]),
                    "panel": panel,
                    "panel_fingerprint": panel_hashes[panel].hex(),
                })
            panel_image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
            if panel_image is not None:
                # OCR may see only one of vertically stacked EVENT badges.
                # Use only OCR-confirmed event artwork as a template seed;
                # this supplements, rather than guesses beyond, OCR.
                event_seeds = [
                    node for node in panel_nodes_from_ocr
                    if str(node.get("type", "")) == "event"
                ]
                for node in detect_event_nodes(panel_image, event_seeds):
                    nodes.append({
                        **node,
                        "id": f"panel_{panel}_{node['id']}",
                        "x": int(node["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                        "panel_x": int(node["x"]),
                        "panel": panel,
                        "panel_fingerprint": panel_hashes[panel].hex(),
                    })
            # The left-edge frame is the authoritative current-position frame.
            # Restrict the pale-character fallback to that frame; overlapping
            # later panels can contain bright enemy/artwork components that
            # otherwise become duplicate player markers.
            player = detect_player_node(panel_image, player_reference) if panel_image is not None and panel == 0 else None
            if player is not None:
                player.update({
                    "id": f"panel_{panel}_{player['id']}",
                    "x": int(player["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                    "panel_x": int(player["x"]),
                    "panel": panel,
                    "panel_fingerprint": panel_hashes[panel].hex(),
                })
                nodes.append(player)
        relic_reference = cv2.imread(str(ROOT / "data/observations/live/relic_reference.png"))
        sign_reference = cv2.imread(str(ROOT / "data/observations/live/connect_sign_reference.png"))
        # A terminal chest needs its own reference.  Never reuse the relic
        # image, or the relic will be emitted as a false area_exit node.
        exit_reference_path = ROOT / "data/observations/live/area_exit_reference.png"
        reference = cv2.imread(str(exit_reference_path)) if exit_reference_path.exists() else None
        # The terminal chest remains visible in several overlapping panels.
        # Detect it in every captured panel so at least one observation shares
        # a panel with the preceding connector.  The normal physical-tile
        # deduplication below collapses these repeated observations; limiting
        # detection to the final panel leaves the terminal isolated and makes
        # a real route appear unreachable.
        if reference is not None:
            for panel in range(len(panel_lines)):
                panel_path = ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"
                panel_image = cv2.imread(str(panel_path))
                terminal = detect_terminal_chest(panel_image, reference)
                if terminal is None:
                    continue
                terminal.update({
                    "id": f"panel_{panel}_{terminal['id']}",
                    "x": int(terminal["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                    "panel_x": int(terminal["x"]),
                    "panel": panel,
                    "panel_fingerprint": panel_hashes[panel].hex(),
                })
                nodes.append(terminal)
        if sign_reference is not None:
            for panel in range(len(panel_lines)):
                panel_image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
                sign = detect_relic_node(panel_image, sign_reference, threshold=0.60) if panel_image is not None else None
                if sign is not None:
                    sign.update({
                        "id": f"panel_{panel}_connect_sign_visual",
                        "type": "connect_sign",
                        "label": "CONNECT_SIGN_VISUAL",
                        "x": int(sign["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                        "panel_x": int(sign["x"]),
                        "panel": panel,
                        "panel_fingerprint": panel_hashes[panel].hex(),
                    })
                    nodes.append(sign)
        if relic_reference is not None:
            for panel in range(len(panel_lines)):
                panel_image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
                relic = detect_relic_node(panel_image, relic_reference) if panel_image is not None else None
                if relic is not None:
                    relic.update({
                        "id": f"panel_{panel}_relic_visual",
                        "type": "relic",
                        "label": "RELIC_VISUAL",
                        "x": int(relic["x"]) + panel * MAP_PAN_WORLD_SHIFT,
                        "panel_x": int(relic["x"]),
                        "panel": panel,
                        "panel_fingerprint": panel_hashes[panel].hex(),
                    })
                    nodes.append(relic)
        if not nodes:
            print(json.dumps({"status": "safety_stop", "reason": "map_nodes_not_recognized"}, ensure_ascii=False))
            return 2
        # Template detectors can return multiple nodes with the same base ID
        # in one panel (for example, two vertically stacked event tiles).
        # Keep every observation as a separate graph vertex; otherwise the
        # later merge/edge pass silently overwrites one of the tiles.
        id_counts: dict[str, int] = {}
        for node in nodes:
            base_id = str(node.get("id", "node"))
            occurrence = id_counts.get(base_id, 0) + 1
            id_counts[base_id] = occurrence
            if occurrence > 1:
                node["id"] = f"{base_id}_{occurrence}"
        # Consecutive 350px pans overlap.  The same physical tile can
        # therefore be OCR'd in multiple panels; collapse those observations
        # before route planning while retaining the raw observations for line
        # verification below.
        raw_nodes = list(nodes)
        node_alias: dict[str, str] = {}
        unique_nodes: list[dict] = []
        for node in sorted(raw_nodes, key=lambda item: (int(item.get("x", 0)), int(item.get("y", 0)), int(item.get("panel", 0)))):
            # The live drag distance is not exactly 350px on every frame.
            # A physical tile can therefore differ by more than 180px in
            # overlapping panels.  Same-type tiles on the same row are
            # normally separated by more than this bound, so 300px removes
            # duplicate observations without collapsing adjacent columns.
            # Terminal observations can appear at the far edge of two
            # adjacent overlapping panels; they are one physical endpoint.
            # Use a wider bound only for this unique node type so ordinary
            # adjacent columns are never merged.
            merge_x_tolerance = 420 if node.get("type") == "area_exit" else 300
            match = next(
                (existing for existing in unique_nodes
                 if (existing.get("type") == node.get("type")
                     or {existing.get("type"), node.get("type")} == {"connect_sign", "event"})
                 and abs(int(existing["x"]) - int(node["x"])) <= merge_x_tolerance
                 and abs(int(existing["y"]) - int(node["y"])) <= 60),
                None,
            )
            if match is None:
                unique_nodes.append(node)
                node_alias[str(node["id"])] = str(node["id"])
            else:
                # The same icon can be classified as EVENT by OCR in one
                # overlap panel and as CONNECT_SIGN by the visual detector
                # in another.  Preserve the stricter sign classification.
                if match.get("type") == "event" and node.get("type") == "connect_sign":
                    old_id = str(match["id"])
                    match.update(node)
                    match["id"] = old_id
                    for alias, target in list(node_alias.items()):
                        if target == old_id:
                            node_alias[alias] = old_id
                node_alias[str(node["id"])] = str(match["id"])
        # A panel overlap can leave one physical column at the edge of two
        # captures with a larger-than-expected world-X gap.  Consecutive
        # columns with the exact same top-to-bottom type signature are
        # therefore merged as one column.  This is deliberately structural:
        # columns with different contents are never merged by distance alone.
        columns: list[list[dict]] = []
        for node in sorted(unique_nodes, key=lambda item: (int(item.get("x", 0)), int(item.get("y", 0)))):
            center_x = sum(int(item.get("x", 0)) for item in columns[-1]) / len(columns[-1]) if columns else None
            if not columns or abs(int(node.get("x", 0)) - float(center_x)) > 120:
                columns.append([node])
            else:
                columns[-1].append(node)
        merged_columns: list[list[dict]] = []
        for column in columns:
            signature = tuple(sorted(str(item.get("type", "")) for item in column))
            if merged_columns:
                previous = merged_columns[-1]
                previous_signature = tuple(sorted(str(item.get("type", "")) for item in previous))
                if signature == previous_signature:
                    for duplicate in column:
                        candidates = [item for item in previous if item.get("type") == duplicate.get("type")]
                        if candidates:
                            representative = min(candidates, key=lambda item: abs(int(item.get("y", 0)) - int(duplicate.get("y", 0))))
                            node_alias[str(duplicate["id"])] = str(representative["id"])
                    continue
            merged_columns.append(column)
        unique_nodes = [node for column in merged_columns for node in column]
        verified_edges = []
        for panel in range(len(panel_lines)):
            panel_nodes = [node for node in raw_nodes if node.get("panel") == panel]
            panel_image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
            if panel_image is None or len(panel_nodes) < 2:
                continue
            columns: list[list[dict]] = []
            for node in sorted(panel_nodes, key=lambda item: float(item.get("panel_x", item["x"]))):
                x = float(node.get("panel_x", node["x"]))
                if not columns or x - float(columns[-1][0].get("panel_x", columns[-1][0]["x"])) > 120:
                    columns.append([node])
                else:
                    columns[-1].append(node)
            for left_column, right_column in zip(columns, columns[1:]):
                for left_node in left_column:
                    for right_node in right_column:
                        score = connection_score(
                            panel_image,
                            _connector_anchor(left_node),
                            _connector_anchor(right_node),
                        )
                        if score >= EDGE_SCORE_THRESHOLD:
                            left_id = node_alias.get(str(left_node["id"]), str(left_node["id"]))
                            right_id = node_alias.get(str(right_node["id"]), str(right_node["id"]))
                            if left_id != right_id:
                                verified_edges.append({"from": left_id, "to": right_id,
                                                       "panel": panel, "score": round(score, 4)})
        # A visual CONNECT_SIGN can be omitted as a column-group source when
        # OCR produces a nearby event row in an overlap panel.  Re-check its
        # immediate rightward candidates independently, preserving only a
        # continuous, threshold-passing connector.
        for panel in range(len(panel_lines)):
            panel_image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
            panel_nodes = [node for node in raw_nodes if node.get("panel") == panel]
            for sign in [node for node in panel_nodes if node.get("type") == "connect_sign"]:
                candidates = [node for node in panel_nodes
                              if float(node.get("panel_x", node.get("x", 0)))
                              > float(sign.get("panel_x", sign.get("x", 0)))
                              and node.get("type") != "connect_sign"]
                if panel_image is None or not candidates:
                    continue
                target = min(candidates, key=lambda node: float(node.get("panel_x", node.get("x", 0))))
                score = connection_score(panel_image, _connector_anchor(sign), _connector_anchor(target))
                left_id = node_alias.get(str(sign["id"]), str(sign["id"]))
                right_id = node_alias.get(str(target["id"]), str(target["id"]))
                if score >= EDGE_SCORE_THRESHOLD and left_id != right_id:
                    verified_edges.append({"from": left_id, "to": right_id,
                                           "panel": panel, "score": round(score, 4),
                                           "source": "connect_sign_independent_check"})
        # Validate a sign-to-next-column connector when the two endpoints are
        # split across overlapping captures.  Both endpoints are projected
        # into each panel's local coordinates; only a measured rail above the
        # normal threshold is retained.
        for sign in [node for node in unique_nodes if node.get("type") == "connect_sign"]:
            next_nodes = [node for node in unique_nodes
                          if float(node.get("x", 0)) > float(sign.get("x", 0)) + 120
                          and node.get("type") != "connect_sign"]
            if not next_nodes:
                continue
            target = min(next_nodes, key=lambda node: float(node.get("x", 0)))
            for panel in range(len(panel_lines)):
                image = cv2.imread(str(ROOT / f"data/observations/live/task_scan_map_panel_{panel}.png"))
                if image is None:
                    continue
                left = {**sign, "x": float(sign["x"]) - panel * MAP_PAN_WORLD_SHIFT}
                right = {**target, "x": float(target["x"]) - panel * MAP_PAN_WORLD_SHIFT}
                if not (0 <= left["x"] < 1280 and 0 <= right["x"] < 1280):
                    continue
                score = connection_score(image, _connector_anchor(left), _connector_anchor(right))
                if score >= EDGE_SCORE_THRESHOLD:
                    left_id = str(sign["id"])
                    right_id = str(target["id"])
                    verified_edges.append({"from": left_id, "to": right_id,
                                           "panel": panel, "score": round(score, 4),
                                           "source": "connect_sign_cross_panel_check"})
                    break
        # Column deduplication can remove a representative node after an
        # overlap edge was collected.  Such stale endpoints must not poison
        # the otherwise valid verified graph.
        valid_node_ids = {str(node.get("id")) for node in unique_nodes}
        verified_edges = [edge for edge in verified_edges
                          if str(edge.get("from")) in valid_node_ids
                          and str(edge.get("to")) in valid_node_ids]
        # A player marker is not necessarily the Area 1 start: after a move
        # the same visual marker sits on the current NORMAL/SIGN/etc. tile.
        # Rebind an unlabelled marker to exactly one nearby scanned tile so a
        # resumed scan cannot keep treating the old start as the current node.
        player_markers = [node for node in unique_nodes if node.get("type") == "area_start"]
        current_node_id: str | None = None
        marker_bindings: list[tuple[dict, dict]] = []
        for marker in player_markers:
            if str(marker.get("label", "")) == "CLEAR_CURRENT":
                # CLEAR is the authoritative current tile after a resolved
                # battle.  Do not bind it to a nearby OCR tile: that creates
                # a false same-column vertical move.
                current_node_id = str(marker["id"])
                continue
            candidates = [node for node in unique_nodes if node.get("type") != "area_start"]
            nearby = [node for node in candidates
                      if abs(int(node.get("x", 0)) - int(marker.get("x", 0))) <= 130
                      and abs(int(node.get("y", 0)) - int(marker.get("y", 0))) <= 130]
            if len(nearby) == 1:
                marker_bindings.append((marker, nearby[0]))
        if current_node_id is None and len(marker_bindings) == 1:
                marker, target = marker_bindings[0]
                current_node_id = str(target["id"])
                target["current_player"] = True
                # Other area_start markers are duplicate/false candidates;
                # they must not become graph vertices or alternate starts.
                unique_nodes = [node for node in unique_nodes if node.get("type") != "area_start"]
                valid_ids = {str(node["id"]) for node in unique_nodes}
                verified_edges = [edge for edge in verified_edges
                                  if str(edge.get("from")) in valid_ids
                                  and str(edge.get("to")) in valid_ids]
        # A CLEAR tile is a resolved current position, not an OCR tile, so it
        # is excluded from ordinary line pairing.  The game guarantees a
        # rightward continuation; attach it only to the nearest strictly
        # right-hand column, never to a same-column vertical tile.
        clear_marker = next(
            (node for node in unique_nodes
             if node.get("type") == "area_start" and node.get("label") == "CLEAR_CURRENT"),
            None,
        )
        # 呼び出し側が直前の戦闘結果などで現在地を明示した場合は、
        # 自動マーカー推定より優先する。未確認のIDは受け付けない。
        if args.current_node_id is not None:
            valid_ids = {str(node.get("id")) for node in unique_nodes}
            if args.current_node_id not in valid_ids:
                print(json.dumps({"status": "safety_stop", "reason": "current_node_not_in_scan"}, ensure_ascii=False))
                return 2
            current_node_id = args.current_node_id
            unique_nodes = [node for node in unique_nodes
                            if node.get("type") != "area_start"
                            or str(node.get("id")) == args.current_node_id]
            if clear_marker is not None and str(clear_marker.get("id")) != args.current_node_id:
                clear_marker = None
        if clear_marker is not None:
            marker_x = int(clear_marker.get("x", 0))
            right_nodes = [node for node in unique_nodes
                           if node.get("type") != "area_start"
                           and int(node.get("x", 0)) >= marker_x + 150]
            if right_nodes:
                next_x = min(int(node["x"]) for node in right_nodes)
                valid_ids = {str(edge.get("to")) for edge in verified_edges
                             if str(edge.get("from")) == str(clear_marker["id"])}
                for node in right_nodes:
                    if int(node["x"]) == next_x and str(node["id"]) not in valid_ids:
                        verified_edges.append({"from": str(clear_marker["id"]),
                                                "to": str(node["id"]),
                                                "panel": int(node.get("panel", 0)),
                                                "score": 1.0,
                                                "source": "known_rightward_continuation"})
        # Keep one observation per physical tile in the downstream graph.
        start_id = current_node_id or _unique_start_id(unique_nodes)
        result = {"status": "scanned", "mode": "full", "panels": len(panel_lines), "nodes": unique_nodes,
                  "verified_edges": verified_edges, "left_edge_confirmed": True, "returned_left": True}
        if area_number is not None:
            result["area_number"] = area_number
        if start_id is not None:
            result["start_id"] = start_id
        if current_node_id is not None:
            result["current_node_id"] = current_node_id
        # Keep the exact raw full-scan result for the L-03 preflight and later
        # route replay.  Stdout remains the machine-readable CLI result.
        (ROOT / "output").mkdir(parents=True, exist_ok=True)
        (ROOT / "output" / "l03_map_scan_live_current.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.pan_right:
        try:
            run_adb_swipe(MAP_PAN_START, MAP_PAN_END, serial=args.serial, healthcheck=True,
                          screen_guard=lambda: _labyrinth_anchor_visible(capture, probe), task_name="map_scan_pan_right")
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"map_swipe_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
        capture.capture(frame)
        try:
            lines = _recognize_map(ocr, frame)
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed_after_swipe:{type(exc).__name__}"}, ensure_ascii=False))
            return 2
    nodes = [
        node for node in extract_map_nodes(lines, min_confidence=args.min_confidence)
        if not (str(node.get("type", "")) == "area_boss" and int(node.get("y", 0)) < 210)
    ]
    if not nodes:
        print(json.dumps({"status": "safety_stop", "reason": "map_nodes_not_recognized"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "scanned", "nodes": nodes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
