"""編成数に応じたEX装備「他のキャラから」利用方針。"""

from __future__ import annotations

from typing import Any, Mapping


def _damage_types(team: Any, character_index: Mapping[str, Mapping[str, Any]] | None) -> set[str]:
    if isinstance(team, Mapping):
        value = team.get("damage_type", team.get("damage_types"))
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return {str(item).lower() for item in values if item}
    if not isinstance(team, list) or not character_index:
        return set()
    result: set[str] = set()
    for name in team:
        info = character_index.get(str(name), {})
        value = info.get("damage_type", info.get("damage_types"))
        values = value if isinstance(value, (list, tuple, set)) else [value]
        result.update(str(item).lower() for item in values if item)
    return result


def plan_other_character_checkbox(
    compositions: Any,
    *,
    team_scores: list[float] | None = None,
    character_index: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """各編成で「他のキャラから」を使うか決める。"""
    if not isinstance(compositions, list) or not compositions:
        return []
    if not isinstance(compositions[0], list) and not isinstance(compositions[0], Mapping):
        compositions = [compositions]
    count = len(compositions)
    if count == 1:
        return [{"team_index": 1, "use_other_characters": True, "reason": "single_formation"}]
    if team_scores is not None and len(team_scores) == count:
        primary = sorted(range(count), key=lambda i: (-float(team_scores[i]), i))[0]
    else:
        primary = 0
    typed = [_damage_types(team, character_index) for team in compositions]
    physical = [i for i, values in enumerate(typed) if "physical" in values or "物理" in values]
    magical = [i for i, values in enumerate(typed) if "magical" in values or "magic" in values or "魔法" in values]
    enabled = {primary}
    reason = "strongest_primary_formation"
    if physical and magical and physical[0] != magical[0]:
        enabled.update({physical[0], magical[0]})
        reason = "physical_and_magical_primary_formations"
    return [{
        "team_index": i + 1,
        "use_other_characters": i in enabled,
        "reason": reason if i in enabled else "resource_conflict_avoidance",
    } for i in range(count)]
