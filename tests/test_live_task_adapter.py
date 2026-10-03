"""The auxiliary runner contract, without sending any device input."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from decision import live_task_adapter as adapter
from scripts import tool_run_live_task as cli


def test_auxiliary_cli_help_starts_without_orchestrator():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "tool_run_live_task.py"), "--help"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert "--output-root" in completed.stdout


def test_auxiliary_cli_writes_mock_bundle_without_running_child(tmp_path, monkeypatch, capsys):
    command = (sys.executable, "scripts/task_boss_gacha_live.py", "--help")
    fake_run = adapter.LiveScriptRun(
        "task_boss_gacha_live.py", command, 0,
        '{"status":"completed"}\n', "", 1.0, {"status": "completed"}, None,
    )
    execute = Mock(return_value=fake_run)
    monkeypatch.setattr(cli, "execute_live_script", execute)

    assert cli.main(["--output-root", str(tmp_path), "task_boss_gacha_live.py", "--", "--help"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "completed"
    assert summary["failure"] is False
    bundle = Path(summary["bundle"])
    assert json.loads((bundle / "result.json").read_text(encoding="utf-8"))["command"] == list(command)
    assert (bundle / "stdout.txt").read_text(encoding="utf-8") == fake_run.stdout
    execute.assert_called_once_with("task_boss_gacha_live.py", ["--help"], timeout_seconds=180.0)


def test_nonzero_child_exit_overrides_json_success(monkeypatch, tmp_path, capsys):
    completed = subprocess.CompletedProcess(
        args=[], returncode=7, stdout='{"status":"completed"}\n', stderr="child failed",
    )
    child = Mock(return_value=completed)
    monkeypatch.setattr(adapter.subprocess, "run", child)

    run = adapter.execute_live_script("task_boss_gacha_live.py", ["--help"])
    assert run.returncode == 7
    assert run.result == {"status": "completed"}
    with pytest.raises(RuntimeError, match="live_script_exit_nonzero:task_boss_gacha_live.py:7"):
        adapter.run_live_script("task_boss_gacha_live.py", ["--help"])

    assert cli.main(["--output-root", str(tmp_path), "task_boss_gacha_live.py", "--", "--help"]) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "failed"
    assert summary["failure"] is True
    assert summary["repair_kind"] == "exit_code_contract"
    assert json.loads((Path(summary["bundle"]) / "result.json").read_text(encoding="utf-8"))["returncode"] == 7
    assert child.call_count == 3
