"""ラビリンス自動操縦の状態駆動オーケストレータ。

このモジュールはゲームへ入力しない。画面認識・ADBなどの実行器は
``TaskHandler`` として注入し、実装済みの定型処理を優先して使う。
未実装又は意味判断が必要な処理はユーザー確認ハンドラへ渡し、確認済みの
シーンを段階的にスクリプトへ置換できる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from boss_gacha import BossGachaController, BossGachaPolicy
from .repair_loop import FailurePacket, RepairLoop, failure_signature, validate_repair_proposal


class Task(str, Enum):
    CHECK_CURRENT_SCREEN = "task_check_current_screen"
    USER_ASSIST = "task_user_assist"
    CLOSE_DIALOG = "task_close_dialog"
    NEXT = "task_next"
    INITIAL_SETUP = "task_initial_setup"
    CHECK_PASSPORTS = "check_passports"
    LAUNCH_LABYRINTH = "launch_labyrinth"
    SELECT_GUILD = "select_guild"
    CHECK_AREA = "check_area"
    BOSS_NAME = "task_boss_name"
    # Backward-compatible Python name used by existing callers.
    CHECK_AREA_BOSS = "task_boss_name"
    EVALUATE_BOSS_TARGET = "task_evaluate_boss_target"
    SCAN_AREA_MAP = "scan_area_map"
    INITIAL_CONTINUE_DECISION = "initial_continue_decision"
    WITHDRAW = "withdraw"
    RETURN_LABYRINTH_TOP = "return_labyrinth_top"
    SELECT_INITIAL_CHARACTERS = "select_initial_characters"
    PLAN_ROUTE = "plan_route"
    MOVE_ROUTE = "move_route"
    CONFIRM_MOVE = "confirm_move"
    HANDLE_TILE = "handle_tile"
    SHOP = "task_shop"
    IDENTIFY_ENEMY = "identify_enemy"
    PREPARE_BATTLE = "prepare_battle"
    START_BATTLE = "start_battle"
    WAIT_BATTLE_RESULT = "wait_battle_result"
    SELECT_REWARD = "select_reward"


class TaskStatus(str, Enum):
    COMPLETED = "completed"
    WAITING = "waiting"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class TaskResult:
    status: TaskStatus
    facts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    # Capture-derived coordinates are stored as candidates only.  A separate
    # review step must approve them before an input adapter may use them.
    coordinate_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskRun:
    task: Task
    executor: str  # script / user / none
    result: TaskResult
    next_task: Task | None


TaskHandler = Callable[[Mapping[str, Any]], TaskResult]
ScreenGuard = Callable[[Task, Mapping[str, Any]], bool]


# A task becomes a script task simply by registering it in ``script_handlers``.
# This is the migration switch from user confirmation to deterministic automation.
DEFAULT_SCRIPT_TASKS = frozenset({
    Task.CHECK_CURRENT_SCREEN,
    Task.CHECK_PASSPORTS,
    Task.LAUNCH_LABYRINTH,
    Task.SELECT_GUILD,
    Task.WITHDRAW,
    Task.RETURN_LABYRINTH_TOP,
    Task.INITIAL_SETUP,
    Task.SELECT_INITIAL_CHARACTERS,
    Task.BOSS_NAME,
    Task.CLOSE_DIALOG,
    Task.NEXT,
    Task.MOVE_ROUTE,
    Task.CONFIRM_MOVE,
    Task.CHECK_AREA,
    Task.SCAN_AREA_MAP,
    Task.INITIAL_CONTINUE_DECISION,
    Task.PLAN_ROUTE,
    Task.HANDLE_TILE,
    Task.IDENTIFY_ENEMY,
    Task.PREPARE_BATTLE,
    Task.START_BATTLE,
    Task.WAIT_BATTLE_RESULT,
    Task.SELECT_REWARD,
    Task.EVALUATE_BOSS_TARGET,
})
MANDATORY_SCRIPT_TASKS = frozenset({
    Task.LAUNCH_LABYRINTH,
    Task.SELECT_GUILD,
})

DEFAULT_TARGET_BOSSES = {
    "3": "ベノムサラマンドラ",
    "5": "ゴブリンロード",
}


class LabyrinthOrchestrator:
    """Execute one small task at a time and retain the resulting facts.

    The caller may call :meth:`step` from a polling loop.  A ``WAITING``
    result is intentionally non-busy: it leaves the current task unchanged so
    the caller can wait for its configured poll interval before trying again.
    """

    def __init__(
        self,
        state: Mapping[str, Any] | None = None,
        *,
        script_handlers: Mapping[Task, TaskHandler] | None = None,
        user_handler: TaskHandler | None = None,
        ai_handler: TaskHandler | None = None,
        target_bosses: Mapping[str | int, str] | None = None,
        target_policy_path: str | Path | None = None,
        screen_guard: ScreenGuard | None = None,
        enforce_script_tasks: bool = True,
        max_boss_gacha_attempts: int = 10,
        resume_from_current_screen: bool = False,
    ) -> None:
        self.state: dict[str, Any] = dict(state or {})
        self.state.setdefault("run_id", f"run-{uuid4().hex}")
        self.script_handlers = dict(script_handlers or {})
        self.user_handler = user_handler
        self.ai_handler = ai_handler
        self.screen_guard = screen_guard
        self.enforce_script_tasks = enforce_script_tasks
        if max_boss_gacha_attempts < 1:
            raise ValueError("max_boss_gacha_attempts must be positive")
        self.max_boss_gacha_attempts = max_boss_gacha_attempts
        self.state.setdefault("boss_gacha_attempts", 0)
        policy_targets: Mapping[str | int, str] = {}
        if target_policy_path is None:
            default_policy = Path(__file__).resolve().parents[2] / "configs" / "labyrinth_target_policy.json"
            target_policy_path = default_policy if default_policy.exists() else None
        if target_policy_path is not None:
            policy_file = Path(target_policy_path)
            if policy_file.exists():
                policy_data = json.loads(policy_file.read_text(encoding="utf-8"))
                if isinstance(policy_data, dict) and isinstance(policy_data.get("target_bosses"), Mapping):
                    policy_targets = policy_data["target_bosses"]
        configured_targets = target_bosses or self.state.get("target_bosses") or policy_targets or DEFAULT_TARGET_BOSSES
        self.target_bosses = {str(area): str(name) for area, name in configured_targets.items()}
        self.state["target_bosses"] = dict(self.target_bosses)
        self.state.setdefault("retry_until_target", True)
        # 初期キャラ・戦闘編成は、勝敗データが十分に蓄積するまで
        # ユーザー補助を既定とする。明示的に学習済みへ切り替える。
        if "learning_mode" not in self.state:
            learning_mode = True
            settings_path = Path(__file__).resolve().parents[2] / "configs" / "runtime_settings.json"
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                learning_mode = settings.get("labyrinth", {}).get("learning", {}).get("mode", "assisted") != "auto"
                self.state.setdefault("learning_min_victories", int(settings.get("labyrinth", {}).get("learning", {}).get("min_confirmed_victories", 3)))
                self.state.setdefault("learning_min_win_rate", float(settings.get("labyrinth", {}).get("learning", {}).get("min_win_rate", 0.8)))
                self.state.setdefault("reference_run_required", bool(settings.get("labyrinth", {}).get("learning", {}).get("reference_run_required", True)))
                self.state.setdefault("learning_scopes", list(settings.get("labyrinth", {}).get("learning", {}).get("scopes", [])))
                automation = settings.get("labyrinth", {}).get("automation", {})
                if isinstance(automation, Mapping):
                    for key in ("auto_continue_decision", "auto_plan_route", "auto_select_event",
                                "auto_select_reward", "auto_select_ex_equipment"):
                        if key in automation:
                            self.state.setdefault(key, bool(automation[key]))
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            self.state["learning_mode"] = learning_mode
        # 旧形式の保存状態にも、非高難度処理の自動化方針を適用する。
        # 明示的にFalseへ設定された値は上書きしない。
        self.state.setdefault("auto_continue_decision", True)
        self.state.setdefault("auto_plan_route", True)
        self.state.setdefault("auto_select_event", True)
        self.state.setdefault("auto_select_reward", True)
        self.state.setdefault("auto_select_ex_equipment", True)
        self.state.setdefault("auto_select_shop", False)
        self.boss_gacha = BossGachaController(
            BossGachaPolicy(self.target_bosses, max_boss_gacha_attempts),
            attempts=int(self.state.get("boss_gacha_attempts", 0)),
        )
        current = self.state.get("current_task")
        if resume_from_current_screen:
            current = Task.CHECK_CURRENT_SCREEN.value
        if current == "check_area_boss":
            current = Task.BOSS_NAME.value
        self.current_task = Task(current) if current else Task.CHECK_PASSPORTS
        self.state["current_task"] = self.current_task.value
        self.state.setdefault("history", [])
        self.state.setdefault("task_execution_counts", {})
        self.state.setdefault("step_index", 0)
        self.state.setdefault("failure_packets", [])
        self.state.setdefault("failure_signatures", {})
        self.state.setdefault("user_locked_instructions", [])
        self.state.setdefault("ai_repair_tasks", [])
        # 旧保存状態の ``ai_first_tasks`` は互換のため保持するが、実行権限
        # には使わない。AIは明示された ``ai_repair_tasks`` の修復境界だけで
        # 呼び出され、定型タスクの初回実行を奪わない。
        self.state.setdefault("ai_first_tasks", [])
        self.state.setdefault("coordinate_candidates", [])
        self._stopped = bool(self.state.get("stop_reason"))
        self._paused = bool(self.state.get("paused", False))

    def start(self) -> None:
        """オーケストレータを開始／一時停止から再開する。"""
        if self._stopped:
            raise RuntimeError("停止済みオーケストレータは再開できません")
        self._paused = False
        self.state["paused"] = False

    def reset_for_new_run(self) -> None:
        """停止済み状態を明示的に破棄し、新規実行の先頭へ戻す。"""
        self._stopped = False
        self._paused = False
        self.state.pop("stop_reason", None)
        self.state["paused"] = False
        self.state["current_task"] = Task.CHECK_PASSPORTS.value
        self.current_task = Task.CHECK_PASSPORTS
        self.state["boss_gacha_attempts"] = 0
        self.boss_gacha.attempts = 0
        self.state["consecutive_defeats"] = 0

    def pause(self) -> None:
        """安全に一時停止する。現在タスクの状態は保持する。"""
        if not self._stopped:
            self._paused = True
            self.state["paused"] = True

    def emergency_stop(self, reason: str = "emergency_stop") -> None:
        """緊急停止。以後のタスク実行と入力を禁止する。"""
        self._paused = False
        self.state["paused"] = False
        self.state["stop_reason"] = reason
        self.state["current_task"] = None
        self._stopped = True

    def status(self) -> dict[str, Any]:
        """制御ウィンドウ向けの軽量な状況表示。"""
        result = {
            "running": not self._paused and not self._stopped,
            "paused": self._paused,
            "stopped": self._stopped,
            "current_task": self.state.get("current_task"),
            "stop_reason": self.state.get("stop_reason"),
            "passports": self.state.get("passports"),
            "boss_gacha_attempts": self.state.get("boss_gacha_attempts", 0),
            "learning_mode": self.state.get("learning_mode", True),
            "forbidden_controls": ["帰還する", "終了する"],
        }
        # UIに毎回のユーザー補助候補と学習度合いを表示する。
        for key in ("initial_character_candidate_names", "composition_candidates", "learning_status"):
            if key in self.state:
                result[key] = self.state[key]
        return result

    def add_user_locked_instruction(self, instruction: Mapping[str, Any]) -> None:
        """Persist a human constraint for every later repair/decision boundary."""
        if instruction.get("type") != "USER_LOCKED" or instruction.get("active") is not True:
            raise ValueError("user locked instruction must be active USER_LOCKED")
        item = dict(instruction)
        item.setdefault("id", str(item.get("constraint", "user_constraint")))
        self.state.setdefault("user_locked_instructions", []).append(item)

    def validate_ai_proposal(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        """Mechanically reject an AI proposal that omits a locked constraint."""
        constraints = self.state.get("user_locked_instructions", [])
        return validate_repair_proposal(proposal, constraints if isinstance(constraints, list) else [])

    def build_repair_loop(
        self,
        *,
        execute: Callable[[Mapping[str, Any] | None], Any],
        repair: Callable[[FailurePacket], Mapping[str, Any]],
        replay: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        apply_patch: Callable[[Mapping[str, Any]], None] | None = None,
        max_attempts: int = 3,
    ) -> RepairLoop:
        """Create the sole bounded repair loop with persisted user constraints."""
        constraints = self.state.get("user_locked_instructions", [])
        return RepairLoop(
            execute=execute,
            repair=repair,
            replay=replay,
            apply_patch=apply_patch,
            max_attempts=max_attempts,
            user_constraints=list(constraints) if isinstance(constraints, list) else [],
            history=self.state.setdefault("repair_history", []),
        )

    def step(self) -> TaskRun:
        """Run at most one task; game input is delegated, never performed here."""
        if self._paused:
            result = TaskResult(TaskStatus.WAITING, reason="paused")
            return TaskRun(self.current_task, "none", result, self.current_task)
        if self._stopped:
            result = TaskResult(TaskStatus.STOPPED, reason=str(self.state["stop_reason"]))
            return TaskRun(self.current_task, "none", result, None)
        if self._passports_depleted():
            return self._stop("passports_depleted")
        if self._consecutive_defeats_exceeded():
            return self._stop("consecutive_defeats_limit")

        task = self.current_task
        step_index = int(self.state.get("step_index", 0)) + 1
        self.state["step_index"] = step_index
        before_state = deepcopy(self.state)
        step_id = f"{self.state['run_id']}:step-{step_index}"
        attempt_id = f"{step_id}:attempt-{int(self.state.get('task_execution_counts', {}).get(task.value, 0)) + 1}"
        if self.screen_guard is not None:
            try:
                is_safe = bool(self.screen_guard(task, dict(self.state)))
            except Exception as exc:
                return self._stop(f"screen_guard_error:{type(exc).__name__}")
            if not is_safe:
                return self._stop(f"unexpected_screen_before_task:{task.value}")
        handler, executor = self._handler_for(task)
        if handler is None and self.enforce_script_tasks and task in MANDATORY_SCRIPT_TASKS:
            return self._stop(f"script_handler_missing:{task.value}")
        if handler is None and task is Task.EVALUATE_BOSS_TARGET:
            result = self._evaluate_boss_target()
            executor = "script"
            handler = True  # type: ignore[assignment]
        elif handler is None:
            result = TaskResult(TaskStatus.WAITING, reason="handler_not_configured")
        else:
            try:
                result = handler(dict(self.state))
            except Exception as exc:
                return self._stop(f"task_execution_error:{task.value}:{type(exc).__name__}")
        if not isinstance(result, TaskResult):
            raise TypeError("task handler must return TaskResult")

        if task is Task.CHECK_CURRENT_SCREEN:
            screen_id = result.facts.get("screen_id")
            entry_mode = result.facts.get("entry_mode")
            resume_task = result.facts.get("resume_task")
            try:
                valid_resume = Task(resume_task) if isinstance(resume_task, str) else None
            except ValueError:
                valid_resume = None
            if not isinstance(screen_id, str) or not screen_id.strip() or entry_mode not in {"new", "resume"} or valid_resume in {
                None,
                Task.CHECK_CURRENT_SCREEN,
            }:
                result = TaskResult(
                    TaskStatus.STOPPED,
                    facts=result.facts,
                    reason="safety_stop:current_screen_unrecognized",
                    coordinate_candidates=result.coordinate_candidates,
                )
            else:
                # Keep the explicit branch decision available to the next handler.
                result.facts.setdefault("challenge_entry_confirmed", True)

        if result.status is TaskStatus.FAILED or self._is_unexpected_screen(result):
            detail = result.reason or "unexpected_screen"
            result = TaskResult(
                TaskStatus.STOPPED,
                facts=result.facts,
                reason=f"safety_stop:{detail}",
                coordinate_candidates=result.coordinate_candidates,
            )

        self._apply_result(task, executor, result)
        next_task = self._next_task(task, result) if result.status is TaskStatus.COMPLETED else task
        if result.status is TaskStatus.STOPPED:
            next_task = None
            self._stopped = True
            self.state["stop_reason"] = result.reason
            self.state["current_task"] = None
        self._record_step(
            task=task,
            step_id=step_id,
            attempt_id=attempt_id,
            before_state=before_state,
            executor=executor,
            result=result,
        )
        if next_task is not None:
            self.current_task = next_task
            self.state["current_task"] = next_task.value
        return TaskRun(task, executor, result, next_task)

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-serializable state suitable for durable local storage."""
        return dict(self.state)

    def run_boss_gacha_live(self, runner: Any) -> dict[str, Any]:
        """注入された実機ランナーをオーケストレータ配下で実行する。

        ADBやOCRは引き続きランナーへ注入し、オーケストレータは結果と次の
        タスクだけを状態へ反映する。停止済み・一時停止中は入力を開始しない。
        """
        if self._stopped:
            return {"status": "safety_stop", "reason": "orchestrator_stopped"}
        if self._paused:
            return {"status": "safety_stop", "reason": "orchestrator_paused"}
        run = getattr(runner, "run", None)
        if not callable(run):
            raise TypeError("runner must provide run()")
        result = run()
        if not isinstance(result, Mapping):
            raise TypeError("live runner result must be a mapping")
        result = dict(result)
        if "attempt" in result:
            self.state["boss_gacha_attempts"] = int(result["attempt"])
        status = result.get("status")
        self.state["last_boss_gacha_result"] = result
        if status == "matched":
            self.state["boss_target_match"] = True
            self.current_task = Task.SCAN_AREA_MAP
            self.state["current_task"] = self.current_task.value
        elif status == "withdraw_and_retry":
            # A step-wise runner may return after one failed draw instead of
            # owning the whole loop.  Route that result back through the
            # normal guarded withdrawal task so the next passport check and
            # departure are not skipped.
            self.state["boss_target_match"] = False
            self.current_task = Task.WITHDRAW
            self.state["current_task"] = self.current_task.value
        elif status in {"safety_stop", "max_attempts"}:
            self.state["boss_target_match"] = False
            self.current_task = Task.RETURN_LABYRINTH_TOP
            self.state["current_task"] = self.current_task.value
            if status == "safety_stop":
                self.state["stop_reason"] = str(result.get("reason", "live_runner_safety_stop"))
                self._stopped = True
        return result

    def run_polling(
        self,
        *,
        poll_interval_seconds: float = 2.0,
        max_steps: int | None = None,
        max_consecutive_waiting: int = 5,
        state_path: str | Path | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> list[TaskRun]:
        """Poll task handlers until stop, with no busy loop.

        Completed tasks are chained immediately because their result already
        contains the next decision.  Only ``WAITING`` is delayed; this keeps
        fixed scripts fast while still allowing screen polling to be gentle.
        ``max_steps`` is a safety bound for foreground callers and tests.
        """
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if max_consecutive_waiting < 1:
            raise ValueError("max_consecutive_waiting must be positive")
        if max_steps is not None and max_steps < 1:
            raise ValueError("max_steps must be positive")
        runs: list[TaskRun] = []
        consecutive_waiting = 0
        while not self._stopped and (max_steps is None or len(runs) < max_steps):
            run = self.step()
            runs.append(run)
            if state_path is not None:
                self.save(state_path)
            if run.result.status is TaskStatus.WAITING:
                consecutive_waiting += 1
                if consecutive_waiting >= max_consecutive_waiting:
                    terminal = self._stop(
                        f"no_progress_timeout:{self.current_task.value}:{consecutive_waiting}"
                    )
                    runs.append(terminal)
                    if state_path is not None:
                        self.save(state_path)
                    break
                sleep_fn(poll_interval_seconds)
            else:
                consecutive_waiting = 0
        return runs

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(
        cls,
        path: str | Path,
        **kwargs: Any,
    ) -> "LabyrinthOrchestrator":
        source = Path(path)
        state = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
        if not isinstance(state, dict):
            raise ValueError("orchestrator state must be a JSON object")
        return cls(state, **kwargs)

    def _handler_for(self, task: Task) -> tuple[TaskHandler | None, str]:
        counts = self.state.get("task_execution_counts", {})
        count = counts.get(task.value, 0) if isinstance(counts, Mapping) else 0
        # Deterministic/script handlers always win.  AI is an explicit repair
        # fallback only for tasks listed in ai_repair_tasks; it is never the
        # default owner of a first execution.
        if task in self.script_handlers:
            return self.script_handlers[task], "script"
        ai_tasks = self.state.get("ai_repair_tasks", [])
        if self.ai_handler is not None and isinstance(ai_tasks, list) and task.value in ai_tasks:
            return self.ai_handler, "ai_repair"
        # Departure and guild selection are input-bearing mandatory tasks.
        # A pure fact validator must never make them appear implemented: use
        # an explicit user adapter when supplied, otherwise preserve the
        # safety stop for a missing live handler.
        if task in MANDATORY_SCRIPT_TASKS:
            if self.user_handler is not None:
                return self.user_handler, "user"
            # A previously observed confirmation is safe to validate offline;
            # it does not issue any input or infer a missing transition.
            from .deterministic_tasks import DETERMINISTIC_TASK_HANDLERS
            confirmed = (
                task is Task.LAUNCH_LABYRINTH and self.state.get("labyrinth_started") is True
            ) or (
                task is Task.SELECT_GUILD and isinstance(self.state.get("guild"), str)
            )
            if confirmed:
                return DETERMINISTIC_TASK_HANDLERS[task], "script"
            return None, "none"
        # Target matching is owned by the orchestrator policy.  Never let a
        # broad user fallback replace this safety-critical deterministic step.
        if task is Task.EVALUATE_BOSS_TARGET:
            return None, "none"
        # Pure fact-validation tasks are safe to run without an injected UI
        # adapter; they never send input and wait when facts are absent.
        from .deterministic_tasks import DETERMINISTIC_TASK_HANDLERS
        if task in DETERMINISTIC_TASK_HANDLERS:
            return DETERMINISTIC_TASK_HANDLERS[task], "script"
        if self.user_handler is not None:
            return self.user_handler, "user"
        from .deterministic_tasks import USER_CONFIRMATION_TASK_HANDLERS
        if task in USER_CONFIRMATION_TASK_HANDLERS:
            return USER_CONFIRMATION_TASK_HANDLERS[task], "user"
        return None, "none"

    def _apply_result(self, task: Task, executor: str, result: TaskResult) -> None:
        self.state.update(result.facts)
        counts = self.state.setdefault("task_execution_counts", {})
        if isinstance(counts, dict) and result.status is TaskStatus.COMPLETED:
            counts[task.value] = int(counts.get(task.value, 0)) + 1
        self.state["history"].append({
            "task": task.value,
            "executor": executor,
            "status": result.status.value,
            "reason": result.reason,
            "facts": result.facts,
        })
        if result.coordinate_candidates:
            self.state["coordinate_candidates"].extend(result.coordinate_candidates)

    def _record_step(
        self, *, task: Task, step_id: str, attempt_id: str,
        before_state: Mapping[str, Any], executor: str, result: TaskResult,
    ) -> None:
        """Store a compact before/action/expected/actual step contract."""
        facts = result.facts if isinstance(result.facts, Mapping) else {}
        after_state = deepcopy(self.state)
        record = {
            "task_id": task.value,
            "run_id": self.state["run_id"],
            "step_id": step_id,
            "attempt_id": attempt_id,
            "screen_before": before_state.get("screen_id"),
            "state_before": dict(before_state),
            "action": {"type": facts.get("action", task.value), "executor": executor,
                       "target": facts.get("target"), "parameters": facts.get("parameters", {})},
            "expected_screen": facts.get("expected_screen"),
            "expected_state": facts.get("expected_state", {}),
            "expected_condition": facts.get("expected_condition", facts.get("expected")),
            "screen_after": facts.get("screen_id", after_state.get("screen_id")),
            "state_after": after_state,
            "status": result.status.value,
            "reason_code": result.reason,
            "evidence": facts.get("evidence", facts.get("evidence_paths", [])),
            "changed_files": facts.get("changed_files", []),
            "patch_id": facts.get("patch_id"),
            "previous_attempts": list(self.state.get("history", []))[-5:],
            "user_constraints": list(self.state.get("user_locked_instructions", [])),
        }
        self.state.setdefault("step_records", []).append(record)
        if result.status in {TaskStatus.FAILED, TaskStatus.STOPPED}:
            packet = FailurePacket(
                task_id=task.value,
                step_id=step_id,
                attempt=len(self.state.get("failure_packets", [])) + 1,
                before={"screen_id": record["screen_before"], "state": dict(before_state)},
                action=record["action"],
                expected={"screen_id": record["expected_screen"], "state": record["expected_state"], "condition": record["expected_condition"]},
                observed={"screen_id": record["screen_after"], "state": after_state},
                failure={"reason_code": result.reason or "task_stopped", "details": result.reason or "task_stopped"},
                previous_attempts=tuple(record["previous_attempts"]),
                user_constraints=tuple(record["user_constraints"]),
                evidence=tuple(record["evidence"] if isinstance(record["evidence"], list) else []),
            )
            signature = failure_signature(packet)
            packet_data = packet.to_dict()
            packet_data["failure_signature"] = signature
            self.state.setdefault("failure_packets", []).append(packet_data)
            signatures = self.state.setdefault("failure_signatures", {})
            if isinstance(signatures, dict):
                signatures[signature] = int(signatures.get(signature, 0)) + 1
            record["failure_signature"] = signature

    def _passports_depleted(self) -> bool:
        passports = self.state.get("passports")
        return isinstance(passports, int) and passports <= 0

    def _consecutive_defeats_exceeded(self) -> bool:
        limit = self.state.get("max_consecutive_defeats", 3)
        count = self.state.get("consecutive_defeats", 0)
        return (
            isinstance(limit, int) and isinstance(count, int)
            and not isinstance(limit, bool) and not isinstance(count, bool)
            and count >= limit
        )

    def _evaluate_boss_target(self) -> TaskResult:
        """Compare both confirmed area bosses with the configured target pair."""
        names = self.state.get("boss_names")
        if not isinstance(names, Mapping):
            return TaskResult(TaskStatus.FAILED, reason="boss_names_missing")
        result = self.boss_gacha.evaluate(names)
        attempt = int(result["attempt"])
        self.state["boss_gacha_attempts"] = attempt
        if result["status"] == "safety_stop":
            return TaskResult(TaskStatus.FAILED, {"boss_gacha_attempts": attempt}, reason="boss_names_missing")
        mismatches = result.get("mismatches", {})
        if result["status"] == "max_attempts":
            return TaskResult(
                TaskStatus.COMPLETED,
                {"boss_target_match": False, "boss_target_mismatches": mismatches,
                 "boss_gacha_attempts": attempt, "boss_gacha_exhausted": True},
                reason=f"boss_gacha_max_attempts_reached:{attempt}",
            )
        matched = result["status"] == "matched"
        return TaskResult(
            TaskStatus.COMPLETED,
            {
                "boss_target_match": matched,
                "boss_target_mismatches": mismatches,
                "boss_gacha_attempts": attempt,
            },
            reason="target_pair_matched" if matched else "target_pair_mismatch_withdraw",
        )

    @staticmethod
    def _is_unexpected_screen(result: TaskResult) -> bool:
        """An executor must explicitly mark an unexpected/unknown screen.

        No retry or user-handler fallback is attempted for this condition.  This keeps
        recognition failures from turning into taps on an unrelated screen.
        """
        return result.facts.get("screen_status") in {"unexpected", "unknown"}

    def _stop(self, reason: str) -> TaskRun:
        result = TaskResult(TaskStatus.STOPPED, reason=reason)
        self._apply_result(self.current_task, "none", result)
        self.state["current_task"] = None
        self.state["stop_reason"] = reason
        self._stopped = True
        return TaskRun(self.current_task, "none", result, None)

    def _next_task(self, task: Task, result: TaskResult) -> Task | None:
        facts = result.facts
        # 汎用タスクは実行器が観測結果に次のタスクを明示できる。
        # 不正な値や自己参照は安全側で終端扱いにする。
        if task in {Task.USER_ASSIST, Task.CLOSE_DIALOG, Task.NEXT}:
            requested = facts.get("next_task")
            if isinstance(requested, str):
                try:
                    candidate = Task(requested)
                except ValueError:
                    return None
                return None if candidate in {task, Task.CHECK_CURRENT_SCREEN} else candidate
            return None
        if task is Task.CHECK_CURRENT_SCREEN:
            resume_task = facts.get("resume_task")
            if not isinstance(resume_task, str):
                return None
            try:
                next_task = Task(resume_task)
            except ValueError:
                return None
            if next_task is Task.CHECK_CURRENT_SCREEN:
                return None
            return next_task
        if task is Task.CHECK_PASSPORTS:
            return None if int(facts.get("passports", 0)) <= 0 else Task.LAUNCH_LABYRINTH
        if task is Task.LAUNCH_LABYRINTH:
            return Task.SELECT_GUILD
        if task is Task.SELECT_GUILD:
            # 出発直後は必ず初期処理（マップ表示・入口判定）を先に行う。
            # 新規出発では、その後に初期キャラ選択へ進む。
            return Task.INITIAL_SETUP
        if task is Task.SELECT_INITIAL_CHARACTERS:
            # 初期キャラ選択は初期処理の完了後に行われるため、
            # 選択後は同じ初期処理へ戻らず、エリア確認へ進む。
            return Task.CHECK_AREA
        if task is Task.CHECK_AREA:
            return Task.BOSS_NAME if int(facts.get("area", 0)) in {3, 5} else Task.SCAN_AREA_MAP
        if task is Task.BOSS_NAME:
            # ボス名の取得と対象組合せの判定を分離する。OCR/画面操作の
            # 結果を保持したまま、必ずオーケストレータ内のポリシー判定へ渡す。
            if isinstance(facts.get("boss_names"), Mapping):
                return Task.EVALUATE_BOSS_TARGET
            return None
        if task is Task.INITIAL_SETUP:
            if facts.get("boss_names_ready"):
                return Task.BOSS_NAME
            if self.state.get("challenge_active") is False:
                return Task.SELECT_INITIAL_CHARACTERS
            return Task.CHECK_AREA
        if task is Task.CHECK_AREA_BOSS:
            return Task.EVALUATE_BOSS_TARGET
        if task is Task.EVALUATE_BOSS_TARGET:
            return Task.SCAN_AREA_MAP if facts.get("boss_target_match") else Task.WITHDRAW
        if task is Task.SCAN_AREA_MAP:
            return Task.INITIAL_CONTINUE_DECISION if int(facts.get("area", 0)) == 1 else Task.PLAN_ROUTE
        if task is Task.INITIAL_CONTINUE_DECISION:
            return Task.WITHDRAW if facts.get("continue_run") is False else Task.SELECT_INITIAL_CHARACTERS
        if task is Task.PLAN_ROUTE:
            return Task.MOVE_ROUTE
        if task is Task.MOVE_ROUTE:
            return Task.CONFIRM_MOVE
        if task is Task.CONFIRM_MOVE:
            return Task.HANDLE_TILE
        if task is Task.HANDLE_TILE:
            tile = facts.get("tile_type")
            if tile == "event":
                if facts.get("event_choice") is not None:
                    return Task.PLAN_ROUTE
                return Task.SELECT_REWARD if facts.get("event_type") == "janken" else Task.IDENTIFY_ENEMY
            if tile == "shop":
                # ショップ判断は自動化対象外。専用タスクへ渡し、
                # 購入完了後にだけルート計画へ戻す。
                return Task.SHOP
            if tile in {"normal", "extreme", "hell", "area_boss"}:
                return Task.IDENTIFY_ENEMY
            if tile in {"relic", "connect_sign"}:
                return Task.SELECT_REWARD
            return Task.PLAN_ROUTE
        if task is Task.SHOP:
            return Task.PLAN_ROUTE
        if task is Task.IDENTIFY_ENEMY:
            return Task.PREPARE_BATTLE
        if task is Task.PREPARE_BATTLE:
            return Task.START_BATTLE
        if task is Task.START_BATTLE:
            return Task.WAIT_BATTLE_RESULT
        if task is Task.WAIT_BATTLE_RESULT:
            victory_outcomes = {"victory", "area3_boss", "area5_boss", "extreme", "hell", "normal"}
            if facts.get("battle_outcome") == "defeat":
                self.state["consecutive_defeats"] = int(self.state.get("consecutive_defeats", 0)) + 1
                retry_count = self.state.get("defeat_retry_count", 0)
                max_retries = self.state.get("max_defeat_retries", 1)
                if isinstance(retry_count, int) and isinstance(max_retries, int) and 0 <= retry_count < max_retries and self.state.get("auto_retry_after_defeat") is True and self.state.get("retry_composition"):
                    retry = self.state["retry_composition"]
                    valid_single = isinstance(retry, list) and retry and all(isinstance(name, str) and name.strip() for name in retry)
                    valid_multi = (
                        isinstance(retry, list) and retry and all(
                            isinstance(team, list) and team and all(isinstance(name, str) and name.strip() for name in team)
                            for team in retry
                        )
                    )
                    if valid_single or valid_multi:
                        previous = self.state.get("selected_composition", [])
                        flatten = lambda value: [name for team in value for name in team] if value and isinstance(value[0], list) else list(value) if isinstance(value, list) else []
                        if flatten(retry) == flatten(previous):
                            self.state["withdraw_reason"] = "battle_defeat_same_composition"
                            return Task.WITHDRAW
                        self.state["selected_composition"] = retry
                        self.state["composition_confirmations"] = [True] * (len(retry) if valid_multi else 1)
                        self.state["defeat_retry_count"] = retry_count + 1
                        return Task.PREPARE_BATTLE
                if isinstance(retry_count, int) and isinstance(max_retries, int) and 0 <= retry_count < max_retries and self.state.get("auto_retry_after_defeat") is True and isinstance(self.state.get("character_pool"), list):
                    previous = self.state.get("selected_composition", [])
                    excluded = []
                    if isinstance(previous, list):
                        excluded = [name for name in previous if isinstance(name, str)]
                    if previous and isinstance(previous[0], list):
                        excluded = [name for team in previous if isinstance(team, list) for name in team if isinstance(name, str)]
                    self.state["selected_characters"] = excluded
                    self.state["excluded_characters"] = excluded
                    self.state["auto_select_composition"] = True
                    self.state["composition_confirmations"] = None
                    self.state["defeat_retry_count"] = retry_count + 1
                    return Task.PREPARE_BATTLE
                # 敗北時は「帰還」ではなく、ラビリンス内の撤退操作で
                # 今回の挑戦を安全に打ち切る。別編成が明示されていない
                # 場合にユーザー補助へ止めると、危険な画面で放置される。
                self.state["withdraw_reason"] = "battle_defeat_or_unwinnable"
                return Task.WITHDRAW
            if facts.get("battle_outcome") in victory_outcomes:
                self.state["consecutive_defeats"] = 0
                return Task.SELECT_REWARD
            return Task.PREPARE_BATTLE
        if task is Task.SELECT_REWARD:
            return Task.PLAN_ROUTE
        if task is Task.WITHDRAW:
            # 撤退は対象外ボスの再抽選だけでなく、敗北・勝利困難時の
            # 安全な中断にも使用する。完全終了の「帰還する」とは別操作。
            if self.state.get("boss_gacha_exhausted") or self.state.get("retry_until_target", True) is False:
                # ボス名NGで検証を終了した場合は、状態をラビリンスTOPへ戻す。
                # 実際の戻る操作は注入されたスクリプトハンドラに委譲する。
                return Task.RETURN_LABYRINTH_TOP
            return Task.CHECK_PASSPORTS if self.state.get("retry_until_target", True) else None
        if task is Task.RETURN_LABYRINTH_TOP:
            return None
        return None
