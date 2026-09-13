from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .capture import CapturedFrame
from .observation import ScreenObservation, ScreenObserver


class FrameCapture(Protocol):
    def capture(self, output_path: str | Path) -> CapturedFrame:
        ...


def capture_and_observe(
    capture: FrameCapture,
    observer: ScreenObserver,
    output_path: str | Path,
    observation_id: str,
) -> ScreenObservation:
    """Compose read-only capture and observation, quarantining capture errors."""
    try:
        frame = capture.capture(output_path)
    except Exception:
        return ScreenObservation(
            observation_id=observation_id,
            image_path=str(output_path),
            source="fixture",
            confidence=0.0,
            status="unknown",
            unknown_reason="capture_error",
        )
    return observer.observe(frame.image_path, observation_id)
