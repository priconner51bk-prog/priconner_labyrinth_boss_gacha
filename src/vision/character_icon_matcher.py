"""登録基準画像によるキャラアイコンの fail-closed 照合。"""

from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np


def _normalized(image: np.ndarray) -> np.ndarray:
    return cv2.resize(image, (96, 96), interpolation=cv2.INTER_AREA)


def compare_icon(current: np.ndarray, reference: np.ndarray) -> dict[str, float | bool]:
    """複数指標がすべて閾値を満たす場合だけ一致とする。"""
    if current is None or reference is None or current.size == 0 or reference.size == 0:
        return {"matched": False, "correlation": 0.0, "histogram": 0.0}
    current_small = _normalized(current)
    reference_small = _normalized(reference)
    current_gray = cv2.cvtColor(current_small, cv2.COLOR_BGR2GRAY)
    reference_gray = cv2.cvtColor(reference_small, cv2.COLOR_BGR2GRAY)
    correlation = float(cv2.matchTemplate(current_gray, reference_gray, cv2.TM_CCOEFF_NORMED)[0, 0])
    current_hist = cv2.calcHist([current_small], [0, 1], None, [32, 32], [0, 256, 0, 256])
    reference_hist = cv2.calcHist([reference_small], [0, 1], None, [32, 32], [0, 256, 0, 256])
    cv2.normalize(current_hist, current_hist)
    cv2.normalize(reference_hist, reference_hist)
    histogram = float(cv2.compareHist(current_hist, reference_hist, cv2.HISTCMP_CORREL))
    matched = correlation >= 0.92 and histogram >= 0.90
    return {"matched": matched, "correlation": correlation, "histogram": histogram}


def match_registered_icon(current: np.ndarray, reference_path: str | Path) -> dict[str, float | bool]:
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    return compare_icon(current, reference)


def crop_card(image: np.ndarray, center: tuple[int, int], *, half_width: int = 65, half_height: int = 60) -> np.ndarray:
    """カード中心から、レベル文字を含むカード上部の安定領域を切り出す。"""
    x, y = center
    return image[max(0, y - half_height):y + half_height, max(0, x - half_width):x + half_width]


def compare_registered_position(
    current_image: np.ndarray,
    reference_image: np.ndarray,
    center: tuple[int, int],
) -> dict[str, float | bool]:
    return compare_icon(crop_card(current_image, center), crop_card(reference_image, center))
