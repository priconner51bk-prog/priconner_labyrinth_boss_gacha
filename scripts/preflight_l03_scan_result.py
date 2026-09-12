"""Validate a saved L-03 full-scan result without touching ADB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decision.route_planner import AREA1_REQUIRED_TYPES, find_route_node_path, find_route_node_sequence, spatial_map_graph, verified_map_graph


def validate_scan_result(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("status") != "scanned":
        return {"status": "safety_stop", "reason": "saved_scan_status_not_scanned"}
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return {"status": "safety_stop", "reason": "saved_scan_nodes_missing"}
    # Prefer the scanner's explicit current position.  Re-deriving a start
    # from the leftmost pixel is retained only for legacy saved fixtures that
    # predate start_id; current live scans are required to emit start_id.
    declared_start = str(payload.get("start_id", "")).strip()
    if not declared_start:
        legacy_graph = spatial_map_graph(nodes)
        if legacy_graph is None:
            return {"status": "safety_stop", "reason": "scan_start_id_missing"}
        declared_start = str(legacy_graph["start"])
    positions = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    if declared_start not in positions:
        return {"status": "safety_stop", "reason": "scan_start_id_not_in_nodes", "start": declared_start}
    edges = payload.get("verified_edges")
    verified = verified_map_graph(nodes, edges, start=declared_start) if isinstance(edges, list) else None
    if verified is None:
        return {"status": "safety_stop", "reason": "connection_evidence_missing_or_invalid"}
    route = find_route_node_sequence(verified, start=str(verified["start"]), required_types=AREA1_REQUIRED_TYPES)
    if not route:
        route = find_route_node_path(
            verified, start=str(verified["start"]), goal_types=("area_boss", "area_exit")
        )
        if not route:
            return {"status": "safety_stop", "reason": "no_reachable_route"}
        policy_warning = "preferred_area1_sequence_not_observed"
    else:
        policy_warning = None
    for node_id in route:
        node = positions.get(node_id, {})
        if node.get("panel") is not None and (
            node.get("panel_x") is None or not node.get("panel_fingerprint")
        ):
            return {"status": "safety_stop", "reason": "route_node_panel_metadata_missing", "node": node_id}
    result = {
        "status": "ready",
        "start": declared_start,
        "route": route,
        "next_local_screen": "boss_map",
        "resume_rule": "observe current screen first; do not tap unless boss_map is confirmed",
    }
    if policy_warning:
        result["policy_warning"] = policy_warning
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="L-03保存済みfull-scan JSONの読み取り専用preflight")
    parser.add_argument("scan_result", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.scan_result.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        result = {"status": "safety_stop", "reason": f"saved_scan_unreadable:{type(exc).__name__}"}
    else:
        result = validate_scan_result(payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
