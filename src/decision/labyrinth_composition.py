"""ラビリンスの敵編成パターン別キャラクター評価。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CharacterScore:
    name: str
    score: float
    selected: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RelicScore:
    name: str
    score: float
    selected: bool
    reasons: tuple[str, ...]


def relic_automation_gate(
    ranked: Iterable[RelicScore],
    candidates: Iterable[Mapping[str, Any]],
    *,
    current_counts: Mapping[str, int] | None,
    count_limits: Mapping[str, int] | None,
    confidence_threshold: float,
    state_token: str | None = None,
    expected_state_token: str | None = None,
    tie_tolerance: float = 0.0,
) -> dict[str, Any]:
    """ランキング結果を自動選択へ渡すための保守的なゲート。

    相性・所持数・信頼度・ランキング時点の状態が揃わない場合は、
    候補提示へ戻す。ランキング自体は副作用を持たない。
    """
    import math

    rows = list(ranked)
    source = list(candidates)
    if not rows or not source or current_counts is None or count_limits is None:
        return {"enabled": False, "reason": "relic_automation_context_required"}
    if not math.isfinite(confidence_threshold) or not 0.0 <= confidence_threshold <= 1.0:
        return {"enabled": False, "reason": "invalid_confidence_threshold"}
    if state_token is None or expected_state_token is None or state_token != expected_state_token:
        return {"enabled": False, "reason": "relic_state_changed"}
    by_name = {str(item.get("name", "")): item for item in source}
    if len(by_name) != len(source) or any(not name for name in by_name):
        return {"enabled": False, "reason": "invalid_relic_candidates"}
    top = rows[0]
    if len(rows) > 1 and top.score - rows[1].score <= tie_tolerance:
        return {"enabled": False, "reason": "relic_top_tie_or_margin_insufficient"}
    candidate = by_name.get(top.name)
    if candidate is None or not isinstance(candidate.get("confidence"), (int, float)):
        return {"enabled": False, "reason": "relic_confidence_required"}
    confidence = float(candidate["confidence"])
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return {"enabled": False, "reason": "invalid_relic_confidence"}
    if confidence < confidence_threshold:
        return {"enabled": False, "reason": "relic_confidence_below_threshold", "confidence": confidence}
    effect = str(candidate.get("effect", candidate.get("relic_type", candidate.get("type", ""))))
    if candidate.get("synergy_confirmed") is not True or not effect:
        return {"enabled": False, "reason": "relic_synergy_context_required"}
    current = current_counts.get(effect)
    limit = count_limits.get(effect)
    if not isinstance(current, int) or isinstance(current, bool) or not isinstance(limit, int) or isinstance(limit, bool):
        return {"enabled": False, "reason": "relic_count_limit_required"}
    if current < 0 or limit < 0 or current >= limit:
        return {"enabled": False, "reason": "relic_count_limit_reached"}
    return {"enabled": True, "selected": top.name, "confidence": confidence,
            "effect": effect, "current_count": current, "count_limit": limit}


def load_patterns(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), dict):
        raise ValueError("patterns must be an object")
    return data


def load_starting_members(path: str | Path = "configs/labyrinth_guild_starting_members.json") -> dict[str, Any]:
    """ギルド別の初期キャラ候補を読み込む。

    ``needs_image_verification`` が true のギルドは、記事画像にある
    未転記メンバーを含むため、自動選択では本文明示候補だけを使う。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("guilds"), dict):
        raise ValueError("starting members must contain a guilds object")
    for guild, entry in data["guilds"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"guild entry must be an object: {guild}")
        if not isinstance(entry.get("recommended_members", []), list):
            raise ValueError(f"recommended_members must be a list: {guild}")
    return data


def _matches(value: Any, expected: list[str]) -> bool:
    if not expected:
        return False
    if isinstance(value, list):
        return bool(set(map(str, value)) & set(expected))
    return str(value) in expected


def _values(item: Mapping[str, Any], *keys: str) -> set[str]:
    """候補データの表記ゆれを吸収して特徴量を取り出す。"""
    values: set[str] = set()
    for key in keys:
        value = item.get(key)
        if isinstance(value, (list, tuple, set)):
            values.update(str(entry).strip() for entry in value if str(entry).strip())
        elif value is not None and str(value).strip():
            values.add(str(value).strip())
    return values


def _relic_effects(relic: Mapping[str, Any]) -> set[str]:
    return _values(relic, "effect", "relic_type", "type", "tags", "synergy_tags")


