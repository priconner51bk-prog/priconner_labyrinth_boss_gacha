"""決定論的なラビリンス接続線検出。"""

from __future__ import annotations

from collections.abc import Mapping
import math

import cv2
import numpy as np


def _line_mask(image: np.ndarray) -> np.ndarray:
    """Extract the bright lavender route rail, excluding dark background."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # Active rails are bright and moderately saturated; dark background rails
    # are intentionally rejected by the value threshold.
    mask = cv2.inRange(hsv, np.array([90, 25, 145]), np.array([179, 255, 255]))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def connection_score(image: np.ndarray, left: Mapping[str, object], right: Mapping[str, object]) -> float:
    """Return the ratio of bright rail samples on the node-to-node segment."""
    if image is None or image.ndim != 3:
        return 0.0
    try:
        x1, y1 = float(left["x"]), float(left["y"])
        x2, y2 = float(right["x"]), float(right["y"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance < 80.0:
        return 0.0
    mask = _line_mask(image)
    # Do not sample inside the node artwork; only the corridor between the
    # two platforms is evidence for a connector.
    trim = min(75.0, distance * 0.22)
    start = trim / distance
    end = 1.0 - start
    count = max(20, int(distance * 1.4))
    hits = 0
    valid = 0
    height, width = mask.shape[:2]
    dx = (x2 - x1) / distance
    dy = (y2 - y1) / distance
    # Rails are attached to platform edges rather than OCR label centers.
    # Search a narrow perpendicular corridor around the expected segment.
    normal_x, normal_y = -dy, dx
    for t in np.linspace(start, end, count):
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        if not (1 <= x < width - 1 and 1 <= y < height - 1):
            continue
        valid += 1
        # Allow platform-anchor and anti-alias offsets while requiring local
        # evidence along the whole segment.
        found = False
        for offset in (-24, -16, -8, 0, 8, 16, 24):
            sx = int(round(x + normal_x * offset))
            sy = int(round(y + normal_y * offset))
            if int(mask[max(0, sy - 2):sy + 3, max(0, sx - 2):sx + 3].max()) > 0:
                found = True
                break
        if found:
            hits += 1
    return hits / valid if valid else 0.0


def verified_connection(image: np.ndarray, left: Mapping[str, object], right: Mapping[str, object], *, threshold: float = 0.72) -> bool:
    """Accept only a continuous, left-to-right connector with high evidence."""
    return connection_score(image, left, right) >= threshold
