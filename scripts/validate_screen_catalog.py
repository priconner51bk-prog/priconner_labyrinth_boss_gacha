"""Validate screen templates, allowed targets, and guarded ADB coordinates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.labyrinth_route import ADB_SCREEN_COORDINATES
from vision.template_screen_probe import AdbTemplateScreenProbe

WIDTH, HEIGHT = 1280, 720
VIRTUAL_SCREENS = {"notice", "startup_error", "startup_splash"}


def duplicate_json_keys(text: str) -> list[str]:
    duplicates: list[str] = []

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                duplicates.append(str(key))
            result[key] = value
        return result

    json.loads(text, object_pairs_hook=pairs)
    return sorted(set(duplicates))


def validate_catalog(config: dict, *, screen_targets=None, coordinates=None) -> dict[str, object]:
    screen_targets = screen_targets or AdbTemplateScreenProbe._SCREEN_TARGETS
    coordinates = coordinates or ADB_SCREEN_COORDINATES
    screens = config.get("screens", {})
    targets = config.get("targets", {})
    errors: list[str] = []
    warnings: list[str] = []

    def check_region(kind: str, name: str, value: object) -> None:
        if not isinstance(value, dict):
            errors.append(f"{kind}.{name}: region_not_object")
            return
        try:
            left, top, right, bottom = (int(value[key]) for key in ("left", "top", "right", "bottom"))
        except (KeyError, TypeError, ValueError):
            errors.append(f"{kind}.{name}: region_invalid")
            return
        if not (0 <= left < right <= WIDTH and 0 <= top < bottom <= HEIGHT):
            errors.append(f"{kind}.{name}: region_out_of_bounds")
        if not str(value.get("image", "")).strip():
            errors.append(f"{kind}.{name}: image_missing")

    for name, value in screens.items():
        check_region("screens", name, value)
        if name not in screen_targets and name not in {"title"}:
            warnings.append(f"screens.{name}: allowed_targets_not_declared")
    for name, value in targets.items():
        check_region("targets", name, value)
        owners = sorted(screen for screen, labels in screen_targets.items() if name in labels)
        if not owners:
            warnings.append(f"targets.{name}: target_not_referenced")

    for screen, labels in coordinates.items():
        if screen not in screens and screen not in VIRTUAL_SCREENS and screen != "title":
            errors.append(f"coordinates.{screen}: screen_not_registered")
        allowed = set(screen_targets.get(screen, set()))
        if screen == "title":
            allowed.add("Touch To Start")
        for label, point in labels.items():
            if not (isinstance(point, tuple) and len(point) == 2
                    and all(isinstance(value, int) for value in point)
                    and 0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT):
                errors.append(f"coordinates.{screen}.{label}: coordinate_out_of_bounds")
            if label not in allowed:
                errors.append(f"coordinates.{screen}.{label}: target_not_allowed_for_screen")
            if label not in targets and screen != "title":
                warnings.append(f"coordinates.{screen}.{label}: target_template_missing")

    generic = {"閉じる", "OK"}
    for label in generic:
        owners = [screen for screen, labels in coordinates.items() if label in labels]
        if len(owners) > 1:
            errors.append(f"common_target.{label}: reused_across_screens:{','.join(sorted(owners))}")
    return {"status": "ok" if not errors else "error", "errors": sorted(set(errors)),
            "warnings": sorted(set(warnings)), "screen_count": len(screens),
            "target_count": len(targets), "coordinate_screen_count": len(coordinates)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/live_screen_templates.json")
    args = parser.parse_args()
    try:
        text = args.config.read_text(encoding="utf-8")
        duplicates = duplicate_json_keys(text)
        result = validate_catalog(json.loads(text))
        if duplicates:
            result["status"] = "error"
            result["errors"] = sorted([*result["errors"], *(f"duplicate_key:{key}" for key in duplicates)])
    except (OSError, ValueError) as exc:
        result = {"status": "error", "errors": [f"catalog_unreadable:{type(exc).__name__}"], "warnings": []}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
