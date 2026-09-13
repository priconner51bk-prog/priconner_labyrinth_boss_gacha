"""ラビリンスのショップ（エリア2〜5）用の決定論的ルール。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


BONUS_THRESHOLDS = (4, 9, 15)
FIRST_REFRESH_COST = 300
SECOND_REFRESH_COST = 600
# ショップの遺物候補も、通常の遺物選択と同じ順位で比較する。
NO_CHARACTER_PURCHASE_AREAS = frozenset({2, 3})
SHOP_EFFECT_PRIORITY = ("会心", "守備", "強化", "加速", "弱体")


@dataclass(frozen=True)
class ShopDecision:
    action: str  # buy / refresh / skip
    candidate_index: int | None
    reason: str
    cost: int


def purchase_all_then_refresh(
    candidates: list[dict[str, Any]],
    *,
    area: int,
    rupies: int,
    refresh_count: int = 0,
    character_candidates: list[dict[str, Any]] | None = None,
    stage: str | None = None,
    next_enemy: str | None = None,
) -> list[ShopDecision]:
    """候補1・2・3を順番に購入し、購入後に1回目の更新を行う。

    候補の比較は遺物選択と同じ段階・効果順位を使う。残額3000以上なら
    300更新を確保し、エリア5では残額でキャラ候補も購入対象にする。
    """
    if area not in (2, 3, 4, 5):
        raise ValueError("ショップルールの対象エリアは2〜5です")
    if rupies < 0 or refresh_count < 0 or refresh_count > 2:
        raise ValueError("ルピと更新回数が不正です")

    actions: list[ShopDecision] = []
    remaining = rupies
    for index, item in enumerate(candidates[:3]):
        price = _number(item, "price", "cost", "rupee", default=-1)
        if price >= 0 and price <= remaining:
            actions.append(ShopDecision("buy", index, f"候補{index + 1}を購入", price))
            remaining -= price

    if refresh_count == 0 and remaining >= 3000:
        actions.append(ShopDecision("refresh", None, "残ルピ3000以上のため300更新", FIRST_REFRESH_COST))
        remaining -= FIRST_REFRESH_COST
    elif refresh_count == 0 and remaining >= FIRST_REFRESH_COST:
        actions.append(ShopDecision("refresh", None, "購入後の残額で1回目の更新", FIRST_REFRESH_COST))
        remaining -= FIRST_REFRESH_COST
    elif refresh_count >= 1:
        actions.append(ShopDecision("skip", None, "600ルピ更新を避ける", 0))

    # エリア5では遺物・更新の後に残ったルピでキャラ候補も購入する。
    if area in NO_CHARACTER_PURCHASE_AREAS or stage in {"2-4", "2", "3", "4"} or (area == 4 and next_enemy is None):
        return actions
    affordable_characters = []
    for index, item in enumerate(character_candidates or []):
        price = _number(item, "price", "cost", "rupee", default=-1)
        if price >= 0 and price <= remaining:
            affordable_characters.append((price, index))
    if affordable_characters:
        price, index = min(affordable_characters)
        actions.append(ShopDecision("buy_character", index, "遺物と更新後の残りルピでキャラを購入", price))
    return actions


def _number(item: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        if key in item:
            return int(item[key])
    return default


def _relic_stage(item: dict[str, Any]) -> int:
    """星数と効果値を同じ段階として扱い、確認できる最大値を採用する。"""
    values = []
    for key in ("level", "relic_level", "stars", "value", "effect_value"):
        if key in item:
            try:
                values.append(int(item[key]))
            except (TypeError, ValueError):
                continue
    return max(values, default=0)


def _relic_type(item: dict[str, Any]) -> str:
    return str(item.get("relic_type", item.get("type", item.get("effect", "unknown"))))


def _threshold_bonus(item: dict[str, Any], current_count: int, relic_level_totals: Mapping[str, int] | None) -> int:
    level = _relic_stage(item)
    if relic_level_totals is None:
        return int(current_count + 1 in BONUS_THRESHOLDS)
    before = int(relic_level_totals.get(_relic_type(item), 0))
    after = before + level
    return int(any(before < threshold <= after for threshold in BONUS_THRESHOLDS))


def _effect_rank(item: dict[str, Any]) -> int:
    effect = str(item.get("effect", item.get("relic_type", item.get("type", ""))))
    try:
        return len(SHOP_EFFECT_PRIORITY) - SHOP_EFFECT_PRIORITY.index(effect)
    except ValueError:
        return 0


def _buy_score(
    item: dict[str, Any],
    current_count: int,
    relic_level_totals: Mapping[str, int] | None = None,
) -> tuple[int, int, int, int]:
    level = _relic_stage(item)
    price = _number(item, "price", "cost", "rupee")
    threshold_bonus = _threshold_bonus(item, current_count, relic_level_totals)
    # レベルを最優先。閾値到達、安さは同レベル内の比較にだけ使う。
    return (level, _effect_rank(item), threshold_bonus, -price)


def choose_shop_action(
    candidates: list[dict[str, Any]],
    *,
    area: int,
    rupies: int,
    relic_count: int,
    refresh_count: int = 0,
    relic_level_totals: Mapping[str, int] | None = None,
    character_candidates: list[dict[str, Any]] | None = None,
    selected_characters: list[str] | None = None,
    next_enemy: str | None = None,
    current_roles: list[str] | None = None,
    current_attributes: list[str] | None = None,
) -> ShopDecision:
    """ショップ候補から購入・更新・見送りを選ぶ。

    残ルピが3000以上で未更新なら、候補購入より先に300更新する。それ以外は
    遺物と同じ段階・効果順位で購入し、購入不能時のみ300更新を検討する。
    """
    if area not in (2, 3, 4, 5):
        raise ValueError("ショップルールの対象エリアは2〜5です")
    if rupies < 0 or relic_count < 0 or refresh_count < 0:
        raise ValueError("ルピ、遺物数、更新回数は0以上で指定してください")
    if refresh_count > 2:
        raise ValueError("更新回数は最大2回です")

    affordable = []
    for index, item in enumerate(candidates):
        price = _number(item, "price", "cost", "rupee", default=-1)
        if price >= 0 and price <= rupies:
            affordable.append((index, item))
    # 3000以上なら、購入より先に明示された300更新を確保する。
    if refresh_count == 0 and rupies >= 3000:
        return ShopDecision("refresh", None, "残ルピ3000以上のため300更新", FIRST_REFRESH_COST)

    if affordable:
        index, item = max(affordable, key=lambda pair: _buy_score(pair[1], relic_count, relic_level_totals))
        relic_score = _relic_shop_score(item, relic_count, relic_level_totals, next_enemy, current_roles, current_attributes)

        # キャラ購入はエリア5、またはエリア4で不足ロール/属性を補完できる場合だけ比較する。
        character_choice = _best_character_candidate(
            character_candidates, rupies, area=area, next_enemy=next_enemy,
            selected_characters=selected_characters, current_roles=current_roles,
            current_attributes=current_attributes,
        )
        if character_choice is not None and character_choice[0] > relic_score:
            character_score, character_index, character = character_choice
            price = _number(character, "price", "cost", "rupee")
            return ShopDecision(
                "buy_character", character_index,
                f"キャラを遺物より優先（スコア{character_score} > {relic_score}）",
                price,
            )
        level = _relic_stage(item)
        if relic_level_totals is None:
            threshold = ""
        else:
            before = int(relic_level_totals.get(_relic_type(item), 0))
            after = before + level
            threshold = "。遺物種別レベル合計ボーナス到達" if any(before < t <= after for t in BONUS_THRESHOLDS) else ""
        price = _number(item, "price", "cost", "rupee")
        comparison = ""
        if character_choice is not None:
            comparison = f"。キャラ候補より優先（スコア{relic_score} >= {character_choice[0]}）"
        return ShopDecision("buy", index, f"レベル{level}を最優先で購入{threshold}{comparison}", price)

    character_choice = _best_character_candidate(
        character_candidates, rupies, area=area, next_enemy=next_enemy,
        selected_characters=selected_characters, current_roles=current_roles,
        current_attributes=current_attributes,
    )
    if character_choice is not None:
        score, index, item = character_choice
        price = _number(item, "price", "cost", "rupee")
        return ShopDecision("buy_character", index, f"購入可能な遺物がなく、キャラを購入（スコア{score}）", price)

    # 2回目更新（600）は避ける。1回目の300だけ許可する。
    if refresh_count == 0 and rupies >= FIRST_REFRESH_COST:
        return ShopDecision("refresh", None, "購入可能な遺物がないため、1回目の更新", FIRST_REFRESH_COST)
    if refresh_count >= 1:
        return ShopDecision("skip", None, "600ルピ更新を避ける", 0)
    return ShopDecision("skip", None, "ルピ不足で購入・更新できない", 0)


def _relic_shop_score(
    item: dict[str, Any], current_count: int,
    relic_level_totals: Mapping[str, int] | None,
    next_enemy: str | None,
    current_roles: list[str] | None,
    current_attributes: list[str] | None,
) -> int:
    level = _number(item, "level", "relic_level", "stars")
    score = level * 10 + _effect_rank(item)
    score += _threshold_bonus(item, current_count, relic_level_totals) * 20
    score += _match_bonus(item, next_enemy, ("enemy_bonus", "boss_bonus", "preferred_enemies")) * 8
    score += _match_bonus(item, current_roles, ("role_bonus", "preferred_roles", "roles")) * 6
    score += _match_bonus(item, current_attributes, ("attribute_bonus", "preferred_attributes", "attributes")) * 4
    return score - int(_number(item, "price", "cost", "rupee") * 0.05)


def _best_character_candidate(
    candidates: list[dict[str, Any]] | None, rupies: int, *, area: int,
    next_enemy: str | None, selected_characters: list[str] | None,
    current_roles: list[str] | None, current_attributes: list[str] | None,
) -> tuple[int, int, dict[str, Any]] | None:
    if not candidates or area in NO_CHARACTER_PURCHASE_AREAS or next_enemy is None:
        return None
    selected = set(selected_characters or [])
    role_set, attribute_set = set(current_roles or []), set(current_attributes or [])
    scored = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict) or str(item.get("name", "")) in selected:
            continue
        price = _number(item, "price", "cost", "rupee", default=-1)
        if price < 0 or price > rupies:
            continue
        roles = _as_values(item.get("role", item.get("roles")))
        attributes = _as_values(item.get("attribute", item.get("attributes")))
        score = int(float(item.get("base_score", 0)))
        score += _match_bonus(item, next_enemy, ("enemy_bonus", "boss_bonus", "preferred_enemies")) * 8
        score += 15 if roles.isdisjoint(role_set) and roles else 0
        score += 10 if attributes.isdisjoint(attribute_set) and attributes else 0
        score += _number(item, "relic_synergy", "relic_bonus", default=0)
        score -= int(price * 0.05)
        scored.append((score, -price, -index, index, item))
    if not scored:
        return None
    score, _, _, index, item = max(scored)
    return score, index, item


def _as_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    return set()


def _match_bonus(item: dict[str, Any], target: Any, keys: tuple[str, ...]) -> int:
    targets = {target} if isinstance(target, str) else _as_values(target)
    if not targets:
        return 0
    values: set[str] = set()
    for key in keys:
        values |= _as_values(item.get(key))
    return int(bool(values & targets))
