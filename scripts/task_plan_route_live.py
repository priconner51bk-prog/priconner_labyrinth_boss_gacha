"""取得済みマップ接続グラフからルートを計画する（task_種別）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decision.route_planner import (
    AREA1_REQUIRED_TYPES,
    TILE_PRIORITY,
    find_route,
    find_route_node_sequence,
    normalize_map_graph,
    verified_map_graph,
)


def _find_area2_frontier_route(graph: dict, start: str) -> list[str] | None:
    """エリア2の必須EXTREME経由・最終遺物までの経路を返す。"""
    nodes = graph.get("nodes")
    if not isinstance(nodes, dict) or start not in nodes:
        return None
    priority = {tile: index for index, tile in enumerate(TILE_PRIORITY)}
    memo: dict[tuple[str, bool, frozenset[str]], tuple[str, ...] | None] = {}

    def walk(node_id: str, trail: frozenset[str], has_extreme: bool) -> tuple[str, ...] | None:
        key = (node_id, has_extreme, trail)
        if key in memo:
            return memo[key]
        node = nodes.get(node_id, {})
        node_type = str(node.get("type", ""))
        next_ids = [str(value) for value in node.get("next", []) if str(value) not in trail]
        if not next_ids:
            result = () if node_type == "relic" and has_extreme else None
            memo[key] = result
            return result
        candidates = []
        for next_id in next_ids:
            next_type = str(nodes[next_id].get("type", ""))
            tail = walk(next_id, trail | {next_id}, has_extreme or next_type == "extreme")
            if tail is None:
                continue
            candidates.append((len(tail) + 1, -priority.get(next_type, len(priority)), tuple(tail), next_id))
        if not candidates:
            memo[key] = None
            return None
        best = max(candidates)
        result = (best[3],) + best[2]
        memo[key] = result
        return result

    result = walk(start, frozenset({start}), False)
    return list(result) if result is not None and result else None


def _inject_area2_known_goal(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], bool]:
    """Add the preconfirmed Area 2 column-7 relic without icon/line OCR.

    The user-confirmed map contract makes the last tile a relic and the
    column-6-to-7 transition valid.  This is not a visual inference: the
    synthetic node is explicitly marked as a known constraint.  Existing
    scanned edges are otherwise left untouched.
    """
    if any(str(node.get("id", "")) == "area2_known_col7_relic" for node in nodes):
        return nodes, edges, False
    positioned = []
    for node in nodes:
        try:
            positioned.append((float(node["x"]), str(node["id"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not positioned:
        return nodes, edges, False
    rightmost = max(x for x, _ in positioned)
    last_column = [node_id for x, node_id in positioned if rightmost - x <= 120]
    if not last_column:
        return nodes, edges, False
    goal_id = "area2_known_col7_relic"
    augmented_nodes = [dict(node) for node in nodes]
    augmented_nodes.append({
        "id": goal_id,
        "type": "relic",
        "label": "AREA2_KNOWN_COL7_RELIC",
        "known_constraint": "user_rule.route.area2_structure",
    })
    augmented_edges = [dict(edge) for edge in edges]
    for source in last_column:
        augmented_edges.append({
            "from": source,
            "to": goal_id,
            "reason": "user_rule.route.area2_structure",
        })
    return augmented_nodes, augmented_edges, True


def _adjacent_right_edges(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Reject same-column and skipped-column edges from stale/overlapped scans."""
    positioned: list[tuple[float, str]] = []
    for node in nodes:
        try:
            positioned.append((float(node["x"]), str(node["id"])))
        except (KeyError, TypeError, ValueError):
            return []
    columns: list[list[str]] = []
    centers: list[float] = []
    for x, node_id in sorted(positioned):
        if not columns or x - centers[-1] > 120:
            columns.append([node_id])
            centers.append(x)
        else:
            columns[-1].append(node_id)
            centers[-1] = sum(value for value, _ in positioned if _ in columns[-1]) / len(columns[-1])
    index = {node_id: column_index for column_index, column in enumerate(columns) for node_id in column}
    return [
        dict(edge) for edge in edges
        if index.get(str(edge.get("to"))) == index.get(str(edge.get("from")), -2) + 1
    ]


def _inject_area2_col4_relic(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], bool]:
    """Represent the preconfirmed second tile in Area 2 column 4.

    The scan can OCR the SHOP label while missing the icon-only relic in the
    same column.  Preserve the observed SHOP topology as the column-4
    transition topology, but expose the user-confirmed relic as the selected
    tile.  The caller must still resolve the relic's fixed row/coordinate
    before issuing input.
    """
    if any(str(node.get("id", "")) == "area2_known_col4_relic" for node in nodes):
        return nodes, edges, False
    shops = [node for node in nodes if str(node.get("type", "")) == "shop"]
    if len(shops) != 1:
        return nodes, edges, False
    shop = shops[0]
    shop_id = str(shop.get("id", ""))
    if not shop_id:
        return nodes, edges, False
    relic_id = "area2_known_col4_relic"
    augmented_nodes = [dict(node) for node in nodes]
    relic = {
        "id": relic_id,
        "type": "relic",
        "label": "AREA2_KNOWN_COL4_RELIC",
        "known_constraint": "user_rule.route.area2_structure",
        "source_column_node": shop_id,
    }
    for key in ("x", "panel_x", "panel"):
        if key in shop:
            relic[key] = shop[key]
    augmented_nodes.append(relic)
    augmented_edges = [dict(edge) for edge in edges]
    for edge in edges:
        if str(edge.get("to")) == shop_id:
            augmented_edges.append({**edge, "to": relic_id, "reason": "user_rule.route.area2_structure"})
        if str(edge.get("from")) == shop_id:
            augmented_edges.append({**edge, "from": relic_id, "reason": "user_rule.route.area2_structure"})
    return augmented_nodes, augmented_edges, True


