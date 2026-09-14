"""Run one live task and write a compact, AI-readable execution bundle.

The tool does not retry.  It is the hand-off boundary for the controlled
"run -> inspect/fix -> rerun" loop: every invocation leaves behind the exact
command, raw output, parsed result, and a repair brief.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decision.live_task_adapter import LiveScriptRun, execute_live_script


def _is_failure(run: LiveScriptRun) -> bool:
    status = str(run.result.get("status", "")) if run.result else ""
    return run.error is not None or run.returncode != 0 or status in {"failed", "safety_stop"}


def _repair_kind(run: LiveScriptRun) -> str:
    if run.error and run.error.startswith("live_script_timeout"):
        return "timeout"
    if run.error:
        return "cli_contract_or_crash"
    if run.result and run.result.get("status") == "safety_stop":
        return "safety_gate"
    if run.returncode:
        return "exit_code_contract"
    return "none"


def _powershell_command(command: tuple[str, ...]) -> str:
    """Render the stored argument array as a copyable PowerShell command."""
    quoted = ["'" + part.replace("'", "''") + "'" for part in command]
    return "& " + " ".join(quoted)


def write_execution_bundle(run: LiveScriptRun, output_root: Path) -> tuple[Path, dict[str, object]]:
    """Persist an immutable-per-run hand-off bundle and return its summary."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    bundle = output_root / f"{stamp}_{Path(run.script_name).stem}"
    bundle.mkdir(parents=True, exist_ok=False)
    failed = _is_failure(run)
    payload: dict[str, object] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script": run.script_name,
        "command": list(run.command),
        "returncode": run.returncode,
        "duration_ms": round(run.duration_ms, 1),
        "result": dict(run.result) if run.result is not None else None,
        "error": run.error,
        "failure": failed,
        "repair_kind": _repair_kind(run),
    }
    (bundle / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (bundle / "stdout.txt").write_text(run.stdout, encoding="utf-8")
    (bundle / "stderr.txt").write_text(run.stderr, encoding="utf-8")
    command = _powershell_command(run.command)
    brief = [
        "# Live task repair brief",
        "",
        f"- Script: `{run.script_name}`",
        f"- Exit code: `{run.returncode}`",
        f"- Classification: `{payload['repair_kind']}`",
        f"- Exact reproduction command: `{command}`",
        "",
        "Read `result.json`, `stderr.txt`, and the task source before changing code.",
        "Add or update a fixture/unit test for a code defect, then run that test before rerunning this exact command.",
        "Do not add `--execute` or broaden task arguments during repair. If the original command already has `--execute`, rerun it at most once after a verified fix and preserve every safety stop.",
        "A `safety_gate` result can be correct: inspect its reason and captured screen evidence before treating it as a code defect.",
    ]
    (bundle / "repair_request.md").write_text("\n".join(brief) + "\n", encoding="utf-8")
    return bundle, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="実機タスクを1回実行し、AI修正用の証跡束を保存")
    parser.add_argument("script", help="scripts/ 配下の task_*.py ファイル名")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-root", type=Path, default=ROOT / "output" / "live_runs")
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help="`--` の後ろに対象スクリプトの引数を指定")
    args = parser.parse_args(argv)
    script_args = args.script_args[1:] if args.script_args[:1] == ["--"] else args.script_args
    try:
        run = execute_live_script(args.script, script_args, timeout_seconds=args.timeout)
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "runner_error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    bundle, payload = write_execution_bundle(run, args.output_root)
    print(json.dumps({"status": "failed" if payload["failure"] else "completed", "bundle": str(bundle), **payload}, ensure_ascii=False))
    return 2 if payload["failure"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
