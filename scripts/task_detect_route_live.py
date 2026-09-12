"""全域マップスキャン結果から、決め打ちルールで接続とルートを生成する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decision.route_planner import AREA1_REQUIRED_TYPES, find_route_node_path, find_route_node_sequence, verified_map_graph


def _write_safety_stop(reason: str, **details: object) -> int:
    """Publish a non-route result so stale route JSON cannot be consumed."""
    result: dict[str, object] = {"status": "safety_stop", "reason": reason, **details}
    output = ROOT / "output/l03_route_live_current.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", type=Path, default=ROOT / "output/l03_map_scan_live_current.json")
    parser.add_argument("--area", type=int, default=1)
    parser.add_argument("--relic-level-total", type=int, default=0)
    args = parser.parse_args()
    try:
        raw = json.loads(args.scan.read_text(encoding="utf-8"))
        nodes = raw.get("nodes") if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        return _write_safety_stop(f"scan_read_failed:{type(exc).__name__}")
    if not isinstance(nodes, list):
        return _write_safety_stop("scan_nodes_missing")
    # Never turn proximity into a live connection.  The scanner must provide
    # explicitly verified edges from connector-line detection; otherwise a
    # route would be a guess and must be rejected.
    verified_edges = raw.get("verified_edges") if isinstance(raw, dict) else None
    if not isinstance(verified_edges, list) or not verified_edges:
        return _write_safety_stop("connection_evidence_missing")
    by_id = {str(node.get("id", "")): node for node in nodes if isinstance(node, dict)}
    start = str(raw.get("start_id", "")).strip()
    if not start or start not in by_id:
        return _write_safety_stop("start_marker_not_confirmed", start=start or None)
    graph = verified_map_graph(nodes, verified_edges, start=start)
    if graph is None:
        return _write_safety_stop("verified_connection_graph_invalid", start=start)
    if args.area == 1:
        path = find_route_node_sequence(graph, start=start, required_types=AREA1_REQUIRED_TYPES)
        policy_warning = None
        if not path:
            path = find_route_node_path(graph, start=start, goal_types=("area_boss", "area_exit"))
            policy_warning = "preferred_area1_sequence_not_observed" if path else None
    else:
        path = find_route_node_path(graph, start=start, avoid_hell=args.area in {4, 5} and args.relic_level_total >= 15)
        policy_warning = None
    if not path:
        return _write_safety_stop("route_not_found", start=start)
    route = {"status": "planned", "start": start, "node_path": path, "graph": graph}
    if policy_warning:
        route["policy_warning"] = policy_warning
    output = ROOT / "output/l03_route_live_current.json"
    output.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "planned", "start": start, "node_path": path, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
