from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts import GameState


class ScreenObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str
    image_path: str
    screen_id: str | None = None
    source: Literal["opencv", "ocr", "fixture"]
    confidence: float = Field(ge=0.0, le=1.0)
    state: GameState | None = None
    status: Literal["known", "unknown"]
    unknown_reason: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScreenObserver:
    """Map injected screen/OCR results to a safe observation contract."""

    def __init__(self, classifier: Callable[[Path], dict[str, Any]], min_confidence: float = 0.7):
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self.classifier = classifier
        self.min_confidence = min_confidence

    def observe(self, image_path: str | Path, observation_id: str) -> ScreenObservation:
        path = Path(image_path)
        try:
            result = self.classifier(path)
        except Exception:
            return ScreenObservation(observation_id=observation_id, image_path=str(path), source="fixture", confidence=0.0, status="unknown", unknown_reason="classifier_error")
        if not isinstance(result, dict):
            return ScreenObservation(observation_id=observation_id, image_path=str(path), source="fixture", confidence=0.0, status="unknown", unknown_reason="invalid_classifier_result")
        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not 0.0 <= confidence <= 1.0:
            confidence = 0.0
        source = result.get("source", "fixture")
        if source not in {"opencv", "ocr", "fixture"}:
            source = "fixture"
        raw_screen_id = result.get("screen_id")
        screen_id = raw_screen_id.strip() if isinstance(raw_screen_id, str) else None
        if not screen_id or confidence < self.min_confidence:
            reason = "missing_screen_id" if not screen_id else "low_confidence"
            return ScreenObservation(observation_id=observation_id, image_path=str(path), screen_id=screen_id, source=source, confidence=confidence, status="unknown", unknown_reason=reason)
        entities = result.get("entities", {})
        if not isinstance(entities, dict):
            return ScreenObservation(observation_id=observation_id, image_path=str(path), screen_id=screen_id, source=source, confidence=0.0, status="unknown", unknown_reason="invalid_entities")
        state = GameState(state_id=observation_id, screen_id=screen_id, source=source, confidence=confidence, entities=entities, raw_observation=result)
        return ScreenObservation(observation_id=observation_id, image_path=str(path), screen_id=screen_id, source=source, confidence=confidence, state=state, status="known")
