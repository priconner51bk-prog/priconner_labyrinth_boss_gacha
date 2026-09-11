"""初期キャラ選択画面のカード単位OCR。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .ocr import OCRLine
from .roi import NormalizedROI


class CharacterOCRAdapter(Protocol):
    def recognize(self, image_path: str, roi: NormalizedROI | None = None) -> list[OCRLine]: ...


def recognize_character_cards(
    image_path: str,
    adapter: CharacterOCRAdapter,
    regions: list[dict[str, Any]],
    *,
    min_confidence: float = 0.80,
    preprocess: bool = False,
) -> list[dict[str, Any]]:
    """カードROIごとに最高信頼度の名前とカード中心を返す。

    名前が読めないカードは返さない。呼び出し側は必要人数に満たない場合、
    推測でタップせず安全停止する。
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    output: list[dict[str, Any]] = []
    for index, region in enumerate(regions, 1):
        try:
            roi = NormalizedROI(**region["normalized"])
            center = region["center"]
            x, y = int(center["x"]), int(center["y"])
        except (KeyError, TypeError, ValueError):
            continue
        ocr_path = image_path
        temporary_path: Path | None = None
        if preprocess:
            try:
                import cv2
                import tempfile
                image = cv2.imread(image_path)
                if image is not None:
                    height, width = image.shape[:2]
                    left, top, right, bottom = roi.pixel_bounds(width, height)
                    crop = image[top:bottom, left:right]
                    crop = cv2.convertScaleAbs(crop, alpha=1.8, beta=20)
                    crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    fd, name = tempfile.mkstemp(prefix="labyrinth_card_", suffix=".png")
                    Path(name).unlink(missing_ok=True)
                    cv2.imwrite(name, crop)
                    temporary_path = Path(name)
                    ocr_path = name
            except (ImportError, OSError, ValueError):
                pass
        lines = adapter.recognize(ocr_path, None if temporary_path is not None else roi)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        valid = [line for line in lines if isinstance(line.text, str) and line.text.strip() and line.confidence >= min_confidence]
        if not valid:
            continue
        line = max(valid, key=lambda item: item.confidence)
        output.append({"index": index, "name": line.text.strip(), "confidence": line.confidence,
                       "x": x, "y": y, "bbox": line.bbox})
    # A card crop can clip decorative Japanese glyphs. One full-frame pass is
    # a useful fallback: assign each positioned line to its configured card.
    recognized = {item["index"] for item in output}
    if len(recognized) < len(regions):
        for line in adapter.recognize(image_path, None):
            if not isinstance(line.text, str) or not line.text.strip() or line.confidence < min_confidence or line.bbox is None:
                continue
            cx = (line.bbox[0] + line.bbox[2]) / 2
            for index, region in enumerate(regions, 1):
                normalized = region.get("normalized", {})
                left = float(normalized.get("x", 0)) * 1280
                right = (float(normalized.get("x", 0)) + float(normalized.get("width", 0))) * 1280
                cy = (line.bbox[1] + line.bbox[3]) / 2
                top = float(normalized.get("y", 0)) * 720
                bottom = (float(normalized.get("y", 0)) + float(normalized.get("height", 0))) * 720
                if left <= cx <= right and top <= cy <= bottom and index not in recognized:
                    center = region.get("center", {})
                    output.append({"index": index, "name": line.text.strip(), "confidence": line.confidence,
                                   "x": int(center.get("x", cx)), "y": int(center.get("y", 0)), "bbox": line.bbox})
                    recognized.add(index)
                    break
    return output
