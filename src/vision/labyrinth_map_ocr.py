"""ラビリンスマップOCR結果を安全なマス候補へ変換する。"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import cv2
import numpy as np


_ALIASES = {
    "normal": "normal", "NORMAL": "normal", "通常": "normal", "通常戦闘": "normal",
    "extreme": "extreme", "EXTREME": "extreme", "EX": "extreme", "エクストリーム": "extreme",
    "hell": "hell", "HELL": "hell", "ヘル": "hell",
    "relic": "relic", "遺物": "relic",
    "connectsign": "connect_sign", "コネクトサイン": "connect_sign",
    "shop": "shop", "SHOP": "shop", "ショップ": "shop",
    "event": "event", "EVENT": "event", "EVEN": "event", "イベン": "event", "イベント": "event",
    "boss": "area_boss", "BOSS": "area_boss", "ボス": "area_boss", "エリアボス": "area_boss",
}


def _canonical_label(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    return _ALIASES.get(compact)


def _bbox(item: Any) -> tuple[int, int, int, int] | None:
    value = item.get("bbox") if isinstance(item, dict) else getattr(item, "bbox", None)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in value)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _text(item: Any) -> str:
    value = item.get("text") if isinstance(item, dict) else getattr(item, "text", "")
    return value.strip() if isinstance(value, str) else ""


def extract_map_nodes(lines: Iterable[Any], *, min_confidence: float = 0.75) -> list[dict[str, Any]]:
    """OCR行から既知のマスだけを抽出し、中心座標付きで返す。

    座標なし・低信頼度・未知ラベルは入力操作に使える候補ではないため除外。
    同一マスの重複OCRは中心距離20px以内で統合する。
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    nodes: list[dict[str, Any]] = []
    for item in lines:
        label = _text(item)
        tile_type = _canonical_label(label)
        box = _bbox(item)
        confidence = item.get("confidence", 0.0) if isinstance(item, dict) else getattr(item, "confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if tile_type is None or box is None or confidence < min_confidence:
            continue
        x1, y1, x2, y2 = box
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if any(abs(node["x"] - center[0]) <= 20 and abs(node["y"] - center[1]) <= 20 for node in nodes):
            continue
        nodes.append({"id": f"ocr_{len(nodes) + 1}", "type": tile_type,
                      "label": label, "x": center[0], "y": center[1],
                      "confidence": confidence})
    return sorted(nodes, key=lambda node: (node["y"], node["x"]))


def detect_terminal_chest(
    image: np.ndarray,
    reference: np.ndarray,
    *,
    threshold: float = 0.85,
) -> dict[str, Any] | None:
    """Detect the visually distinct right-edge relic chest conservatively."""
    if image is None or reference is None or image.shape[:2] != reference.shape[:2]:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY) if reference.ndim == 3 else reference
    template = ref_gray[250:465, 545:735]
    search = gray[120:620, 100:1100]
    if template.size == 0 or search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return None
    score_map = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(score_map)
    # At the right edge the chest can be clipped by the viewport.  The full
    # template then has a low score even though its distinctive left half is
    # clearly visible.  Limit the fallback to the right-side search region so
    # arbitrary map artwork cannot become an exit node.
    if score < threshold:
        partial = template[:, :120]
        right_search = search[:, 650:]
        partial_map = cv2.matchTemplate(right_search, partial, cv2.TM_CCOEFF_NORMED)
        _, partial_score, _, partial_location = cv2.minMaxLoc(partial_map)
        if partial_score < 0.90:
            return None
        location = (partial_location[0] + 650, partial_location[1])
    x = 100 + location[0] + template.shape[1] // 2
    y = 120 + location[1] + template.shape[0] // 2
    return {"id": "terminal_chest", "type": "area_exit", "label": "TERMINAL_CHEST",
            "x": x, "y": y, "confidence": round(float(score), 4)}


