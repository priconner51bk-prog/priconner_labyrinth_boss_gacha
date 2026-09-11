"""オーケストレータのタスク分類台帳。"""

from __future__ import annotations

from dataclasses import dataclass

from .labyrinth_orchestrator import DEFAULT_SCRIPT_TASKS, Task
from .deterministic_tasks import USER_CONFIRMATION_TASK_HANDLERS


@dataclass(frozen=True)
class TaskDefinition:
    task: Task
    executor: str  # script / user
    implemented: bool
    description: str


_USER_TASKS = {Task.USER_ASSIST}
_DESCRIPTIONS = {
    Task.CHECK_CURRENT_SCREEN: "現在画面と新規/再開を判定",
    Task.CLOSE_DIALOG: "汎用ダイアログを閉じる",
    Task.NEXT: "汎用の次へを押す",
    Task.BOSS_NAME: "左右ボスを順序固定でOCR",
    Task.EVALUATE_BOSS_TARGET: "対象ボス組合せを照合",
    Task.SHOP: "ショップ購入をユーザー確認で実行",
    Task.WITHDRAW: "対象外試行を撤退",
}


def build_task_catalog() -> tuple[TaskDefinition, ...]:
    """全Taskを漏れなく分類した不変カタログを返す。"""
    definitions = []
    for task in Task:
        if task in DEFAULT_SCRIPT_TASKS:
            executor = "script"
        elif task in _USER_TASKS:
            executor = "user"
        else:
            executor = "user"
        implemented = task in DEFAULT_SCRIPT_TASKS or task in USER_CONFIRMATION_TASK_HANDLERS
        definitions.append(TaskDefinition(task, executor, implemented, _DESCRIPTIONS.get(task, task.value)))
    return tuple(definitions)