def _character_synergy_score(
    relic: Mapping[str, Any],
    characters: list[Mapping[str, Any]],
    boss_name: str | None,
    pattern: Mapping[str, Any],
) -> tuple[float, list[str]]:
    """経験則ベースの相性補正。明示された遺物効果だけを補正する。"""
    synergy = pattern.get("character_synergy", {})
    if not isinstance(synergy, Mapping) or not characters:
        return 0.0, []
    effects = _relic_effects(relic)
    roles = set().union(*(_values(character, "role", "roles") for character in characters))
    styles = set().union(*(_values(character, "attack_style", "attack_type", "scaling", "needs") for character in characters))
    reasons: list[str] = []
    score = 0.0

    def add_if(effect_key: str, character_values: set[str], reason: str) -> None:
        nonlocal score
        configured_effects = synergy.get(effect_key, [])
        if isinstance(configured_effects, list) and effects & {str(value) for value in configured_effects} and character_values:
            score += float(synergy.get("bonus", 0))
            reasons.append(reason)

    add_if("single_target", {"single_target", "単体攻撃"} & styles, "単体攻撃編成と相性")
    add_if("action_speed", {"加速不足", "TP", "行動回数"} & styles, "行動回数不足と相性")
    add_if("light_attribute", {"光"} & set().union(*(_values(character, "attribute", "attributes") for character in characters)), "光属性編成と相性")

    tank_count = sum(1 for role in roles if role in {"タンク", "tank"})
    shortage_effects = synergy.get("tank_shortage", [])
    if tank_count == 0 and isinstance(shortage_effects, list) and effects & {str(value) for value in shortage_effects}:
        score += float(synergy.get("tank_shortage_bonus", synergy.get("bonus", 0)))
        reasons.append("タンク不足を補う")

    bosses = synergy.get("bosses", {})
    if isinstance(bosses, Mapping) and boss_name and isinstance(bosses.get(boss_name), list):
        if effects & {str(value) for value in bosses[boss_name]}:
            score += float(synergy.get("boss_bonus", synergy.get("bonus", 0)))
            reasons.append(f"{boss_name}対策")
    return score, reasons


def rank_characters(
    character_pool: list[dict[str, Any]],
    selected_members: list[str],
    pattern: dict[str, Any],
    selected_bonus: float = 100.0,
) -> list[CharacterScore]:
    """プールをボスパターン別に採点し、選択中メンバーを上位へ寄せる。"""
    if selected_bonus < 0:
        raise ValueError("selected_bonus must be non-negative")
    selected = set(selected_members)
    preferred_names = set(map(str, pattern.get("priority_characters", [])))
    excluded_names = set(map(str, pattern.get("excluded_characters", [])))
    priority_roles = list(map(str, pattern.get("priority_roles", [])))
    priority_attributes = list(map(str, pattern.get("priority_attributes", [])))
    result: list[CharacterScore] = []
    attribute_pool_counts: dict[str, int] = {}
    for item in character_pool:
        values = item.get("attributes", item.get("attribute", []))
        values = values if isinstance(values, list) else [values]
        for value in values:
            attribute_pool_counts[str(value)] = attribute_pool_counts.get(str(value), 0) + 1
    for character in character_pool:
        name = str(character.get("name", ""))
        if not name:
            raise ValueError("every character needs a name")
        score = float(character.get("base_score", 0))
        reasons: list[str] = []
        if name in preferred_names:
            score += float(pattern.get("character_bonus", 50))
            reasons.append("ボス別優先キャラ")
        if _matches(character.get("role", ""), priority_roles):
            score += float(pattern.get("role_bonus", 20))
            reasons.append("役割適合")
        if _matches(character.get("attributes", []), priority_attributes):
            score += float(pattern.get("attribute_bonus", 10))
            reasons.append("属性適合")
        if name in excluded_names:
            score -= float(pattern.get("excluded_penalty", 1000))
            reasons.append("対象外")
        if name in selected:
            score += selected_bonus
            reasons.append("現在の選択メンバー")
        for rule in pattern.get("conditional_penalties", []):
            attribute = str(rule.get("when_attribute", ""))
            minimum = int(rule.get("min_pool_count", 0))
            names = {str(value) for value in rule.get("characters", [])}
            if attribute_pool_counts.get(attribute, 0) >= minimum and name in names:
                penalty = float(rule.get("penalty", 0))
                score -= penalty
                reasons.append(f"{attribute}属性充実時の減点(-{penalty:g})")
        result.append(CharacterScore(name, score, name in selected, tuple(reasons)))
    return sorted(result, key=lambda item: (-item.score, item.name))


