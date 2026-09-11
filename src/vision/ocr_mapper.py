from __future__ import annotations

from typing import Any

from contracts import GameState


def map_ocr_to_gamestate(state_id: str, ocr: dict[str, Any], min_confidence: float = 0.7) -> GameState | None:
    """Convert validated OCR fixture fields to GameState, or return unknown."""
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    screen_id = str(ocr.get("screen_id", "")).strip()
    try:
        confidence = float(ocr.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    if not screen_id or not 0.0 <= confidence <= 1.0 or confidence < min_confidence:
        return None
    entities = ocr.get("entities", {})
    if not isinstance(entities, dict):
        return None
    return GameState(
        state_id=state_id,
        screen_id=screen_id,
        source="ocr",
        confidence=confidence,
        entities=entities,
        raw_observation=ocr,
    )
