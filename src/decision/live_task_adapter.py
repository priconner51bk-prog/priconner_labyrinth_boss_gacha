"""実機 task_ CLI の結果をオーケストレータのTaskResultへ変換する。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .labyrinth_orchestrator import TaskResult, TaskStatus

ROOT = Path(__file__).resolve().parents[2]

# task_*_live.py が操作完了として返す共通ステータス。ここにない値は、
# AIが意味を推測して次の入力を送らないよう WAITING のままにする。
DEFAULT_LIVE_SUCCESS_STATUSES = frozenset({
    "ok", "completed", "scanned", "moved", "selected", "confirmed",
    "equipment_ready", "started", "advanced", "closed", "planned",
    "confirmed_move", "result_detected", "withdraw_selected",
    "withdraw_confirmed", "withdraw_cancelled", "retry_selected", "ready",
    "filled", "captured", "matched",
})


@dataclass(frozen=True)
class LiveScriptRun:
    """One subprocess invocation, including data needed to reproduce a failure."""

    script_name: str
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: float
    result: Mapping[str, Any] | None
    error: str | None


def _script_path(script_name: str) -> Path:
    """Resolve a task CLI without allowing a caller to escape scripts/."""
    name = Path(script_name)
    if name.name != script_name or name.suffix != ".py":
        raise ValueError("live_script_name_must_be_a_python_basename")
    script = ROOT / "scripts" / name
    if not script.exists():
        raise FileNotFoundError(script)
    return script


def _last_json_object(stdout: str) -> tuple[Mapping[str, Any] | None, bool]:
    """Return the last JSON object from noisy or pretty-printed stdout.

    Live CLIs may emit library warnings and progress objects before their final
    result.  Parsing only the final line rejects a perfectly valid indented
    result (whose final line is just ``}``).  ``raw_decode`` also lets each
    task keep its existing human-readable diagnostics while the caller gets a
    machine-readable final result.
    """
    decoder = json.JSONDecoder()
    last_value: Any = None
    found_value = False
    offset = 0
    while True:
        object_start = stdout.find("{", offset)
        array_start = stdout.find("[", offset)
        starts = [index for index in (object_start, array_start) if index >= 0]
        start = min(starts) if starts else -1
        if start < 0:
            break
        try:
            decoded, end = decoder.raw_decode(stdout[start:])
        except json.JSONDecodeError:
            offset = start + 1
            continue
        last_value = decoded
        found_value = True
        offset = start + max(end, 1)
    return (last_value if isinstance(last_value, Mapping) else None), found_value


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def execute_live_script(
    script_name: str,
    args: list[str] | None = None,
    *,
    timeout_seconds: float = 180.0,
) -> LiveScriptRun:
    """Execute a task once and retain stdout/stderr even when it fails.

    This is deliberately a one-shot executor.  Retry policy belongs to the
    caller so that an AI repair loop cannot accidentally repeat game input.
    """
    script = _script_path(script_name)
    command = (sys.executable, str(script), *(args or []))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return LiveScriptRun(
            script_name, command, None, _as_text(exc.stdout), _as_text(exc.stderr),
            (time.perf_counter() - started) * 1000,
            None, f"live_script_timeout:{script_name}:{timeout_seconds:g}s",
        )
    stdout = _as_text(completed.stdout)
    result, found_json = _last_json_object(stdout)
    if result is None:
        if found_json:
            error = f"live_script_result_not_object:{script_name}"
        else:
            error = (f"live_script_no_json:{script_name}:{completed.returncode}"
                     if not stdout.strip() else f"live_script_invalid_json:{script_name}")
    else:
        error = None
    return LiveScriptRun(
        script_name, command, completed.returncode, stdout, _as_text(getattr(completed, "stderr", "")),
        (time.perf_counter() - started) * 1000, result, error,
    )


def run_live_script(script_name: str, args: list[str] | None = None, *, timeout_seconds: float = 180.0) -> Mapping[str, Any]:
    """Execute one task CLI and return its final structured result."""
    run = execute_live_script(script_name, args, timeout_seconds=timeout_seconds)
    if run.error is not None:
        raise RuntimeError(run.error)
    if run.result is None:  # Defensive guard for future changes to execute_live_script.
        raise RuntimeError(f"live_script_no_json:{script_name}:{run.returncode}")
    return run.result


def task_result_from_live(
    result: Mapping[str, Any],
    *,
    success_statuses: set[str] | frozenset[str] = DEFAULT_LIVE_SUCCESS_STATUSES,
) -> TaskResult:
    """CLI結果を失敗・安全停止優先でTaskResultへ変換する。"""
    status = str(result.get("status", "")).strip()
    facts = {str(key): value for key, value in result.items() if key not in {"status", "reason"}}
    evidence_paths = result.get("evidence_paths")
    if evidence_paths is not None:
        if not isinstance(evidence_paths, (list, tuple)) or not all(isinstance(path, str) for path in evidence_paths):
            return TaskResult(TaskStatus.STOPPED, facts, "evidence_paths_invalid")
        missing = [path for path in evidence_paths if not (ROOT / path).is_file()]
        if missing:
            facts["missing_evidence_paths"] = missing
            return TaskResult(TaskStatus.STOPPED, facts, "evidence_paths_missing")
    if status in {"safety_stop", "failed"}:
        return TaskResult(TaskStatus.STOPPED, facts, str(result.get("reason", "live_script_safety_stop")))
    if status not in success_statuses:
        return TaskResult(TaskStatus.WAITING, facts, str(result.get("reason", "live_script_waiting")))
    return TaskResult(TaskStatus.COMPLETED, facts)
