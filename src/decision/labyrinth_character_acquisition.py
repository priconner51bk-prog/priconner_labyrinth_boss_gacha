"""ラビリンス内のキャラ獲得候補を共通の状態で評価する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SOURCE_RULES: dict[str, dict[str, Any]] = {
    # Legacy/manual reward input has no fixed UI cardinality.
    "character_reward": {"candidate_count": None, "select_count": 1, "selection": "single"},
    "initial_guild": {"candidate_count": 3, "select_count": 3, "selection": "multi"},
    "initial_random": {"candidate_count": 1, "select_count": 1, "selection": "random"},
    "connect_sign": {"candidate_count": 3, "select_count": 1, "selection": "single"},
    "event": {"candidate_count": None, "select_count": 1, "selection": "single"},
    "extreme_reward": {"candidate_count": 3, "select_count": 1, "selection": "single"},
    "hell_reward": {"candidate_count": 3, "select_count": 1, "selection": "single"},
    "area3_boss_reward": {"candidate_count": 3, "select_count": 1, "selection": "single"},
    "shop": {"candidate_count": None, "select_count": 1, "selection": "single"},
}


@dataclass(frozen=True)
class AcquisitionScore:
    name: str
    score: float
    reasons: tuple[str, ...]


def source_rule(source: str) -> Mapping[str, Any] | None:
    return SOURCE_RULES.get(str(source).strip().lower())


def _values(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {str(value).strip()} if value is not None and str(value).strip() else set()


def validate_candidates(source: str, candidates: list[Any]) -> str | None:
    """候補数・候補形式を検査し、問題があれば理由を返す。"""
    rule = source_rule(source)
    if rule is None:
        return "character_source_unknown"
    if not candidates:
        return "character_candidates_required"
    expected = rule["candidate_count"]
    if expected is not None and len(candidates) != expected:
        return f"character_candidate_count_required:{expected}"
    if any(not isinstance(item, Mapping) or not str(item.get("name", "")).strip() for item in candidates):
        return "character_candidate_name_required"
    names = [str(item["name"]).strip() for item in candidates]
    if len(set(names)) != len(names):
        return "character_candidates_must_be_unique"
    return None


def _score(candidate: Mapping[str, Any], state: Mapping[str, Any]) -> AcquisitionScore:
    name = str(candidate.get("name", "")).strip()
    score = float(candidate.get("base_score", 0))
    reasons: list[str] = []
    owned = {str(item).strip() for item in state.get("owned_characters", []) if str(item).strip()} 
    if name in owned:
        score -= 1000
        reasons.append("重複所持")

    wanted_roles = _values(state.get("needed_roles", state.get("priority_roles", [])))
    if _values(candidate.get("role", candidate.get("roles", []))) & wanted_roles:
        score += float(state.get("role_bonus", 30))
        reasons.append("不足役割を補完")

    wanted_attributes = _values(state.get("needed_attributes", state.get("priority_attributes", [])))
    if _values(candidate.get("attributes", candidate.get("attribute", []))) & wanted_attributes:
        score += float(state.get("attribute_bonus", 15))
        reasons.append("属性適合")

    target_bosses = _values(state.get("future_targets", state.get("target_bosses", [])))
    boss_tags = _values(candidate.get("bosses", candidate.get("boss_tags", [])))
    if target_bosses & boss_tags:
        score += float(state.get("boss_bonus", 35))
        reasons.append("今後のボス適性")

    if candidate.get("rare_opportunity") is True:
        score += float(state.get("rare_opportunity_bonus", 20))
        reasons.append("入手機会が希少")
    if candidate.get("exclusive_sp", candidate.get("has_exclusive_sp")) is True:
        score += float(state.get("exclusive_sp_bonus", 25))
        reasons.append("専用SPあり")
    if candidate.get("exclusive_equipment", candidate.get("has_exclusive_equipment")) is True:
        score += float(state.get("exclusive_equipment_bonus", 20))
        reasons.append("専用装備あり")
    if candidate.get("cr15", candidate.get("has_cr15")) is True or str(candidate.get("equipment_set", "")).upper() == "CR15":
        score += float(state.get("cr15_bonus", 40))
        reasons.append("CR15が希少")
    if str(state.get("objective", "high_score")) == "high_score":
        score += float(candidate.get("score_value", 0))
        if candidate.get("score_value"):
            reasons.append("高スコア寄与")
    price = candidate.get("price")
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        score -= float(price) * float(state.get("price_penalty", 0.05))
        reasons.append("購入コスト")
    return AcquisitionScore(name, score, tuple(reasons))


def rank_acquisition_candidates(
    source: str, candidates: list[Mapping[str, Any]], state: Mapping[str, Any] | None = None
) -> list[AcquisitionScore]:
    """獲得地点と現在状態を考慮して候補を順位付けする。"""
    state = state or {}
    error = validate_candidates(source, list(candidates))
    if error:
        raise ValueError(error)
    owned = {str(item).strip() for item in state.get("owned_characters", []) if str(item).strip()}
    ranked = [_score(item, state) for item in candidates if str(item.get("name", "")).strip() not in owned]
    return sorted(ranked, key=lambda item: (-item.score, item.name))


def choose_acquisition(
    source: str, candidates: list[Mapping[str, Any]], state: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """候補から安全に選択結果を返す。ランダム加入は選択しない。"""
    state = state or {}
    rule = source_rule(source)
    if rule is None:
        return None
    error = validate_candidates(source, list(candidates))
    if error:
        return {"status": "waiting", "reason": error}
    if rule["selection"] == "random":
        return {"status": "completed", "selection_allowed": False, "reason": "random_join_observe_only"}
    ranked = rank_acquisition_candidates(source, candidates, state)
    if not ranked:
        return {"status": "waiting", "reason": "all_character_candidates_already_owned"}
    if len(ranked) > 1 and float(ranked[0].score - ranked[1].score) < float(state.get("minimum_score_gap", 0)):
        return {"status": "waiting", "reason": "character_choice_ambiguous", "ranked": [item.__dict__ for item in ranked]}
    if rule["selection"] == "multi":
        count = int(rule["select_count"])
        # Initial guild candidates are selected as a set; preserve candidate order.
        selected = [item.name for item in ranked[:count]]
        return {"status": "completed", "selected": selected, "ranked": [item.__dict__ for item in ranked], "basis": "acquisition_score"}
    selected = ranked[0]
    return {"status": "completed", "selected": selected.name, "score": selected.score,
            "reasons": list(selected.reasons), "ranked": [item.__dict__ for item in ranked],
            "basis": "acquisition_score"}
