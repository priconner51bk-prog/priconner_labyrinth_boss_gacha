"""ラビリンス画面以外への誤操作を防ぐ fail-closed ガード。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

LABYRINTH_BOTTOM_LABELS = frozenset({"キャラ", "迷宮遺物", "HP"})
NON_LABYRINTH_BOTTOM_LABELS = frozenset({"クエスト", "マイページ", "キャラ", "強化", "ストーリー"})

# 画面認識結果から、入力を送る前の復帰先だけを決める対応表。
# ここではタップを行わず、未知の画面は必ず None を返す。
_RESUME_TASKS = {
    "home": "launch_labyrinth",
    "title": "launch_labyrinth",
    "notice": "task_close_dialog",
    "quest_menu": "launch_labyrinth",
    "labyrinth_top": "launch_labyrinth",
    "guild_select": "select_guild",
    "guild_confirm": "select_guild",
    "bonus": "task_close_dialog",
    "initial_char": "task_initial_setup",
    "boss_map": "task_boss_name",
    "withdraw_confirm": "withdraw",
    "item_reward": "task_close_dialog",
}


def classify_resume_screen(screen_id: object, *, challenge_active: object = False) -> dict[str, str] | None:
    """Return a safe resume decision for a recognized Labyrinth screen.

    ``challenge_active`` distinguishes a fresh departure from a resumed run.
    Unknown values or screens return ``None`` so the caller can fail closed.
    """
    if isinstance(screen_id, str):
        screen_id = screen_id.strip()
    if not isinstance(screen_id, str) or screen_id not in _RESUME_TASKS:
        return None
    if not isinstance(challenge_active, bool):
        return None
    if ((screen_id == "labyrinth_top" or screen_id == "initial_char")
            and challenge_active):
        resume_task = "task_initial_setup"
        entry_mode = "resume"
    else:
        resume_task = _RESUME_TASKS[screen_id]
        entry_mode = "resume" if challenge_active else "new"
    return {"screen_id": screen_id, "entry_mode": entry_mode, "resume_task": resume_task}


def bottom_navigation_is_labyrinth(labels: object) -> bool:
    """下部ナビゲーションの軽量な一次判定。

    ``labels`` は下部ROIから得たOCRラベル集合/リストを想定する。
    クエスト等のホーム下部ナビが見えた場合は即座にFalseとし、
    ラビリンス固有の「迷宮遺物」等が確認できない場合も安全側でFalseにする。
    """
    if isinstance(labels, str):
        observed = {labels}
    elif isinstance(labels, (list, tuple, set, frozenset)):
        observed = {str(label).strip() for label in labels if str(label).strip()}
    else:
        return False
    if observed & {"クエスト", "マイページ", "強化", "ストーリー"}:
        return False
    return bool(observed & LABYRINTH_BOTTOM_LABELS)


@dataclass
class LabyrinthScreenGuard:
    """認識器が返す画面IDをタスク別の許可リストと照合する。"""

    allowed_by_task: Mapping[str, set[str]] = field(default_factory=dict)

    def __call__(self, task: object, state: Mapping[str, object]) -> bool:
        screen_id = state.get("screen_id")
        if not isinstance(screen_id, str) or not screen_id.strip():
            return False
        task_id = getattr(task, "value", str(task))
        allowed = self.allowed_by_task.get(task_id)
        return bool(allowed and screen_id in allowed)
