from __future__ import annotations

from typing import Any

# These values describe instantaneous load, not environment configuration.
# Comparing them makes repeated collection reports noisy by design.
VOLATILE_KEYS = {
    "collected_at",
    "vram_used_mib",
    "vram_used_mib_at_collection",
    "utilization_percent",
    "utilization_percent_at_collection",
}


def compare_environment(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic environment drift without mutating either report."""
    changes: list[dict[str, Any]] = []

    def walk(path: str, old: Any, new: Any) -> None:
        if path.endswith("collected_at"):
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                if key in VOLATILE_KEYS or key == "schema_version":
                    continue
                if key not in old:
                    changes.append({"path": f"{path}.{key}".strip("."), "kind": "added", "current": new[key]})
                elif key not in new:
                    changes.append({"path": f"{path}.{key}".strip("."), "kind": "removed", "baseline": old[key]})
                else:
                    walk(f"{path}.{key}".strip("."), old[key], new[key])
            return
        if isinstance(old, list) and isinstance(new, list):
            if _can_match_by_stable_key(old, new):
                old_by_key = {str(item["stable_key"]): item for item in old}
                new_by_key = {str(item["stable_key"]): item for item in new}
                for key in sorted(set(old_by_key) | set(new_by_key)):
                    item_path = f"{path}[stable_key={key}]"
                    if key not in old_by_key:
                        changes.append({"path": item_path, "kind": "added", "current": new_by_key[key]})
                    elif key not in new_by_key:
                        changes.append({"path": item_path, "kind": "removed", "baseline": old_by_key[key]})
                    else:
                        walk(item_path, old_by_key[key], new_by_key[key])
                return
            for index in range(max(len(old), len(new))):
                item_path = f"{path}[{index}]"
                if index >= len(old):
                    changes.append({"path": item_path, "kind": "added", "current": new[index]})
                elif index >= len(new):
                    changes.append({"path": item_path, "kind": "removed", "baseline": old[index]})
                else:
                    walk(item_path, old[index], new[index])
            return
        if old != new:
            changes.append({"path": path, "kind": "changed", "baseline": old, "current": new})

    walk("", baseline, current)
    baseline_schema = baseline.get("schema_version")
    current_schema = current.get("schema_version")
    return {
        "baseline_schema": baseline_schema,
        "current_schema": current_schema,
        "schema_compatible": baseline_schema == current_schema,
        "requires_baseline_migration": baseline_schema != current_schema,
        "changed": len(changes),
        "changes": changes,
    }


def _can_match_by_stable_key(old: list[Any], new: list[Any]) -> bool:
    if not old or not new or not all(isinstance(item, dict) and item.get("stable_key") for item in old + new):
        return False
    old_keys = [str(item["stable_key"]) for item in old]
    new_keys = [str(item["stable_key"]) for item in new]
    return len(old_keys) == len(set(old_keys)) and len(new_keys) == len(set(new_keys))
