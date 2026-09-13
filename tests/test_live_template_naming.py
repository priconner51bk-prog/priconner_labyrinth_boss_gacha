"""ライブテンプレートの命名規則と参照先を検証する。"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/live_screen_templates.json"


def _live_template_paths() -> list[str]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    return list(
        dict.fromkeys(
            item["image"]
            for group in ("screens", "targets")
            for item in config[group].values()
            if item["image"].startswith("data/observations/live/")
        )
    )


def test_live_template_images_use_template_prefix_and_exist() -> None:
    paths = _live_template_paths()
    assert paths
    assert all(Path(path).name.startswith("template_") for path in paths)
    assert all((ROOT / path).is_file() for path in paths)
