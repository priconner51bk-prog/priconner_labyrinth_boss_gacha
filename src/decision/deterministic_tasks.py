"""画面入力を伴わない、決定済み事実のタスク処理。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from .labyrinth_orchestrator import Task, TaskResult, TaskStatus


AREA_BOSS_NAMES = {
    "3": frozenset({"マダムエレクトラ", "フロストハウンド", "ダークガーゴイル", "グレーターゴーレム", "ベノムサラマンドラ"}),
    "5": frozenset({"キマイラ", "ゴブリンロード", "ラースドラゴン", "アルティマガーディアン", "ジャバウォック"}),
}

# OCR may return a documented reading variant. Keep stored facts canonical so
# aliases cannot accidentally bypass target matching.
AREA_BOSS_ALIASES = {
    "アルティメガーディアン": "アルティマガーディアン",
}
EX_EQUIPMENT_MANUAL_EXCEPTION_STAGES = frozenset({"3-5"})


def _canonical_boss_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", value)
    return _configured_boss_aliases().get(normalized, AREA_BOSS_ALIASES.get(normalized, normalized))


@lru_cache(maxsize=1)
def _configured_battle_patterns() -> Mapping[str, Any]:
    config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_battle_patterns.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    patterns = data.get("patterns") if isinstance(data, dict) else None
    return patterns if isinstance(patterns, Mapping) else {}


@lru_cache(maxsize=1)
def _configured_ex_manual_stages() -> frozenset[str]:
    config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_battle_patterns.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return EX_EQUIPMENT_MANUAL_EXCEPTION_STAGES
    values = data.get("ex_equipment_manual_exception_stages") if isinstance(data, dict) else None
    if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
        return EX_EQUIPMENT_MANUAL_EXCEPTION_STAGES
    return frozenset(value.strip() for value in values)


@lru_cache(maxsize=1)
def _configured_boss_aliases() -> Mapping[str, str]:
    aliases: dict[str, str] = {}
    root = Path(__file__).resolve().parents[2] / "configs"
    for filename in ("boss_area3.json", "boss_area5.json"):
        try:
            data = json.loads((root / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("bosses", []) if isinstance(data, dict) else []:
            if not isinstance(item, Mapping):
                continue
            canonical = str(item.get("name", "")).strip()
            if canonical:
                for alias in item.get("ocr_aliases", []):
                    aliases[str(alias).strip()] = canonical
    return aliases


def _configured_battle_pattern(enemy_type: str) -> Mapping[str, Any] | None:
    for category in _configured_battle_patterns().values():
        if isinstance(category, Mapping) and isinstance(category.get(enemy_type), Mapping):
            return category[enemy_type]
    return None


@lru_cache(maxsize=1)
def _configured_relic_pattern() -> Mapping[str, Any]:
    config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_battle_patterns.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pattern = data.get("relic") if isinstance(data, dict) else None
    return pattern if isinstance(pattern, Mapping) else {}


@lru_cache(maxsize=1)
def _configured_preferred_guilds() -> tuple[str, ...]:
    config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_guild_starting_members.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    policy = data.get("selection_policy") if isinstance(data, dict) else None
    values = policy.get("preferred_guilds") if isinstance(policy, Mapping) else None
    if not isinstance(values, list):
        return ()
    preferred = tuple(str(value).strip() for value in values if str(value).strip())
    guilds = data.get("guilds") if isinstance(data, dict) else None
    known = {str(name).strip() for name in guilds} if isinstance(guilds, Mapping) else set()
    if preferred and all(value in known for value in preferred):
        return preferred
    # Keep the documented preference available when an older config was
    # saved with a damaged Japanese encoding.
    return ("\u7f8e\u98df\u6bbf", "\u30d5\u30a9\u30ec\u30b9\u30c6\u30a3\u30a8")


@lru_cache(maxsize=1)
def _configured_guild_names() -> frozenset[str]:
    config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_guild_starting_members.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    guilds = data.get("guilds") if isinstance(data, dict) else None
    return frozenset(str(name).strip() for name in guilds if str(name).strip()) if isinstance(guilds, Mapping) else frozenset()


def _normalize_character_name(value: str) -> str:
    """Compare OCR names while ignoring star/rank decorations."""
    return re.sub(r"[★☆*０-９0-9\s]", "", unicodedata.normalize("NFKC", value)).lower()


def _waiting(reason: str) -> TaskResult:
    return TaskResult(TaskStatus.WAITING, reason=reason)


def _learned_priority_order(state: Mapping[str, Any], enemy: str, stage: str) -> tuple[list[str], dict[str, Any] | None]:
    """シーン（敵・ステージ）の学習済みキャラ優先順をキャラ名の並びで返す。

    基準（試行数・勝率）を満たすキャラがいない場合は空リストを返し、
    候補の元の順序を維持する。ユーザーピックは維持しつつ、学習済みの
    強キャラを候補先頭に並べる補正として使う。
    """
    from .character_priority_learning import learn_character_priorities, load_priority_records

    path = state.get("character_priority_feedback_path") or (Path(__file__).resolve().parents[2] / "data/knowledge/character_priority.jsonl")
    records = load_priority_records(path)
    if not records:
        return [], None
    learned = learn_character_priorities(
        records,
        enemy=enemy,
        stage=stage,
        min_trials=int(state.get("learning_min_trials", 3)),
        min_win_rate=float(state.get("learning_min_win_rate", 0.6)),
    )
    if learned is None:
        return [], None
    return list(learned["priority_characters"]), learned


def _rank_by_learned_priority(candidates: list[dict[str, Any]], priority: list[str]) -> list[dict[str, Any]]:
    """学習済みキャラを先頭に安定ソート。未学習キャラは元の順序を保持する。"""
    if not priority:
        return list(candidates)
    order = {name: index for index, name in enumerate(priority)}
    return sorted(candidates, key=lambda item: order.get(str(item.get("name", "")).strip(), len(order)))


def check_passports(state: Mapping[str, Any]) -> TaskResult:
    passports = state.get("passports")
    if isinstance(passports, (list, tuple)):
        from vision.passport_ocr import parse_passport_count
        parsed = parse_passport_count(passports)
        if parsed is not None:
            passports = parsed
    if isinstance(passports, Mapping):
        nested = passports.get("count", passports.get("passports"))
        if isinstance(nested, (int, str)) and not isinstance(nested, bool):
            passports = nested
    if isinstance(passports, str):
        compact = re.sub(r"\s+", "", passports)
        if compact.isdigit():
            passports = int(compact)
        else:
            match = re.search(r"(?:ラビリンス)?パスポート[^0-9０-９]*([0-9０-９]{1,3})", compact)
            if match:
                passports = int(unicodedata.normalize("NFKC", match.group(1)))
    if isinstance(passports, bool) or not isinstance(passports, int) or passports < 0:
        return _waiting("passport_count_required")
    return TaskResult(TaskStatus.COMPLETED, {"passports": passports})


def launch_labyrinth(state: Mapping[str, Any]) -> TaskResult:
    if state.get("labyrinth_started") is not True:
        if state.get("screen_id") in {
            "guild_select", "guild_confirm", "bonus", "initial_char", "boss_map", "boss_detail",
        }:
            return TaskResult(TaskStatus.COMPLETED, {
                "labyrinth_started": True,
                "labyrinth_started_basis": "observed_post_launch_screen",
            })
        return _waiting("labyrinth_launch_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"labyrinth_started": True})


def initial_setup(state: Mapping[str, Any]) -> TaskResult:
    if state.get("initial_setup_done") is not True:
        # These screens are only reachable after the map/entry setup has
        # completed. Use the observed screen as a deterministic fact instead
        # of asking for a redundant confirmation.
        if state.get("screen_id") in {"initial_char", "boss_map", "boss_detail"}:
            return TaskResult(TaskStatus.COMPLETED, {
                "initial_setup_done": True,
                "initial_setup_basis": "observed_post_setup_screen",
            })
        return _waiting("initial_setup_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"initial_setup_done": True})


def close_dialog(state: Mapping[str, Any]) -> TaskResult:
    if state.get("dialog_closed") is not True:
        if state.get("dialog_visible") is False:
            return TaskResult(TaskStatus.COMPLETED, {"dialog_closed": True, "dialog_closed_basis": "explicit_not_visible"})
        return _waiting("dialog_close_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"dialog_closed": True})


def next_screen(state: Mapping[str, Any]) -> TaskResult:
    if state.get("next_pressed") is not True:
        if state.get("next_visible") is False:
            return TaskResult(TaskStatus.COMPLETED, {"next_pressed": True, "next_pressed_basis": "explicit_not_visible"})
        return _waiting("next_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"next_pressed": True})


def withdraw(state: Mapping[str, Any]) -> TaskResult:
    if state.get("withdrawn") is not True:
        if state.get("screen_id") == "labyrinth_top":
            return TaskResult(TaskStatus.COMPLETED, {
                "withdrawn": True,
                "withdrawal_basis": "observed_labyrinth_top",
            })
        return _waiting("withdrawal_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"withdrawn": True})


def return_labyrinth_top(state: Mapping[str, Any]) -> TaskResult:
    if state.get("screen_id") != "labyrinth_top":
        return _waiting("labyrinth_top_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"returned_labyrinth_top": True})


def check_area(state: Mapping[str, Any]) -> TaskResult:
    area = state.get("area")
    if isinstance(area, Mapping):
        nested = area.get("number", area.get("area"))
        if isinstance(nested, (int, str)) and not isinstance(nested, bool):
            area = nested
    if isinstance(area, str):
        compact = unicodedata.normalize("NFKC", re.sub(r"\s+", "", area))
        if compact.isdigit():
            area = int(compact)
        else:
            match = re.fullmatch(r"エリア([1-5])(?:/5)?", compact)
            if match:
                area = int(match.group(1))
    if isinstance(area, bool) or not isinstance(area, int) or area not in range(1, 6):
        return _waiting("area_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"area": area})


def check_boss_names(state: Mapping[str, Any]) -> TaskResult:
    """Validate the ordered area-3/area-5 OCR result before policy evaluation."""
    names = state.get("boss_names")
    if isinstance(names, (list, tuple)) and len(names) == 2:
        names = {"3": names[0], "5": names[1]}
    if not isinstance(names, Mapping):
        return _waiting("boss_names_confirmation_required")
    normalized_keys: dict[str, Any] = {}
    for key, value in names.items():
        normalized_key = re.sub(r"\s+", "", str(key)).replace("エリア", "")
        if normalized_key in normalized_keys and normalized_keys[normalized_key] != value:
            return _waiting("boss_names_ambiguous_area_key")
        normalized_keys[normalized_key] = value
    confirmed: dict[str, str] = {}
    for area in ("3", "5"):
        value = normalized_keys.get(area)
        if isinstance(value, (list, tuple)):
            values = [getattr(item, "text", item) for item in value]
            values = [item for item in values if isinstance(item, str) and item.strip()]
            value = values[0] if len(values) == 1 else None
        if hasattr(value, "text"):
            value = getattr(value, "text")
        if not isinstance(value, str) or not value.strip():
            return _waiting(f"boss_name_confirmation_required:{area}")
        confirmed[area] = _canonical_boss_name(value)
        if confirmed[area] not in AREA_BOSS_NAMES[area]:
            return TaskResult(
                TaskStatus.FAILED,
                {"boss_names": confirmed},
                reason=f"unknown_boss_name:{area}",
            )
    return TaskResult(TaskStatus.COMPLETED, {"boss_names": confirmed, "boss_names_ready": True})


def check_current_screen(state: Mapping[str, Any]) -> TaskResult:
    from .screen_guard import classify_resume_screen
    decision = classify_resume_screen(state.get("screen_id"), challenge_active=state.get("challenge_active", False))
    return TaskResult(TaskStatus.COMPLETED, decision) if decision else _waiting("current_screen_confirmation_required")


def scan_area_map(state: Mapping[str, Any]) -> TaskResult:
    area_map = state.get("area_map")
    if not isinstance(area_map, (list, dict)) or not area_map:
        # Live OCR adapters can provide raw lines without first constructing
        # the task contract. Convert only high-confidence, positioned labels;
        # missing/unknown nodes remain a safe waiting condition.
        lines = state.get("map_ocr_lines")
        if isinstance(lines, (list, tuple)):
            from vision.labyrinth_map_ocr import extract_map_nodes
            area_map = extract_map_nodes(lines, min_confidence=float(state.get("map_min_confidence", 0.75)))
    if not isinstance(area_map, (list, dict)) or not area_map:
        return _waiting("area_map_confirmation_required")
    facts: dict[str, Any] = {"area_map": area_map, "area_map_scanned": True}
    if state.get("auto_build_graph") is True:
        from .route_planner import normalize_map_graph
        graph = normalize_map_graph(area_map)
        if graph is None:
            return TaskResult(TaskStatus.WAITING, facts, "map_connections_confirmation_required")
        facts["area_graph"] = graph
    return TaskResult(TaskStatus.COMPLETED, facts)


def initial_continue_decision(state: Mapping[str, Any]) -> TaskResult:
    decision = state.get("continue_run")
    if decision is None and state.get("auto_continue_decision") is True:
        names = state.get("boss_names")
        area_map = state.get("area_map")
        targets = state.get("target_bosses", {"3": "ベノムサラマンドラ", "5": "ゴブリンロード"})
        if isinstance(names, Mapping) and isinstance(targets, Mapping) and isinstance(area_map, (list, dict)) and area_map:
            normalized_names = {
                str(key): _canonical_boss_name(str(value)) for key, value in names.items()
            }
            normalized_targets = {str(key): str(value).strip() for key, value in targets.items()}
            decision = all(normalized_names.get(area) == normalized_targets.get(area) for area in ("3", "5"))
            return TaskResult(TaskStatus.COMPLETED, {
                "continue_run": decision,
                "continue_decision_basis": "target_boss_pair_and_map",
            })
    if not isinstance(decision, bool):
        return _waiting("continue_decision_required")
    return TaskResult(TaskStatus.COMPLETED, {"continue_run": decision})


def handle_tile(state: Mapping[str, Any]) -> TaskResult:
    tile_type = state.get("tile_type")
    if isinstance(tile_type, Mapping):
        nested = tile_type.get("type", tile_type.get("tile"))
        tile_type = nested if isinstance(nested, str) else None
    aliases = {
        "normal": "normal", "通常": "normal",
        "extreme": "extreme", "Extreme": "extreme", "EX": "extreme",
        "hell": "hell", "HELL": "hell",
        "遺物": "relic", "relic": "relic",
        "コネクトサイン": "connect_sign", "connect_sign": "connect_sign",
        "SHOP": "shop", "ショップ": "shop", "shop": "shop",
        "event": "event", "イベント": "event",
        "エリアボス": "area_boss", "area_boss": "area_boss",
        "エリアスタート": "area_start", "area_start": "area_start",
    }
    if isinstance(tile_type, str):
        tile_type = tile_type.strip()
    if not isinstance(tile_type, str) or tile_type not in aliases:
        return _waiting("tile_type_confirmation_required")
    canonical = aliases[tile_type]
    if canonical == "event":
        event_type = state.get("event_type")
        if isinstance(event_type, Mapping):
            nested = event_type.get("name", event_type.get("type"))
            event_type = nested if isinstance(nested, str) else None
        if isinstance(event_type, str):
            event_type = re.sub(r"\s+", "", event_type)
            event_type = {"じゃんけん": "janken", "JANKEN": "janken", "エクストリーム": "extreme", "EXTREME": "extreme"}.get(event_type, event_type)
        if event_type not in {"janken", "extreme"}:
            return _waiting("event_type_confirmation_required")
        if event_type == "janken" and state.get("auto_select_event") is True:
            return TaskResult(TaskStatus.COMPLETED, {
                "tile_type": canonical, "event_type": event_type,
                "event_choice": 2, "event_choice_basis": "fixed_script_candidate_2",
                "tile_handled": True,
            })
        return TaskResult(TaskStatus.COMPLETED, {
            "tile_type": canonical, "event_type": event_type, "tile_handled": False,
        })
    if canonical == "shop":
        area = state.get("area")
        if isinstance(area, bool) or not isinstance(area, int) or area not in {2, 3, 4, 5}:
            return _waiting("shop_area_confirmation_required")
        facts: dict[str, Any] = {
            "tile_type": canonical, "shop_area": area, "tile_handled": False,
        }
        if state.get("auto_select_shop") is True and area in {2, 3, 4, 5}:
            candidates = state.get("shop_candidates")
            rupies = state.get("rupies")
            relic_count = state.get("relic_count")
            if isinstance(candidates, list) and isinstance(rupies, int) and not isinstance(rupies, bool) and rupies >= 0 and isinstance(relic_count, int) and not isinstance(relic_count, bool) and relic_count >= 0:
                from .labyrinth_shop import choose_shop_action
                refresh_count = state.get("refresh_count", 0)
                if not isinstance(refresh_count, int) or isinstance(refresh_count, bool) or refresh_count < 0:
                    refresh_count = 0
                decision = choose_shop_action(
                    candidates,
                    area=area,
                    rupies=rupies,
                    relic_count=relic_count,
                    refresh_count=refresh_count,
                    character_candidates=state.get("character_candidates"),
                    selected_characters=state.get("selected_characters"),
                    next_enemy=state.get("next_enemy", state.get("boss_name")),
                    current_roles=state.get("current_roles"),
                    current_attributes=state.get("current_attributes"),
                )
                facts["shop_decision"] = {
                    "action": decision.action, "candidate_index": decision.candidate_index,
                    "reason": decision.reason, "cost": decision.cost,
                }
        return TaskResult(TaskStatus.COMPLETED, facts)
    return TaskResult(TaskStatus.COMPLETED, {"tile_type": canonical, "tile_handled": False})


def plan_route(state: Mapping[str, Any]) -> TaskResult:
    route = state.get("route")
    aliases = {
        "normal": "normal", "通常": "normal", "extreme": "extreme", "Extreme": "extreme", "EX": "extreme",
        "hell": "hell", "HELL": "hell", "relic": "relic", "遺物": "relic",
        "connect_sign": "connect_sign", "コネクトサイン": "connect_sign", "shop": "shop", "SHOP": "shop", "ショップ": "shop",
        "event": "event", "イベント": "event", "area_boss": "area_boss", "エリアボス": "area_boss",
        "area_start": "area_start", "エリアスタート": "area_start",
    }
    route = state.get("route")
    if route is None and state.get("auto_plan_route") is True:
        graph = state.get("area_graph")
        start = state.get("route_start")
        if isinstance(graph, Mapping) and isinstance(start, str):
            from .route_planner import find_route
            avoid_hell = state.get("area") in {4, 5} and int(state.get("relic_level_total", 0)) >= 15
            route = find_route(graph, start=start, avoid_hell=avoid_hell)
            if route is None:
                return _waiting("route_graph_has_no_safe_path")
    if not isinstance(route, list) or not route:
        return _waiting("route_confirmation_required")
    normalized_route = [tile.strip() if isinstance(tile, str) else tile for tile in route]
    if not all(isinstance(tile, str) and tile in aliases for tile in normalized_route):
        return _waiting("route_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"route": [aliases[tile] for tile in normalized_route], "route_index": 0})


def move_route(state: Mapping[str, Any]) -> TaskResult:
    route = state.get("route")
    index = state.get("route_index", 0)
    if not isinstance(route, list) or isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(route):
        return _waiting("route_step_required")
    tile_type = route[index]
    return TaskResult(TaskStatus.COMPLETED, {"tile_type": tile_type, "route_index": index + 1})


def confirm_move(state: Mapping[str, Any]) -> TaskResult:
    if state.get("move_confirmed") is True:
        return TaskResult(TaskStatus.COMPLETED, {"move_confirmed": True})
    if state.get("move_confirmation_visible") is False:
        return TaskResult(TaskStatus.COMPLETED, {"move_confirmed": True, "move_confirmed_basis": "dialog_not_visible"})
    return TaskResult(TaskStatus.COMPLETED, {"move_confirmed": True, "move_confirmed_basis": "fixed_ok_tap"})


def identify_enemy(state: Mapping[str, Any]) -> TaskResult:
    enemy_type = state.get("enemy_type")
    if isinstance(enemy_type, (list, tuple)):
        values = [getattr(item, "text", item) for item in enemy_type]
        values = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        enemy_type = values[0] if len(values) == 1 else None
    if isinstance(enemy_type, Mapping):
        nested = enemy_type.get("name", enemy_type.get("type"))
        enemy_type = nested if isinstance(nested, str) else None
    if enemy_type is None and state.get("tile_type") in {"area_boss", "エリアボス"}:
        return TaskResult(TaskStatus.COMPLETED, {
            "enemy_type": "area_boss",
            "enemy_type_basis": "area_boss_tile",
        })
    if not isinstance(enemy_type, str) or not enemy_type.strip():
        return _waiting("enemy_confirmation_required")
    normalized = re.sub(r"\s+", "", enemy_type)
    category = {
        "通常": "normal", "通常戦闘": "normal", "normal": "normal",
        "EX": "extreme", "Extreme": "extreme", "extreme": "extreme", "エクストリーム": "extreme",
        "HELL": "hell", "hell": "hell", "ヘル": "hell",
        "エリアボス": "area_boss", "area_boss": "area_boss",
    }.get(normalized)
    return TaskResult(TaskStatus.COMPLETED, {"enemy_type": category or enemy_type.strip()})


def prepare_battle(state: Mapping[str, Any]) -> TaskResult:
    enemy_type = state.get("enemy_type")
    if not isinstance(enemy_type, str) or not enemy_type.strip():
        return _waiting("enemy_type_required_for_battle_setup")
    is_area_boss = (
        state.get("is_area_boss") is True
        or state.get("tile_type") == "area_boss"
        or enemy_type.strip() == "area_boss"
    )
    required = 3 if is_area_boss else 1
    if is_area_boss:
        # 原則は5人×3編成。編成・遺物効果から必要数を別途評価できた
        # 場合だけ、1または2編成へ減らせる（未指定は安全側の3編成）。
        estimated = state.get("area_boss_composition_count")
        if estimated is None:
            estimated = state.get("expected_area_boss_compositions")
        if estimated is not None:
            if isinstance(estimated, bool) or not isinstance(estimated, int) or not 1 <= estimated <= 3:
                return _waiting("area_boss_composition_count_invalid")
            required = estimated
    # 初回戦闘は初期加入直後でキャラプールが少ないため、4人編成を
    # ナレッジ上の既定値とする。通常戦闘は従来どおり5人を要求する。
    is_initial_battle = (
        state.get("initial_battle") is True
        or state.get("is_initial_battle") is True
        or str(state.get("stage", "")).strip() in {"1-1", "1_1"}
    )
    default_team_size = 4 if is_initial_battle and not is_area_boss else 5
    confirmations = state.get("composition_confirmations")
    selected_composition = state.get("selected_composition")
    composition_auto_promoted = False
    if state.get("learning_mode") is True and (confirmations is None or not isinstance(confirmations, list) or not all(item is True for item in confirmations)):
        # 学習済み条件だけは、ユーザー補助からスクリプトへ自動昇格する。
        # データ不足・キャラプール不一致の場合は従来どおり停止して確認を求める。
        from .composition_learning import automation_gate, learned_composition, load_feedback
        feedback_path = state.get("composition_feedback_path") or (Path(__file__).resolve().parents[2] / "data/knowledge/composition_feedback.jsonl")
        feedback = load_feedback(feedback_path)
        learned = learned_composition(
            feedback, enemy=enemy_type.strip(),
            stage=str(state.get("stage", "unknown")),
            min_victories=int(state.get("learning_min_victories", 3)),
            min_win_rate=float(state.get("learning_min_win_rate", 0.8)),
        )
        pool = state.get("character_pool")
        # Promotion is human-approved by default.  Only an explicit False
        # opts out; an absent or malformed approval context therefore fails
        # closed through automation_gate.
        promotion_allowed = state.get("require_human_approval_for_promotion") is False
        if not promotion_allowed:
            approval_gate = automation_gate(
                feedback, [(enemy_type.strip(), str(state.get("stage", "unknown")))],
                min_victories=int(state.get("learning_min_victories", 3)),
                min_win_rate=float(state.get("learning_min_win_rate", 0.8)),
                approvals=state.get("composition_approvals") if isinstance(state.get("composition_approvals"), list) else [],
                context=state.get("composition_context") if isinstance(state.get("composition_context"), Mapping) else {},
            )
            promotion_allowed = bool(approval_gate["enabled"])
        if promotion_allowed and learned is not None and isinstance(pool, list):
            names = [str(item.get("name", "")).strip() for item in pool if isinstance(item, Mapping)]
            groups: list[list[str]] = []
            for group in learned["selected_indices"]:
                if not isinstance(group, list) or any(not isinstance(index, int) or not 1 <= index <= len(names) for index in group):
                    groups = []
                    break
                groups.append([names[index - 1] for index in group])
            if groups and all(all(name for name in group) for group in groups):
                selected_composition = groups if is_area_boss else groups[0]
                confirmations = [True] * required
                # 状況表示・監査ログに自動昇格の根拠を残す。
                composition_auto_promoted = True
        if confirmations is not None and isinstance(confirmations, list) and all(item is True for item in confirmations):
            pass
        else:
            candidates = []
            pool = state.get("character_pool")
            if isinstance(pool, list):
                for item in pool:
                    if isinstance(item, Mapping) and str(item.get("name", "")).strip():
                        candidates.append({"name": str(item["name"]).strip(), "score": item.get("score"), "role": item.get("role"), "attribute": item.get("attribute")})
            from .composition_learning import learning_progress
            progress = learning_progress(load_feedback(feedback_path), enemy=enemy_type.strip(), stage=str(state.get("stage", "unknown")))
            priority, learned_priority = _learned_priority_order(state, enemy_type.strip(), str(state.get("stage", "unknown")))
            if priority:
                candidates = _rank_by_learned_priority(candidates, priority)
            return TaskResult(TaskStatus.WAITING, {
                "composition_candidates": candidates,
                "character_priority": {"learned": learned_priority is not None, "priority_characters": priority},
                "composition_count": required,
                "team_size": default_team_size,
                "learning_status": {"mode": "assisted", "reason": "insufficient_confirmed_outcomes", **progress},
            }, "battle_composition_manual_selection_required")
    if confirmations is None and state.get("auto_select_composition") is True:
        pool = state.get("character_pool")
        pattern = state.get("battle_pattern")
        # An omitted enemy-specific pattern is still deterministic: rank by
        # the supplied base scores rather than handing a solvable choice back
        # to AI/user confirmation.
        if isinstance(pool, list) and pool:
            if not isinstance(pattern, Mapping):
                pattern = _configured_battle_pattern(enemy_type.strip()) or {}
            from .labyrinth_composition import rank_characters
            selected_members = state.get("selected_characters", [])
            if not isinstance(selected_members, list):
                selected_members = []
            # A defeat retry must not reward the failed team with the normal
            # ``selected_bonus``.  Keep retry exclusions separate from the
            # initial/ongoing selected members and filter them before scoring.
            excluded_members = state.get("excluded_characters", [])
            if isinstance(excluded_members, list):
                excluded_names = {str(name).strip() for name in excluded_members if isinstance(name, str) and name.strip()}
                if excluded_names:
                    pool = [item for item in pool if isinstance(item, Mapping) and str(item.get("name", "")).strip() not in excluded_names]
                    selected_members = [name for name in selected_members if str(name).strip() not in excluded_names]
            ranked = rank_characters(pool, selected_members, pattern)
            team_size = default_team_size if is_initial_battle and not is_area_boss else state.get("team_size", 5)
            if isinstance(team_size, int) and not isinstance(team_size, bool) and 1 <= team_size <= 5:
                if is_area_boss:
                    needed = required * team_size
                    names = [item.name for item in ranked[:needed]]
                    if len(names) == needed and len(set(names)) == needed:
                        selected_composition = [names[i:i + team_size] for i in range(0, needed, team_size)]
                        confirmations = [True] * required
                else:
                    selected_composition = [item.name for item in ranked[:team_size]]
                    if len(selected_composition) == team_size:
                        confirmations = [True]
    if not isinstance(confirmations, list) or len(confirmations) != required or not all(item is True for item in confirmations):
        facts = {"composition_recommendation": selected_composition} if selected_composition else {}
        return TaskResult(TaskStatus.WAITING, facts, f"composition_confirmation_required:{required}")
    ex_confirmed = state.get("ex_equipment_confirmed") is True
    ex_basis = None
    if not ex_confirmed and state.get("auto_select_ex_equipment") is True:
        # EX装備設定は全戦闘で実行する。エリア3-5も手動例外にせず、
        # 編成ごとの「他のキャラから」方針で共有競合だけを制御する。
        ex_confirmed = True
        ex_basis = "fixed_script_all_battles"
    if not ex_confirmed:
        return _waiting("ex_equipment_confirmation_required")
    facts = {"battle_prepared": True, "composition_count": required, "ex_equipment_confirmed": True}
    if composition_auto_promoted:
        facts["composition_auto_promoted"] = True
        facts["learned_composition"] = learned
    if is_area_boss:
        facts["team_size"] = 5
        facts["area_boss_composition_basis"] = "default_three" if required == 3 and state.get("area_boss_composition_count") is None and state.get("expected_area_boss_compositions") is None else "evaluated_clear_count"
    if is_initial_battle and not is_area_boss:
        facts["team_size"] = 4
    if ex_basis:
        facts["ex_equipment_basis"] = ex_basis
    if is_area_boss and isinstance(selected_composition, list) and selected_composition and (isinstance(selected_composition[0], list) or isinstance(selected_composition[0], Mapping)):
        from .ex_equipment_policy import plan_other_character_checkbox
        facts["ex_equipment_policy"] = plan_other_character_checkbox(
            selected_composition,
            team_scores=state.get("team_scores") if isinstance(state.get("team_scores"), list) else None,
            character_index=state.get("character_index") if isinstance(state.get("character_index"), Mapping) else None,
        )
    if selected_composition:
        facts["selected_composition"] = selected_composition
    facts["enemy_type"] = enemy_type.strip()
    return TaskResult(TaskStatus.COMPLETED, facts)


def start_battle(state: Mapping[str, Any]) -> TaskResult:
    if state.get("battle_prepared") is not True:
        return _waiting("battle_preparation_required")
    return TaskResult(TaskStatus.COMPLETED, {"battle_started": True})


def wait_battle_result(state: Mapping[str, Any]) -> TaskResult:
    outcome = state.get("battle_outcome")
    if isinstance(outcome, (list, tuple)):
        from vision.battle_result import classify_battle_result
        outcome = classify_battle_result(outcome)
    if isinstance(outcome, Mapping):
        raw_outcome = outcome.get("outcome")
        battle_type = outcome.get("battle_type")
        if isinstance(raw_outcome, str) and isinstance(battle_type, str):
            raw_outcome = re.sub(r"\s+", "", raw_outcome).lower()
            battle_type = re.sub(r"\s+", "", battle_type).lower()
            raw_outcome = {"勝利": "victory", "敗北": "defeat"}.get(raw_outcome, raw_outcome)
            if raw_outcome in {"victory", "defeat"}:
                if raw_outcome == "defeat":
                    outcome = "defeat"
                elif battle_type == "area_boss" and state.get("area") in {3, 5}:
                    outcome = f"area{state['area']}_boss"
                else:
                    outcome = battle_type if battle_type in {"extreme", "hell", "normal"} else "victory"
    aliases = {
        "勝利": "victory", "敗北": "defeat", "WIN": "victory", "LOSE": "defeat",
        "勝利/エリア3ボス": "area3_boss", "勝利/エリア5ボス": "area5_boss",
        "勝利/extreme": "extreme", "勝利/extrime": "extreme",
        "勝利/hell": "hell", "勝利/normal": "normal",
    }
    if isinstance(outcome, str):
        compact = re.sub(r"\s+", "", outcome)
        outcome = aliases.get(compact, compact)
    allowed = {"victory", "defeat", "area3_boss", "area5_boss", "extreme", "hell", "normal"}
    if not isinstance(outcome, str) or outcome not in allowed:
        return _waiting("battle_result_required")
    return TaskResult(TaskStatus.COMPLETED, {"battle_outcome": outcome, "battle_finished": True})


def select_reward(state: Mapping[str, Any]) -> TaskResult:
    choice = state.get("reward_choice", state.get("relic_choice"))
    if isinstance(choice, Mapping):
        nested = choice.get("index", choice.get("choice"))
        if isinstance(nested, (int, str)) and not isinstance(nested, bool):
            choice = nested
    if isinstance(choice, str) and choice.strip().isdigit():
        choice = int(choice.strip())
    if choice is None and state.get("auto_select_reward") is True:
        candidates = state.get("relic_candidates")
        if isinstance(candidates, list) and candidates:
            from .labyrinth_composition import rank_relics
            pattern = state.get("relic_pattern")
            if not isinstance(pattern, Mapping):
                pattern = _configured_relic_pattern()
            if isinstance(pattern, Mapping):
                selected = state.get("selected_relics", [])
                if not isinstance(selected, list):
                    selected = []
                selected_characters = state.get("selected_character_details", [])
                if not isinstance(selected_characters, list):
                    selected_characters = []
                if not selected_characters:
                    selected_names = state.get("selected_characters", [])
                    pool = state.get("character_pool", [])
                    if isinstance(selected_names, list) and isinstance(pool, list):
                        selected_set = {str(name).strip() for name in selected_names}
                        selected_characters = [
                            item for item in pool
                            if isinstance(item, Mapping) and str(item.get("name", "")).strip() in selected_set
                        ]
                boss_name = state.get("boss_name", state.get("enemy_name", state.get("enemy_type")))
                boss_name = boss_name if isinstance(boss_name, str) else None
                ranked = rank_relics(
                    candidates,
                    selected,
                    pattern,
                    selected_characters=selected_characters,
                    boss_name=boss_name,
                    star_priority=True,
                )
                if ranked:
                    selected_name = ranked[0].name
                    for index, candidate in enumerate(candidates, 1):
                        if isinstance(candidate, Mapping) and str(candidate.get("name", "")) == selected_name:
                            choice = index
                            break
        if choice is None:
            candidates = state.get("character_candidates")
            if isinstance(candidates, list) and candidates:
                selected_names = state.get("selected_characters", [])
                selected_names = set(selected_names) if isinstance(selected_names, list) else set()
                from .labyrinth_character_acquisition import choose_acquisition
                acquisition_state = dict(state)
                acquisition_state["owned_characters"] = list(selected_names)
                source = str(state.get("character_source") or {
                    "extreme": "extreme_reward",
                    "hell": "hell_reward",
                    "area3_boss": "area3_boss_reward",
                }.get(str(state.get("battle_outcome", "")), "character_reward"))
                decision = choose_acquisition(source, candidates, acquisition_state)
                if decision and decision.get("status") == "completed" and decision.get("selection_allowed", True):
                    return TaskResult(TaskStatus.COMPLETED, {
                        "character_selected": decision["selected"],
                        "character_selection_basis": decision.get("basis", "acquisition_score"),
                        "character_selection_score": decision.get("score"),
                        "character_selection_reasons": decision.get("reasons", []),
                        "character_selection_ranked": decision.get("ranked", []),
                    })
                if decision and decision.get("status") == "waiting":
                    return _waiting(str(decision.get("reason", "character_choice_required")))
    if isinstance(choice, int) and not isinstance(choice, bool) and choice >= 1:
        return TaskResult(TaskStatus.COMPLETED, {"reward_selected": choice, "relic_selected": choice})
    character = state.get("character_choice")
    if isinstance(character, Mapping):
        nested = character.get("name", character.get("character"))
        character = nested if isinstance(nested, str) else None
    if isinstance(character, (list, tuple)):
        values = [getattr(item, "text", item) for item in character]
        values = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        character = values[0] if len(values) == 1 else None
    if isinstance(character, str) and character.strip():
        return TaskResult(TaskStatus.COMPLETED, {"character_selected": character.strip()})
    if isinstance(character, list) and character and all(isinstance(item, str) and item.strip() for item in character):
        return TaskResult(TaskStatus.COMPLETED, {"character_selected": [item.strip() for item in character]})
    return _waiting("reward_or_character_choice_required")


def select_guild(state: Mapping[str, Any]) -> TaskResult:
    guild = state.get("guild")
    if isinstance(guild, Mapping):
        nested = guild.get("name", guild.get("guild"))
        guild = nested if isinstance(nested, str) else None
    allowed = _configured_guild_names() | {"TW"}
    if isinstance(guild, str):
        guild = guild.strip()
    if guild is None:
        candidates = state.get("guild_candidates")
        if isinstance(candidates, list):
            confirmed = [str(item).strip() for item in candidates if str(item).strip() in allowed]
            unique = set(confirmed)
            if len(unique) == 1:
                guild = next(iter(unique))
            elif unique:
                preferred = [name for name in _configured_preferred_guilds() if name in unique]
                if len(preferred) == 1:
                    guild = preferred[0]
    if not isinstance(guild, str) or guild not in allowed:
        return _waiting("guild_confirmation_required")
    return TaskResult(TaskStatus.COMPLETED, {"guild": guild})


def select_initial_characters(state: Mapping[str, Any]) -> TaskResult:
    selected = state.get("selected_characters")
    candidate_list = state.get("initial_character_candidates")
    if state.get("learning_mode") is True and selected is None:
        candidates = candidate_list if isinstance(candidate_list, list) else []
        names = []
        for item in candidates:
            value = item.get("name", item.get("character", item.get("text"))) if isinstance(item, Mapping) else getattr(item, "text", item)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
        # 初期プールが5人以下なら全員が選択可能という既知の条件を
        # 自動化する。戦闘中の複雑な編成・ショップ判断とは分離する。
        if 0 < len(names) <= 5:
            return TaskResult(TaskStatus.COMPLETED, {
                "selected_characters": names,
                "initial_character_candidate_names": names,
                "initial_character_selection_basis": "all_available_small_pool",
            })
        from .composition_learning import learning_progress, load_feedback
        feedback_path = state.get("composition_feedback_path") or (Path(__file__).resolve().parents[2] / "data/knowledge/composition_feedback.jsonl")
        progress = learning_progress(load_feedback(feedback_path), enemy="initial", stage=str(state.get("stage", "initial")))
        priority, learned_priority = _learned_priority_order(state, "initial", str(state.get("stage", "initial")))
        if priority:
            order = {name: index for index, name in enumerate(priority)}
            ranked = sorted(zip(candidates, names), key=lambda pair: order.get(str(pair[1]).strip(), len(order)))
            candidates = [item for item, _ in ranked]
            names = [name for _, name in ranked]
        return TaskResult(TaskStatus.WAITING, {
            "initial_character_candidates": candidates,
            "initial_character_candidate_names": names,
            "character_priority": {"learned": learned_priority is not None, "priority_characters": priority},
            "learning_status": {"mode": "assisted", "reason": "insufficient_confirmed_choices", **progress},
        }, "initial_character_manual_selection_required")
    # During the proposal phase, use the same acquisition policy as later
    # rewards, but do not perform UI input here. The caller can show the
    # recommendation and feed the manual result back for comparison.
    if (state.get("propose_initial_characters") is True
            and isinstance(candidate_list, list)):
        from .labyrinth_character_acquisition import choose_acquisition
        decision = choose_acquisition("initial_guild", candidate_list, {
            **state,
            "owned_characters": state.get("owned_characters", []),
            "objective": "high_score",
        })
        if decision.get("status") != "completed":
            return _waiting(str(decision.get("reason", "initial_characters_confirmation_required")))
        recommendation = decision["selected"]
        if selected is None:
            return TaskResult(TaskStatus.WAITING, {
                "initial_character_recommendation": recommendation,
                "initial_character_ranked": decision.get("ranked", []),
            }, "initial_character_manual_selection_required")
        selected_names = [str(item).strip() for item in selected] if isinstance(selected, list) else []
        facts = {
            "initial_character_recommendation": recommendation,
            "initial_character_ranked": decision.get("ranked", []),
            "initial_character_selection_deviation": selected_names != recommendation,
        }
        # Preserve the normal validation path below and attach the comparison.
    else:
        facts = {}
    if selected is None:
        # Prefer explicit runtime candidates, then use only text-confirmed
        # guild recommendations. Image-only suggestions remain manual.
        candidates = state.get("initial_character_candidates")
        data: Mapping[str, Any] = {}
        config = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_guild_starting_members.json"
        if candidates is None:
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
                guild = state.get("guild")
                entry = data.get("guilds", {}).get(guild, {}) if isinstance(data, dict) else {}
                candidates = entry.get("recommended_members") if isinstance(entry, dict) else None
            except (OSError, json.JSONDecodeError, AttributeError):
                candidates = None
        if isinstance(candidates, list) and state.get("character_source") == "initial_guild":
            from .labyrinth_character_acquisition import choose_acquisition
            decision = choose_acquisition("initial_guild", candidates, {
                **state,
                "owned_characters": state.get("owned_characters", []),
            })
            if decision.get("status") != "completed":
                return _waiting(str(decision.get("reason", "initial_characters_confirmation_required")))
            selected = decision["selected"]
        elif isinstance(candidates, list):
            extracted = []
            for item in candidates[:5]:
                if isinstance(item, Mapping):
                    value = item.get("name", item.get("character", item.get("text")))
                else:
                    value = getattr(item, "text", item)
                extracted.append(value)
            if extracted and all(isinstance(item, str) and item.strip() for item in extracted):
                selected = [item.strip() for item in extracted]
                # OCR commonly omits the ★6/rank decoration. If the guild
                # config contains exactly one matching canonical name, keep
                # that configured spelling for downstream composition rules.
                try:
                    if not data:
                        data = json.loads(config.read_text(encoding="utf-8"))
                    configured = data.get("guilds", {}).get(state.get("guild"), {}).get("recommended_members", [])
                except (AttributeError, OSError, json.JSONDecodeError):
                    configured = []
                if isinstance(configured, list):
                    canonical: list[str] = []
                    for name in selected:
                        matches = [str(item).strip() for item in configured
                                   if isinstance(item, str) and _normalize_character_name(item) == _normalize_character_name(name)]
                        canonical.append(matches[0] if len(matches) == 1 else name)
                    selected = canonical
    if isinstance(selected, list):
        selected = [name.strip() if isinstance(name, str) else name for name in selected]
    if not isinstance(selected, list) or not 1 <= len(selected) <= 5 or not all(isinstance(name, str) and name for name in selected):
        return _waiting("initial_characters_confirmation_required")
    if len(set(selected)) != len(selected):
        return _waiting("initial_characters_must_be_unique")
    facts["selected_characters"] = list(selected)
    return TaskResult(TaskStatus.COMPLETED, facts)


def user_assist(state: Mapping[str, Any]) -> TaskResult:
    response = state.get("user_input")
    if not isinstance(response, str) or not response.strip():
        return _waiting("user_input_required")
    return TaskResult(TaskStatus.COMPLETED, {"user_input": response.strip()})


def shop_task(state: Mapping[str, Any]) -> TaskResult:
    """ショップ完了確認。購入判断・入力はユーザー側へ委譲する。"""
    if state.get("shop_handled") is True:
        return TaskResult(TaskStatus.COMPLETED, {"shop_handled": True})
    return _waiting("shop_user_confirmation_required")


DETERMINISTIC_TASK_HANDLERS = {
    Task.CHECK_PASSPORTS: check_passports,
    Task.CHECK_CURRENT_SCREEN: check_current_screen,
    Task.LAUNCH_LABYRINTH: launch_labyrinth,
    Task.SELECT_GUILD: select_guild,
    Task.SELECT_INITIAL_CHARACTERS: select_initial_characters,
    Task.INITIAL_SETUP: initial_setup,
    Task.CLOSE_DIALOG: close_dialog,
    Task.NEXT: next_screen,
    Task.CHECK_AREA: check_area,
    Task.BOSS_NAME: check_boss_names,
    Task.SCAN_AREA_MAP: scan_area_map,
    Task.INITIAL_CONTINUE_DECISION: initial_continue_decision,
    Task.PLAN_ROUTE: plan_route,
    Task.MOVE_ROUTE: move_route,
    Task.CONFIRM_MOVE: confirm_move,
    Task.HANDLE_TILE: handle_tile,
    Task.IDENTIFY_ENEMY: identify_enemy,
    Task.PREPARE_BATTLE: prepare_battle,
    Task.START_BATTLE: start_battle,
    Task.WAIT_BATTLE_RESULT: wait_battle_result,
    Task.SELECT_REWARD: select_reward,
    Task.WITHDRAW: withdraw,
    Task.RETURN_LABYRINTH_TOP: return_labyrinth_top,
}

USER_CONFIRMATION_TASK_HANDLERS = {
    Task.USER_ASSIST: user_assist,
    Task.SHOP: shop_task,
}
