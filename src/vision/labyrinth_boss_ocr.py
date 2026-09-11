"""ラビリンスのモンスター詳細に対する固定ROI OCR。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .ocr import OCRLine
from .roi import NormalizedROI


class OCRAdapter(Protocol):
    def recognize(self, image_path: str, roi: NormalizedROI | None = None) -> list[OCRLine]: ...


def load_boss_name_roi(config_path: str | Path) -> NormalizedROI:
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    try:
        region = data["regions"]["boss_detail_name"]["normalized"]
        return NormalizedROI(**region)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("boss_detail_name ROI is invalid") from exc


def normalize_boss_name(text: str) -> str:
    """Remove a leading decoration/OCR noise while retaining the Japanese name."""
    value = text.strip()
    prefixes = ("グレーター", "ジャバ", "ダーク", "グレート")
    positions = [value.find(prefix) for prefix in prefixes if value.find(prefix) >= 0]
    if positions:
        value = value[min(positions):]
    return value


def recognize_boss_name(
    image_path: str,
    adapter: OCRAdapter,
    roi: NormalizedROI,
) -> dict[str, Any] | None:
    """Recognize the highest-confidence line from the fixed boss-name ROI."""
    lines = adapter.recognize(image_path, roi)
    if not lines:
        return None
    line = max(lines, key=lambda item: item.confidence)
    name = normalize_boss_name(line.text)
    if not name:
        return None
    return {"name": name, "raw_text": line.text, "confidence": line.confidence, "bbox": line.bbox}
