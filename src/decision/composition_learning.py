"""ユーザー補助で蓄積した編成結果から安全に採用候補を判定する。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
from typing import Any, Iterable, Mapping


def load_feedback(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    file = Path(path)
    if not file.exists():
        return records
    for line in file.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def learned_composition(
    records: Iterable[dict[str, Any]], *, enemy: str, stage: str,
    min_victories: int = 3, min_win_rate: float = 0.8,
) -> dict[str, Any] | None:
    """条件に一致し、十分な勝率を持つ編成だけを返す。

    複数編成は一つの候補キーとして扱い、順序も保持する。同率の場合は
    勝利数、次に試行数、辞書順で決定する。データ不足は必ずNone。
    """
    if min_victories < 1 or not 0.0 <= min_win_rate <= 1.0:
        raise ValueError("invalid_learning_threshold")
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"victories": 0, "defeats": 0, "indices": None})
    for item in records:
        if str(item.get("enemy", "")) != str(enemy) or str(item.get("stage", "")) != str(stage):
            continue
        raw = item.get("selected_indices")
        if not isinstance(raw, list) or not raw:
            continue
        try:
            groups = [[int(v) for v in group] for group in raw if isinstance(group, list)]
        except (TypeError, ValueError):
            continue
        if not groups or any(len(group) != len(set(group)) for group in groups):
            continue
        key = json.dumps(groups, ensure_ascii=False, separators=(",", ":"))
        entry = stats[key]
        entry["indices"] = groups
        if item.get("outcome") == "victory":
            entry["victories"] += 1
        elif item.get("outcome") == "defeat":
            entry["defeats"] += 1
    eligible = []
    for entry in stats.values():
        trials = entry["victories"] + entry["defeats"]
        rate = entry["victories"] / trials if trials else 0.0
        if entry["victories"] >= min_victories and rate >= min_win_rate:
            eligible.append((entry["victories"], trials, json.dumps(entry["indices"], ensure_ascii=False), entry, rate))
    if not eligible:
        return None
    _, trials, _, best, rate = max(eligible, key=lambda row: (row[0], row[1], row[2]))
    return {"selected_indices": best["indices"], "victories": best["victories"], "defeats": best["defeats"], "trials": trials, "win_rate": rate, "status": "learned"}


def learning_progress(records: Iterable[dict[str, Any]], *, enemy: str | None = None, stage: str | None = None,
                      min_victories: int = 3, min_win_rate: float = 0.8) -> dict[str, Any]:
    """表示用の学習進捗。候補の採用可否は別途 ``learned_composition`` が決める。"""
    scoped = [item for item in records
              if (enemy is None or str(item.get("enemy", "")) == str(enemy))
              and (stage is None or str(item.get("stage", "")) == str(stage))]
    victories = sum(item.get("outcome") == "victory" for item in scoped)
    defeats = sum(item.get("outcome") == "defeat" for item in scoped)
    trials = victories + defeats
    rate = victories / trials if trials else 0.0
    return {"trials": trials, "victories": victories, "defeats": defeats,
            "win_rate": rate, "minimum_victories": min_victories,
            "minimum_win_rate": min_win_rate,
            "learned": victories >= min_victories and rate >= min_win_rate}


def automation_gate(records: Iterable[dict[str, Any]], required: Iterable[tuple[str, str]], *,
                    min_victories: int = 3, min_win_rate: float = 0.8,
                    approvals: Iterable[Mapping[str, Any]] | None = None,
                    context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """必要な全戦闘条件が学習済みかを判定する安全ゲート。

    ``approvals`` を渡した場合は、人手承認と非空の承認対象コンテキストも
    必須にする。既存の学習進捗表示との互換性のため、未指定時は従来の
    ``learned`` 判定だけを返す。
    """
    entries = list(records)
    approval_entries = list(approvals) if approvals is not None else None
    runtime_context = dict(context or {})
    checks = []
    for enemy, stage in required:
        result = learned_composition(entries, enemy=enemy, stage=stage,
                                      min_victories=min_victories, min_win_rate=min_win_rate)
        item = {"enemy": enemy, "stage": stage, "learned": result is not None, "composition": result}
        if approval_entries is not None:
            matching = []
            for approval in approval_entries:
                if (str(approval.get("enemy", "")) == str(enemy)
                        and str(approval.get("stage", "")) == str(stage)
                        and approval.get("approved") is True):
                    if result is not None and approval.get("selected_indices") == result["selected_indices"]:
                        approved_context = approval.get("context", {})
                        if (runtime_context and isinstance(approved_context, Mapping)
                                and bool(approved_context) and all(
                                approved_context.get(key) == value for key, value in runtime_context.items())):
                            matching.append(approval)
            item["human_approved"] = bool(matching)
            item["approval"] = matching[-1] if matching else None
        checks.append(item)
    enabled = bool(checks) and all(item["learned"] for item in checks)
    if approval_entries is not None:
        enabled = enabled and all(item.get("human_approved", False) for item in checks)
    return {"enabled": enabled, "checks": checks,
            "minimum_victories": min_victories, "minimum_win_rate": min_win_rate}
