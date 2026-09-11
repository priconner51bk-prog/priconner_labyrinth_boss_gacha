from __future__ import annotations

from pathlib import Path
from typing import Any

from .observation import ScreenObserver, ScreenObservation


def replay_screen_fixtures(fixtures: list[dict[str, Any]], observer: ScreenObserver, repeat: int = 1) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    expanded: list[dict[str, Any]] = []
    for iteration in range(repeat):
        for fixture in fixtures:
            if isinstance(fixture, dict):
                item = dict(fixture)
                if repeat > 1 and isinstance(item.get("observation_id"), str):
                    item["observation_id"] = f"{item['observation_id']}#r{iteration + 1}"
                expanded.append(item)
            else:
                expanded.append(fixture)
    observations: list[ScreenObservation] = []
    for fixture in expanded:
        if not isinstance(fixture, dict):
            observation = observer.observe("<invalid-fixture>", "invalid-fixture")
            observation.unknown_reason = "invalid_fixture"
            observations.append(observation)
            continue
        image_path = fixture.get("image_path")
        observation_id = fixture.get("observation_id")
        if not isinstance(image_path, (str, Path)) or not str(image_path).strip() or not isinstance(observation_id, str) or not observation_id.strip():
            observation = observer.observe("<invalid-fixture>", "invalid-fixture")
            observation.unknown_reason = "invalid_fixture"
            observations.append(observation)
            continue
        observations.append(observer.observe(image_path, observation_id))
    known = sum(observation.status == "known" for observation in observations)
    total = len(observations)
    return {
        "total": total,
        "known": known,
        "unknown": total - known,
        "known_rate": known / total if total else 0.0,
        "unknown_rate": (total - known) / total if total else 0.0,
        "repeat": repeat,
        "observations": [observation.model_dump(mode="json") for observation in observations],
    }