def build_boss_lists(
    character_pool: list[dict[str, Any]],
    selected_members: list[str],
    patterns: dict[str, Any],
    selected_bonus: float = 100.0,
) -> dict[str, list[dict[str, Any]]]:
    """Extremeボス／マップボスごとのキャラリストを作る。"""
    output: dict[str, list[dict[str, Any]]] = {}
    for category, bosses in patterns.get("patterns", {}).items():
        for boss_name, pattern in bosses.items():
            ranked = rank_characters(character_pool, selected_members, pattern, selected_bonus)
            output[f"{category}:{boss_name}"] = [
                {"rank": index, "name": item.name, "score": item.score, "selected": item.selected, "reasons": list(item.reasons)}
                for index, item in enumerate(ranked, 1)
            ]
    return output


def rank_relics(
    relic_candidates: list[dict[str, Any]],
    selected_relics: list[str],
    pattern: dict[str, Any] | None = None,
    selected_bonus: float = 100.0,
    selected_characters: list[Mapping[str, Any]] | None = None,
    boss_name: str | None = None,
    star_priority: bool = False,
) -> list[RelicScore]:
    """遺物候補を採点する。

    ``star_priority`` は自動選択用の厳格な星数優先。相性補正は同星数内の
    順位付けに使い、キャラ情報がない場合は従来の規則へフォールバックする。
    """
    if selected_bonus < 0:
        raise ValueError("selected_bonus must be non-negative")
    pattern = pattern or {}
    selected = set(selected_relics)
    priority_effects = list(map(str, pattern.get("priority_effects", [])))
    result: list[RelicScore] = []
    for relic in relic_candidates:
        name = str(relic.get("name", ""))
        if not name:
            raise ValueError("every relic needs a name")
        score = float(relic.get("base_score", 0))
        reasons: list[str] = []
        stars = int(relic.get("stars", 0))
        value = int(relic.get("value", relic.get("effect_value", 0)))
        level = max(stars, value)
        score += level * float(pattern.get("star_bonus", 10))
        if stars or value:
            reasons.append(f"遺物段階{level}（星{stars}/効果値{value}）")
        effect = str(relic.get("effect", ""))
        if effect in priority_effects:
            score += float(pattern.get("effect_bonus", 20))
            reasons.append("効果適合")
        synergy_score, synergy_reasons = _character_synergy_score(
            relic, selected_characters or [], boss_name, pattern,
        )
        score += synergy_score
        reasons.extend(synergy_reasons)
        if name in selected:
            score += selected_bonus
            reasons.append("選択済み遺物")
        result.append(RelicScore(name, score, name in selected, tuple(reasons)))
    if star_priority:
        # RelicScore does not retain stars, so use the original candidate stars
        # as the primary key while keeping the detailed score as tie-breaker.
        level_by_name = {
            str(item.get("name", "")): max(
                int(item.get("stars", 0)),
                int(item.get("value", item.get("effect_value", 0))),
            )
            for item in relic_candidates
        }
        return sorted(result, key=lambda item: (-level_by_name.get(item.name, 0), -item.score, item.name))
    return sorted(result, key=lambda item: (-item.score, item.name))


def build_selection_lists(
    character_pool: list[dict[str, Any]],
    selected_members: list[str],
    relic_candidates: list[dict[str, Any]],
    selected_relics: list[str],
    patterns: dict[str, Any],
    selected_bonus: float = 100.0,
    selected_characters: list[Mapping[str, Any]] | None = None,
    boss_name: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """戦闘前のキャラ／遺物候補リストを一括生成する。"""
    result = build_boss_lists(character_pool, selected_members, patterns, selected_bonus)
    relic_pattern = patterns.get("relic", {})
    ranked_relics = rank_relics(
        relic_candidates, selected_relics, relic_pattern, selected_bonus,
        selected_characters=selected_characters, boss_name=boss_name,
    )
    result["relic:候補"] = [
        {"rank": index, "name": item.name, "score": item.score, "selected": item.selected, "reasons": list(item.reasons)}
        for index, item in enumerate(ranked_relics, 1)
    ]
    return result
