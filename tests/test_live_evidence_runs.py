"""Offline checks for evidence isolation across live CLI invocations."""

import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from boss_gacha.runner import LiveSafetyStop
from decision.operation_log import OperationLogger
from scripts import task_boss_gacha_live as cli


def test_two_offline_runs_keep_first_png_and_operation_log(tmp_path, monkeypatch, capsys):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "labyrinth_target_policy.json").write_text(
        json.dumps({"target_bosses": {"3": "boss3", "5": "boss5"}}), encoding="utf-8"
    )
    (config_dir / "labyrinth_guild_starting_members.json").write_text(
        json.dumps({"selection_policy": {"preferred_guilds": ["guild"]},
                    "guilds": {"guild": {}}}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["live", "--execute", "--attempts", "1",
                                  "--area3-boss", "boss3", "--area5-boss", "boss5"])
    probe = Mock()
    probe.observe_screen.return_value = "initial_char"
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *args: probe)
    captures = {"count": 0}

    def capture_factory(**kwargs):
        def capture(path):
            captures["count"] += 1
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + str(captures["count"]).encode())
        return SimpleNamespace(capture=capture)

    monkeypatch.setattr(cli, "AdbScreenCapture", capture_factory)
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", Mock(side_effect=AssertionError("unexpected input")))
    monkeypatch.setattr(cli, "run_adb_swipe", Mock(side_effect=AssertionError("unexpected input")))
    monkeypatch.setattr(cli.LiveBossGachaWorkflow, "begin_attempt",
                        lambda *args: (_ for _ in ()).throw(LiveSafetyStop("offline_simulated_stop")))

    def operation_logger(jsonl_path, markdown_path):
        logger = OperationLogger(jsonl_path, markdown_path)
        logger.record(task="offline_test", purpose="mock observation", screen_before="initial_char",
                      action="no input", outcome="observed")
        return logger

    monkeypatch.setattr(cli, "OperationLogger", operation_logger)
    runs_root = tmp_path / "data" / "observations" / "live" / "task_boss_gacha_runs"
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["reason"] == "offline_simulated_stop"
    first_dir, = runs_root.iterdir()
    first_png, = first_dir.glob("task_boss_gacha_screen_*.png")
    first_log = first_dir / "boss_gacha_operations.jsonl"
    png_before, log_before = first_png.read_bytes(), first_log.read_bytes()

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["reason"] == "offline_simulated_stop"
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 2
    second_dir, = [path for path in run_dirs if path != first_dir]
    assert list(second_dir.glob("task_boss_gacha_screen_*.png"))
    assert (second_dir / "boss_gacha_operations.jsonl").exists()
    assert first_png.read_bytes() == png_before
    assert first_log.read_bytes() == log_before
    cli.run_adb_coordinate_sequence.assert_not_called()
    cli.run_adb_swipe.assert_not_called()


def test_evidence_run_dir_rejects_reused_id(tmp_path, monkeypatch):
    fixed = datetime(2026, 9, 25, tzinfo=timezone.utc)
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(now=lambda _: fixed))
    monkeypatch.setattr(cli.uuid, "uuid4", lambda: SimpleNamespace(hex="same"))
    first = cli.create_evidence_run_dir(tmp_path)
    with pytest.raises(FileExistsError):
        cli.create_evidence_run_dir(tmp_path)
    assert first.is_dir()