def detect_relic_node(
    image: np.ndarray,
    reference: np.ndarray,
    *,
    threshold: float = 0.82,
) -> dict[str, Any] | None:
    """Detect the icon-only relic tile used by the live labyrinth map.

    Relic tiles do not carry a readable label, so OCR-only scans silently
    dropped the mandatory area exit path.  The icon scale is fixed by the
    game viewport; this conservative template match supplies a node candidate
    without accepting arbitrary platform/background pixels.
    """
    if image is None or reference is None or image.ndim != 3 or reference.ndim != 3:
        return None
    # Reference crop is the pink relic statue and its platform, excluding the
    # surrounding map rails.  Keep the crop small enough to tolerate a
    # different background while retaining the distinctive icon silhouette.
    template = reference[250:400, 590:690]
    if template.size == 0 or image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    score_map = cv2.matchTemplate(gray, ref_gray, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(score_map)
    if score < threshold:
        return None
    x = location[0] + template.shape[1] // 2
    y = location[1] + template.shape[0] // 2
    return {"id": "relic_visual", "type": "relic", "label": "RELIC_VISUAL",
            "x": int(x), "y": int(y), "confidence": round(float(score), 4)}


def detect_event_nodes(
    image: np.ndarray,
    seeds: list[Mapping[str, Any]],
    *,
    threshold: float = 0.82,
) -> list[dict[str, Any]]:
    """Find all event badges in a panel using an OCR-confirmed event seed.

    OCR can return only the upper ``EVENT`` badge when two identical event
    tiles are vertically stacked.  The badge artwork is stable, so an event
    already confirmed by OCR is a safe, deterministic template for finding
    its sibling.  No event is invented when the panel has no OCR-confirmed
    seed.
    """
    if image is None or image.ndim != 3 or not seeds:
        return []
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    detections: list[dict[str, Any]] = []
    for seed in seeds:
        try:
            sx, sy = int(seed["x"]), int(seed["y"])
        except (KeyError, TypeError, ValueError):
            continue
        # Include the badge and platform but avoid the fixed header and
        # bottom controls.  A 100x100 crop is stable across the map panels.
        x0, y0 = sx - 45, sy - 33
        x1, y1 = x0 + 90, y0 + 100
        if x0 < 0 or y0 < 90 or x1 > width or y1 > height - 70:
            continue
        template = gray[y0:y1, x0:x1]
        if template.size == 0:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        while True:
            _, score, _, location = cv2.minMaxLoc(scores)
            if score < threshold:
                break
            cx = int(location[0] + template.shape[1] / 2)
            cy = int(location[1] + template.shape[0] / 2)
            if 90 <= cy <= height - 70 and not any(
                abs(cx - int(item["x"])) < 55 and abs(cy - int(item["y"])) < 55
                for item in detections
            ):
                detections.append({
                    "id": "event_visual",
                    "type": "event",
                    "label": "EVENT_VISUAL",
                    "x": cx,
                    "y": cy,
                    "confidence": round(float(score), 4),
                })
            # Suppress this local maximum so the next sibling can be found.
            cv2.rectangle(
                scores,
                (max(0, location[0] - 60), max(0, location[1] - 60)),
                (min(scores.shape[1] - 1, location[0] + 60),
                 min(scores.shape[0] - 1, location[1] + 60)),
                -1,
                -1,
            )
    return detections


def detect_player_node(
    image: np.ndarray,
    reference: np.ndarray,
    *,
    threshold: float = 0.62,
) -> dict[str, Any] | None:
    """Detect the current/start tile carrying the player sprite.

    The start tile has no OCR label.  A scan that only keeps NORMAL/EVENT
    labels therefore chooses an arbitrary visible tile as its graph start and
    can issue a valid tap for an unreachable tile.  The left-edge scan frame
    is used as the reference for the current run, so the active character
    appearance may differ between runs without requiring a fixed character
    asset.
    """
    if image is None or reference is None or image.ndim != 3 or reference.ndim != 3:
        return None
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # The active character is a bright, saturated sprite above a platform;
    # unlike the dark enemy icons and yellow EVENT labels it contains a large
    # orange/skin-coloured connected region.  The bounds exclude the header
    # and bottom controls.  This remains valid after the character moves.
    mask = cv2.inRange(hsv, (0, 90, 120), (35, 255, 255))
    mask[:120] = 0
    mask[620:] = 0
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for stats_row in stats[1:]:
        x, y, w, h, area = (int(value) for value in stats_row)
        # The map background and terminal artwork can also contain large
        # orange components.  The active character sprite is consistently a
        # compact portrait-sized component; rejecting broad/short components
        # prevents an empty platform or boss art from becoming a fake S node.
        if (30 <= x and x + w <= width - 30
                and 1000 <= area <= 5000 and 50 <= w <= 110 and 70 <= h <= 130
                and 0.45 <= w / max(h, 1) <= 1.05):
            candidates.append((area, x, y, w, h))
    if candidates:
        area, x, y, w, h = max(candidates)
        return {"id": "player_start", "type": "area_start", "label": "PLAYER_START",
                "x": int(x + w / 2), "y": int(y + h + 35),
                "confidence": round(min(0.99, 0.70 + area / 10000), 4)}
    # A resolved tile is authoritative when both the cyan CLEAR stamp and a
    # pale character/art component are visible in the same viewport.  Check
    # it before the generic pale-player fallback to avoid rebinding the
    # current position to the old start platform.
    clear_mask = cv2.inRange(hsv, (75, 80, 100), (110, 255, 255))
    clear_mask[:120] = 0
    clear_mask[620:] = 0
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(clear_mask)
    clear_candidates = []
    for stats_row in stats[1:]:
        x, y, w, h, area = (int(value) for value in stats_row)
        if (250 <= x <= 1100 and 130 <= y <= 500 and 60 <= w <= 240
                and 40 <= h <= 180 and 1500 <= area <= 14000):
            clear_candidates.append((area, x, y, w, h))
    if clear_candidates:
        area, x, y, w, h = max(clear_candidates)
        return {"id": "player_start", "type": "area_start", "label": "CLEAR_CURRENT",
                "x": int(x + w / 2), "y": int(y + h + 40),
                "confidence": round(min(0.88, 0.60 + area / 20000), 4)}

    # Pale characters (for example the current white-haired unit) have too
    # little orange area for the primary mask.  On the left-edge frame, the
    # player and its platform form one compact bright component in this band;
    # require the full geometry so enemy/terminal artwork is not promoted.
    bright = cv2.inRange(hsv, (0, 0, 160), (180, 255, 255))
    bright[:120] = 0
    bright[620:] = 0
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(bright)
    pale_candidates = []
    for stats_row in stats[1:]:
        x, y, w, h, area = (int(value) for value in stats_row)
        if (450 <= x <= 700 and 220 <= y <= 380 and 100 <= w <= 220
                and 80 <= h <= 180 and 3000 <= area <= 15000):
            pale_candidates.append((area, x, y, w, h))
    if pale_candidates:
        area, x, y, w, h = max(pale_candidates)
        return {"id": "player_start", "type": "area_start", "label": "PLAYER_START",
                "x": int(x + w / 2), "y": int(y + 30),
                "confidence": round(min(0.90, 0.62 + area / 20000), 4)}
    # After a tile is resolved, the character sprite can be replaced by the
    # cyan CLEAR stamp.  On the left-edge frame it occupies the current-tile
    # band; use the largest compact cyan component and keep the same explicit
    # area_start contract for downstream route planning.
    # Do not fall back to platform template matching here.  A platform is
    # visually much larger than the player and the old fallback routinely
    # promoted an empty/clear platform to the current position.  A missing
    # player observation is safer than authorizing a route from a fake S node;
    # overlapping panels will normally provide a valid sprite observation.
    return None
