"""シーン別のキャラ優先順位をユーザーのピックと勝敗から学習する。

学習データが基準を満たすまではユーザーがキャラピックを行い、その結果を
記録する。ここでキャラクター単位に「どのキャラがそのシーン（敵・ステージ）で
有効だったか」を集計し、基準を超えたキャラだけを自動化の優先候補へ昇格させる。
編成単位（composition_learning）と異なり、編成全体ではなく個別キャラの寄与を
追うのが目的で、初期キャラ選択の「雑なピック」でエリアボスに勝てない問題への
対策として、シーンごとに強キャラを絞り込む。
"""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_MIN_TRIALS = 3
DEFAULT_MIN_WIN_RATE = 0.6


def build_enemy_composition_id(
    *,
    enemy: str,
    stage: str,
    composition: Any = None,
    difficulty: str | None = None,
) -> str:
    """敵名だけでなく編成・難易度を含む再現可能な学習キーを作る。"""
    if isinstance(composition, str):
        normalized = composition.strip()
    else:
        normalized = json.dumps(composition or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = json.dumps({"enemy": enemy, "stage": stage, "difficulty": difficulty or "", "composition": normalized}, ensure_ascii=False, sort_keys=True)
    return "enemycomp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_priority_records(path: str | Path) -> list[dict[str, Any]]:
    """JSONLのキャラ優先順位学習記録を読み込む。壊れた行は無視する。"""
    records: list[dict[str, Any]] = []
    file = Path(path)
    if not file.exists():
        return records
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _record_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("selected_character_names", "candidate_names", "selected_characters"):
        value = item.get(key)
        if isinstance(value, (list, tuple)):
            for entry in value:
                text = str(entry).strip() if not isinstance(entry, Mapping) else str(entry.get("name", "")).strip()
                if text and text not in names:
                    names.append(text)
        elif isinstance(value, str) and value.strip():
            names.append(value.strip())
    if names:
        return names
    for key in ("selected_character_name", "selected_character"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _record_character_ids(item: dict[str, Any]) -> list[str]:
    values = item.get("selected_character_ids") or item.get("character_ids")
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def learn_character_priorities(
    records: Iterable[dict[str, Any]],
    *,
    enemy: str,
    stage: str,
    enemy_composition_id: str | None = None,
    min_trials: int = DEFAULT_MIN_TRIALS,
    min_win_rate: float = DEFAULT_MIN_WIN_RATE,
) -> dict[str, Any] | None:
    """シーン（敵・ステージ）ごとにキャラ別勝率を集計し、基準を満たすキャラだけ返す。

    基準を満たすキャラが一つもいない場合は ``None`` を返し、自動化へは昇格しない。
    """
    if min_trials < 1 or not 0.0 <= min_win_rate <= 1.0:
        raise ValueError("invalid_learning_threshold")
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"victories": 0, "defeats": 0})
    for item in records:
        # 少人数プールの全選択は優先順位の意思決定ではないため、
        # ピックアップ回数・加点の集計対象から除外する。
        if item.get("selection_reason") == "pool_under_five_all" or item.get("priority_credit") is False:
            continue
        if enemy_composition_id is not None:
            if str(item.get("enemy_composition_id", "")) != str(enemy_composition_id):
                continue
        elif str(item.get("enemy", "")) != str(enemy) or str(item.get("stage", "")) != str(stage):
            continue
        names = _record_character_ids(item) or _record_names(item)
        if not names:
            continue
        outcome = item.get("outcome")
        for name in names:
            bucket = stats[name]
            if outcome == "victory":
                bucket["victories"] += 1
            elif outcome == "defeat":
                bucket["defeats"] += 1
    characters: list[dict[str, Any]] = []
    for name, bucket in stats.items():
        trials = bucket["victories"] + bucket["defeats"]
        if trials == 0:
            continue
        rate = bucket["victories"] / trials
        if bucket["victories"] >= min_trials and rate >= min_win_rate:
            characters.append({
                "name": name,
                "trials": trials,
                "victories": bucket["victories"],
                "defeats": bucket["defeats"],
                "win_rate": rate,
            })
    if not characters:
        return None
    characters.sort(key=lambda row: (-row["win_rate"], -row["victories"], row["name"]))
    return {
        "enemy": enemy,
        "stage": stage,
        "priority_characters": [row["name"] for row in characters],
        "characters": characters,
        "status": "learned",
    }


def priority_learning_progress(
    records: Iterable[dict[str, Any]],
    *,
    enemy: str | None = None,
    stage: str | None = None,
    enemy_composition_id: str | None = None,
    min_trials: int = DEFAULT_MIN_TRIALS,
    min_win_rate: float = DEFAULT_MIN_WIN_RATE,
) -> dict[str, Any]:
    """シーン別のキャラ優先順位学習進捗を表示用集計。"""
    entries = list(records)
    if enemy_composition_id is not None:
        entries = [item for item in entries if str(item.get("enemy_composition_id", "")) == str(enemy_composition_id)]
    elif enemy is not None or stage is not None:
        entries = [
            item for item in entries
            if (enemy is None or str(item.get("enemy", "")) == str(enemy))
            and (stage is None or str(item.get("stage", "")) == str(stage))
        ]
    names = sorted({name for item in entries for name in (_record_character_ids(item) or _record_names(item))})
    victories = sum(item.get("outcome") == "victory" for item in entries)
    defeats = sum(item.get("outcome") == "defeat" for item in entries)
    trials = victories + defeats
    rate = victories / trials if trials else 0.0
    return {
        "trials": trials,
        "victories": victories,
        "defeats": defeats,
        "win_rate": rate,
        "character_count": len(names),
        "characters": names,
        "minimum_trials": min_trials,
        "minimum_win_rate": min_win_rate,
        "learned": bool(names) and victories >= min_trials and rate >= min_win_rate,
    }


def merge_into_boss_patterns(
    patterns: dict[str, Any],
    learned: dict[str, Any],
) -> dict[str, Any]:
    """学習済みキャラをボスパターンの ``priority_characters`` へマージする。

    ``learned["characters"]`` の並びを優先度として採用し、既存の優先キャラを
    先頭に保つ。学習済みキャラが既存に無い場合だけ追記するため、人手で固定した
    優先キャラを上書きしない。
    """
    characters = learned.get("characters")
    if not isinstance(characters, list) or not characters:
        return patterns
    learned_names = [str(row.get("name", "")).strip() for row in characters if isinstance(row, Mapping)]
    learned_names = [name for name in learned_names if name]
    if not learned_names:
        return patterns
    result: dict[str, Any] = dict(patterns)
    existing = result.get("priority_characters")
    existing_names = [str(name).strip() for name in existing if str(name).strip()] if isinstance(existing, (list, tuple)) else []
    merged = list(existing_names)
    for name in learned_names:
        if name not in merged:
            merged.append(name)
    result["priority_characters"] = merged
    result["learned_priority_source"] = "character_priority_learning"
    result["learned_priority_characters"] = learned_names
    return result
