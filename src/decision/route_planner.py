"""明示されたマス接続グラフからの決定論的ルート選択。"""

from __future__ import annotations

import heapq
import re
from collections.abc import Mapping, Sequence
from typing import Any


TILE_ALIASES = {
    "normal": "normal", "通常": "normal", "extreme": "extreme", "Extreme": "extreme", "EX": "extreme",
    "hell": "hell", "HELL": "hell", "relic": "relic", "遺物": "relic",
    "connect_sign": "connect_sign", "コネクトサイン": "connect_sign", "shop": "shop", "SHOP": "shop", "ショップ": "shop",
    "event": "event", "イベント": "event", "area_boss": "area_boss", "エリアボス": "area_boss",
    "area_start": "area_start", "エリアスタート": "area_start", "ボス": "area_boss",
    "area_exit": "area_exit", "エリア出口": "area_exit",
}
TILE_PRIORITY = ("extreme", "normal", "relic", "connect_sign", "shop", "event", "area_boss", "area_exit", "hell")

# Area 1 has a fixed requirement, but its row/edge choices are re-scanned for
# every run.  Only the two CONNECT_SIGN tiles and final RELIC are mandatory;
# NORMAL tiles may be used as connection intermediates and are not a route
# constraint.  Do not reintroduce the obsolete fixed NORMAL sequence.
AREA1_REQUIRED_TYPES = ("connect_sign", "connect_sign", "relic")


def verified_map_graph(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]], *, start: str) -> dict[str, Any] | None:
    """Build the graph authorized by scanner evidence only.

    Proximity-derived neighbours are never copied into this graph.  A malformed
    edge or an endpoint not present in the current scan invalidates the graph.
    Duplicate observations are harmless because edges are de-duplicated.
    """
    if not isinstance(start, str) or not start.strip():
        return None
    graph_nodes: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("id") is None:
            return None
        node_id = str(node["id"]).strip()
        tile = TILE_ALIASES.get(re.sub(r"\s+", "", str(node.get("type", ""))), "")
        if not node_id or not tile:
            return None
        graph_nodes[node_id] = {"type": tile, "next": []}
    if start not in graph_nodes or not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        return None
    for edge in edges:
        if not isinstance(edge, Mapping):
            return None
        source = str(edge.get("from", "")).strip()
        target = str(edge.get("to", "")).strip()
        if source not in graph_nodes or target not in graph_nodes:
            return None
        if target not in graph_nodes[source]["next"]:
            graph_nodes[source]["next"].append(target)
    return {"nodes": graph_nodes, "start": start}