def _write_safety_stop(reason: str, **details: object) -> int:
    result: dict[str, object] = {"status": "safety_stop", "reason": reason, **details}
    output = ROOT / "output/l03_route_live_current.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="マップ接続グラフから安全なルートを生成")
    parser.add_argument("--graph", type=Path, required=True, help="nodesを含むJSONファイル")
    parser.add_argument("--start", required=True, help="開始ノードID")
    parser.add_argument("--area", type=int, required=True)
    parser.add_argument("--relic-level-total", type=int, default=0)
    parser.add_argument("--signs-reached", type=int, default=0,
                        help="AIが補填するArea 1のCONNECT_SIGN到達済み回数")
    args = parser.parse_args()
    if args.area not in range(1, 6) or args.relic_level_total < 0 or not 0 <= args.signs_reached <= 2:
        parser.error("area or relic level is invalid")
    try:
        raw = json.loads(args.graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _write_safety_stop(f"graph_read_failed:{type(exc).__name__}")
    # A live scan is a snapshot.  Never accept a start node supplied from an
    # older scan/session: doing so can produce a syntactically valid route
    # whose node IDs do not belong to the current map.
    if isinstance(raw, dict) and isinstance(raw.get("nodes"), list):
        snapshot_start = str(raw.get("start_id", "")).strip()
        if not snapshot_start:
            return _write_safety_stop("scan_start_id_missing")
        if args.start != snapshot_start:
            return _write_safety_stop(
                "start_node_does_not_match_scan",
                requested_start=args.start,
                scan_start=snapshot_start,
            )
    # Live scanner output stores node records and evidence-backed edges at the
    # top level, while fixture graphs use the compact {nodes:{...}} schema.
    known_goal_injected = False
    known_col4_relic_injected = False
    if isinstance(raw, dict) and isinstance(raw.get("nodes"), list) and isinstance(raw.get("verified_edges"), list):
        scan_nodes = raw["nodes"]
        scan_edges = _adjacent_right_edges(scan_nodes, raw["verified_edges"])
        if args.area == 2:
            scan_nodes, scan_edges, known_col4_relic_injected = _inject_area2_col4_relic(scan_nodes, scan_edges)
            scan_nodes, scan_edges, known_goal_injected = _inject_area2_known_goal(scan_nodes, scan_edges)
        graph = verified_map_graph(scan_nodes, scan_edges, start=args.start)
    else:
        graph = normalize_map_graph(raw)
    if graph is None:
        return _write_safety_stop("map_connections_missing_or_invalid")
    if args.area == 1:
        # After both mandatory signs have already been reached, plan only the
        # remaining relic leg.  Replaying the full sequence from the current
        # tile would incorrectly demand two additional signs.
        required_types = ("relic",) if args.signs_reached >= 2 else AREA1_REQUIRED_TYPES
        # The start node is the already-resolved current tile and is excluded
        # from the returned path.  Consume the matching first requirement so
        # a NORMAL battle just completed is not demanded again as a future hop.
        start_type = str(graph["nodes"].get(args.start, {}).get("type", ""))
        if args.signs_reached == 1 and start_type == "connect_sign":
            required_types = ("normal", "connect_sign", "relic")
        elif args.signs_reached == 1 and start_type == "normal":
            # NORMAL after the first sign is already resolved; only the
            # second sign and terminal relic remain.
            required_types = ("connect_sign", "relic")
        if required_types and start_type == required_types[0]:
            required_types = required_types[1:]
        node_route = find_route_node_sequence(
            graph, start=args.start, required_types=required_types,
            allow_intermediates=True,
        )
        route = [graph["nodes"][node_id]["type"] for node_id in node_route] if node_route else None
    elif args.area == 2:
        node_route = _find_area2_frontier_route(graph, args.start)
        route = [graph["nodes"][node_id]["type"] for node_id in node_route] if node_route else None
    else:
        route = find_route(
            graph, start=args.start,
            avoid_hell=args.area in {4, 5} and args.relic_level_total >= 15,
        )
    if not route:
        return _write_safety_stop("no_reachable_route_target", start=args.start, area=args.area)
    result = {"status": "planned", "route": route, "area": args.area,
              "start": args.start, "signs_reached": args.signs_reached}
    if known_goal_injected:
        result["known_goal"] = "area2_known_col7_relic"
        result["known_goal_source"] = "user_rule.route.area2_structure"
    if known_col4_relic_injected:
        result["known_col4_relic"] = "area2_known_col4_relic"
        result["known_col4_relic_source"] = "user_rule.route.area2_structure"
    if args.area == 1:
        result["node_route"] = node_route
    if args.area == 2:
        result["node_route"] = node_route
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
