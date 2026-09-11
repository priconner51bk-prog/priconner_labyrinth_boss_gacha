from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonFixtureClassifier:
    """Deterministic classifier for offline screen-observation replay."""

    def __init__(self, fixture_path: str | Path):
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        self._results = {
            str(item["image_path"]): dict(item["result"])
            for item in payload
            if "image_path" in item and "result" in item
        }

    def __call__(self, image_path: Path) -> dict[str, Any]:
        return dict(self._results.get(str(image_path), {}))

