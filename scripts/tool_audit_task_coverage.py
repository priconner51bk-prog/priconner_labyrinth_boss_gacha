"""ラビリンス全タスクの実行経路を監査するツール。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decision.deterministic_tasks import (  # noqa: E402
    DETERMINISTIC_TASK_HANDLERS,
    USER_CONFIRMATION_TASK_HANDLERS,
)
from decision.labyrinth_orchestrator import DEFAULT_SCRIPT_TASKS, Task  # noqa: E402
from decision.task_catalog import build_task_catalog  # noqa: E402

LIVE_SCRIPTS = {
    Task.CHECK_CURRENT_SCREEN: "task_check_current_screen_live.py",
    # ボス名確認は出発・撤退と同じ複合ワークフロー内で実行される。
    Task.BOSS_NAME: "task_boss_gacha_live.py",
    Task.SCAN_AREA_MAP: "task_scan_map_live.py",
    Task.PLAN_ROUTE: "task_plan_route_live.py",
    Task.MOVE_ROUTE: "task_move_map_node_live.py",
    Task.CLOSE_DIALOG: "task_close_live.py",
    Task.NEXT: "task_next_live.py",
    Task.SELECT_INITIAL_CHARACTERS: "task_select_initial_characters_live.py",
    Task.INITIAL_SETUP: "task_initial_setup_live.py",
    Task.START_BATTLE: "task_run_normal_battle_live.py",
    Task.WAIT_BATTLE_RESULT: "task_wait_battle_result_live.py",
    Task.WITHDRAW: "task_withdraw_live.py",
    Task.SHOP: "task_shop_live.py",
}


def audit() -> dict[str, object]:
    catalog = build_task_catalog()
    executor_counts: dict[str, int] = {}
    for entry in catalog:
        executor_counts[entry.executor] = executor_counts.get(entry.executor, 0) + 1
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    live_missing: list[str] = []
    for entry in catalog:
        task = entry.task
        if task in DETERMINISTIC_TASK_HANDLERS:
            handler = "deterministic"
        elif task in USER_CONFIRMATION_TASK_HANDLERS:
            handler = "user_confirmation"
        elif task is Task.EVALUATE_BOSS_TARGET:
            handler = "orchestrator_internal"
        else:
            handler = "missing"
            missing.append(task.value)
        rows.append({
            "task": task.value,
            "executor": entry.executor,
            "implemented": handler != "missing",
            "handler": handler,
            "live_script": LIVE_SCRIPTS.get(task),
        })
        script_name = LIVE_SCRIPTS.get(task)
        if script_name and not (ROOT / "scripts" / script_name).exists():
            live_missing.append(task.value)
    return {
        "task_count": len(catalog),
        "implemented_count": len(catalog) - len(missing),
        "executor_counts": executor_counts,
        "script_ratio": round(executor_counts.get("script", 0) / len(catalog), 4) if catalog else 0.0,
        "user_confirmation_tasks": [entry.task.value for entry in catalog if entry.executor == "user"],
        "missing": missing,
        "live_missing": live_missing,
        "mandatory_script_tasks": sorted(task.value for task in DEFAULT_SCRIPT_TASKS if task in {Task.LAUNCH_LABYRINTH, Task.SELECT_GUILD}),
        "tasks": rows,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