def spatial_map_graph(
    nodes: Sequence[Mapping[str, Any]],
    *,
    max_vertical_ratio: float = 0.45,
    # Full scans use global X coordinates across adjacent panels. 0.6 rejected
    # valid panel-to-panel links in the live 3-panel scan even though each
    # candidate remained left-to-right and vertically bounded.
    max_horizontal_ratio: float = 0.8,
    max_connections: int = 4,
    allow_relic_terminal: bool = False,
) -> dict[str, Any] | None:
    """Derive a left-to-right route graph from positioned OCR map nodes.

    The labyrinth is a left-to-right branching path: each node connects to the
    nearest nodes that lie to its right and within one vertical lane.  This is
    the only place pixel proximity is used, and it is bounded so a stray label
    cannot create a shortcut across the map.  A graph is rejected (``None``)
    when it cannot reach an ``area_boss`` from the leftmost start node, so the
    caller falls back to a safe stop instead of guessing a route.
    """
    positioned = []
    for node in nodes:
        if not isinstance(node, Mapping):
            return None
        node_id = str(node.get("id", "")).strip()
        raw_type = re.sub(r"\s+", "", str(node.get("type", "")))
        tile = TILE_ALIASES.get(raw_type, "")
        try:
            x = float(node["x"])
            y = float(node["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not node_id or not tile:
            return None
        positioned.append((x, y, node_id, tile))
    if len(positioned) < 2:
        return None
    terminal_types = {"area_boss", "area_exit"}
    if allow_relic_terminal:
        terminal_types.add("relic")
    if not any(tile in terminal_types for _, _, _, tile in positioned):
        return None
    width = max(x for x, _, _, _ in positioned) - min(x for x, _, _, _ in positioned)
    height = max(y for _, y, _, _ in positioned) - min(y for _, y, _, _ in positioned)
    if width <= 0 or height <= 0:
        return None
    # OCR centre coordinates can differ by a few pixels even on a straight
    # lane. Keep the relative bound for real maps, with a small deterministic
    # floor for compact/unit-test layouts.
    vertical_limit = max(max_vertical_ratio * height, 12.0)
    horizontal_limit = max_horizontal_ratio * width
    minimum_advance = 0.05 * width
    graph: dict[str, dict[str, Any]] = {}
    for x, y, node_id, tile in positioned:
        candidates = []
        for nx, ny, nid, _ in positioned:
            if nid == node_id:
                continue
            dx = nx - x
            dy = abs(ny - y)
            if dx < minimum_advance or dx > horizontal_limit:
                continue
            if dy > vertical_limit:
                continue
            candidates.append((dx * dx + dy * dy, nid))
        candidates.sort()
        connections = [nid for _, nid in candidates[:max_connections]]
        graph[node_id] = {"type": tile, "next": connections}
    explicit_starts = [item for item in positioned if item[3] == "area_start"]
    start = (min(explicit_starts, key=lambda item: item[0])[2]
             if explicit_starts else min(positioned, key=lambda item: item[0])[2])
    candidate_graph = {"nodes": graph, "start": start}
    if find_route(candidate_graph, start=start, goal_types=tuple(terminal_types)) is None:
        return None
    return {"nodes": graph, "start": start}



def normalize_map_graph(layouts: Any) -> dict[str, dict[str, dict[str, Any]]] | None:
    """Merge panel observations into the strict graph schema used by ``find_route``.

    Only observations that explicitly contain node IDs, tile types, and
    connection lists are accepted. Pixel proximity or panel order is never
    treated as an inferred connection.
    """
    panels = layouts if isinstance(layouts, list) else [layouts]
    nodes: dict[str, dict[str, Any]] = {}
    for panel in panels:
        if isinstance(panel, Mapping) and isinstance(panel.get("nodes"), Mapping):
            candidates = panel["nodes"].items()
        elif isinstance(panel, Mapping) and isinstance(panel.get("nodes"), list):
            candidates = ((str(item.get("id")), item) for item in panel["nodes"] if isinstance(item, Mapping))
        elif isinstance(panel, list):
            candidates = ((str(item.get("id")), item) for item in panel if isinstance(item, Mapping))
        else:
            return None
        for raw_id, raw_node in candidates:
            node_id = str(raw_id).strip()
            if not node_id or node_id in nodes or not isinstance(raw_node, Mapping):
                return None
            raw_type = re.sub(r"\s+", "", str(raw_node.get("type", "")))
            tile = TILE_ALIASES.get(raw_type, "")
            next_nodes = raw_node.get("next", raw_node.get("neighbors"))
            if not tile or not isinstance(next_nodes, Sequence) or isinstance(next_nodes, (str, bytes)):
                return None
            nodes[node_id] = {"type": tile, "next": [str(value).strip() for value in next_nodes]}
    if not nodes or any(target not in nodes for node in nodes.values() for target in node["next"]):
        return None
    return {"nodes": nodes}


def find_route(
    graph: Mapping[str, Any],
    *,
    start: str,
    goal_types: Sequence[str] = ("area_boss", "area_exit"),
    avoid_hell: bool = False,
) -> list[str] | None:
    """Return tile types for the lowest-policy-cost reachable path.

    Graph schema is intentionally strict: ``nodes`` maps node IDs to objects
    with ``type`` and ``next`` (a list of node IDs). Unknown or malformed
    graphs return ``None`` instead of guessing a route.
    """
    nodes = graph.get("nodes")
    if isinstance(start, str):
        start = start.strip()
    if not isinstance(nodes, Mapping) or start not in nodes:
        return None
    goals = {TILE_ALIASES.get(re.sub(r"\s+", "", str(value)), str(value)) for value in goal_types}
    priority = {tile: index for index, tile in enumerate(TILE_PRIORITY)}
    queue: list[tuple[int, tuple[str, ...], str]] = [(0, (), str(start))]
    best: dict[str, tuple[int, tuple[str, ...]]] = {}
    while queue:
        cost, path, node_id = heapq.heappop(queue)
        previous = best.get(node_id)
        if previous is not None and previous <= (cost, path):
            continue
        best[node_id] = (cost, path)
        node = nodes.get(node_id)
        if not isinstance(node, Mapping):
            continue
        tile = TILE_ALIASES.get(re.sub(r"\s+", "", str(node.get("type", ""))), "")
        if tile in goals and path:
            return list(path)
        next_nodes = node.get("next", node.get("neighbors"))
        if not isinstance(next_nodes, Sequence) or isinstance(next_nodes, (str, bytes)):
            continue
        for raw_next in next_nodes:
            next_id = str(raw_next).strip()
            if next_id not in nodes:
                continue
            next_node = nodes[next_id]
            if not isinstance(next_node, Mapping):
                continue
            next_tile = TILE_ALIASES.get(re.sub(r"\s+", "", str(next_node.get("type", ""))), "")
            if not next_tile or (avoid_hell and next_tile == "hell"):
                continue
            next_cost = cost + priority.get(next_tile, len(priority)) + 1
            heapq.heappush(queue, (next_cost, path + (next_tile,), next_id))
    return None


def find_route_node_path(
    graph: Mapping[str, Any],
    *,
    start: str,
    goal_types: Sequence[str] = ("area_boss", "area_exit"),
    avoid_hell: bool = False,
) -> list[str] | None:
    """Return the node IDs along the lowest-policy-cost route to a goal.

    This is the coordinate-bearing counterpart of :func:`find_route`: the same
    policy is applied, but the result is the ordered list of node IDs (excluding
    ``start``) so an executor can tap each node's on-screen position.  Returns
    ``None`` when no route exists, mirroring :func:`find_route`.
    """
    nodes = graph.get("nodes")
    if isinstance(start, str):
        start = start.strip()
    if not isinstance(nodes, Mapping) or start not in nodes:
        return None
    goals = {TILE_ALIASES.get(re.sub(r"\s+", "", str(value)), str(value)) for value in goal_types}
    priority = {tile: index for index, tile in enumerate(TILE_PRIORITY)}
    queue: list[tuple[int, tuple[str, ...], str]] = [(0, (), str(start))]
    best: dict[str, tuple[int, tuple[str, ...]]] = {}
    while queue:
        cost, path, node_id = heapq.heappop(queue)
        previous = best.get(node_id)
        if previous is not None and previous <= (cost, path):
            continue
        best[node_id] = (cost, path)
        node = nodes.get(node_id)
        if not isinstance(node, Mapping):
            continue
        tile = TILE_ALIASES.get(re.sub(r"\s+", "", str(node.get("type", ""))), "")
        if tile in goals and path:
            return list(path)
        next_nodes = node.get("next", node.get("neighbors"))
        if not isinstance(next_nodes, Sequence) or isinstance(next_nodes, (str, bytes)):
            continue
        for raw_next in next_nodes:
            next_id = str(raw_next).strip()
            if next_id not in nodes:
                continue
            next_node = nodes[next_id]
            if not isinstance(next_node, Mapping):
                continue
            next_tile = TILE_ALIASES.get(re.sub(r"\s+", "", str(next_node.get("type", ""))), "")
            if not next_tile or (avoid_hell and next_tile == "hell"):
                continue
            next_cost = cost + priority.get(next_tile, len(priority)) + 1
            heapq.heappush(queue, (next_cost, path + (next_id,), next_id))
    return None


def find_route_node_sequence(
    graph: Mapping[str, Any], *, start: str, required_types: Sequence[Any],
    allow_intermediates: bool = False,
) -> list[str] | None:
    """Return a typed path, optionally including non-required intermediates."""
    nodes = graph.get("nodes")
    if not isinstance(nodes, Mapping) or start not in nodes:
        return None
    wanted = []
    for value in required_types:
        choices = value if isinstance(value, (tuple, list, set, frozenset)) else (value,)
        normalized = tuple(TILE_ALIASES.get(re.sub(r"\s+", "", str(item)), "") for item in choices)
        if not normalized or any(not item for item in normalized):
            return None
        wanted.append(frozenset(normalized))
    if not wanted:
        return None
    queue: list[tuple[str, tuple[str, ...], int]] = [(str(start), (), 0)]
    seen: set[tuple[str, int]] = {(str(start), 0)}
    while queue:
        node_id, path, index = queue.pop(0)
        if index == len(wanted):
            return list(path)
        node = nodes.get(node_id)
        if not isinstance(node, Mapping):
            continue
        next_nodes = node.get("next", node.get("neighbors"))
        if not isinstance(next_nodes, Sequence) or isinstance(next_nodes, (str, bytes)):
            continue
        for raw_next in next_nodes:
            next_id = str(raw_next).strip()
            next_node = nodes.get(next_id)
            if not isinstance(next_node, Mapping):
                continue
            next_type = TILE_ALIASES.get(re.sub(r"\s+", "", str(next_node.get("type", ""))), "")
            matches = next_type in wanted[index]
            next_index = index + 1 if matches else index
            if not matches and not allow_intermediates:
                continue
            state = (next_id, next_index)
            if state in seen:
                continue
            seen.add(state)
            queue.append((next_id, path + (next_id,), next_index))
    return None
