"""黎明界ラビリンスのイベント選択に関する判断支援。"""

from __future__ import annotations

from typing import Any, Mapping


EVENT_NAMES = {
    "ギルド管理協会": "guild_recruit", "仲間をお探し": "guild_recruit",
    "魔物たちが集まる闘技場": "arena", "闘技場": "arena",
    "ダンジョンで迷った": "lost_dungeon", "イベント会場に魔物": "event_battle",
    "不思議な石板": "stone_tablet", "箱の中から声": "box_voice",
    "じゃんけん": "janken", "釣りスポット": "fishing", "ピクニック": "picnic",
    "スロットマシン": "slot",
}


def normalize_event_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = "".join(value.split())
    for label, canonical in EVENT_NAMES.items():
        if label in compact:
            return canonical
    return None


def choose_event_option(event_name: Any, options: list[Mapping[str, Any]], state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """既知イベントの候補を返す。未知・状態不足なら入力せず確認待ちにする。"""
    state = state or {}
    canonical = normalize_event_name(event_name)
    if canonical is None or not options:
        return {"status": "waiting", "reason": "event_options_or_name_required"}
    if canonical == "janken":
        return {"status": "completed", "selection_allowed": True, "index": 1, "basis": "random_choice"}
    if canonical == "arena":
        extreme = state.get("prefer_extreme") is True and state.get("battle_ready") is True
        return {"status": "completed", "selection_allowed": True, "index": 2 if extreme else 1,
                "basis": "extreme_reward" if extreme else "opening_safety"}
    return {"status": "waiting", "reason": f"event_choice_requires_context:{canonical}"}
