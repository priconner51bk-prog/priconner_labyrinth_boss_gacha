"""ADB画面取得の再試行でADBサーバーを再起動しないことを確認する。"""

import subprocess

import pytest

from vision import capture as capture_module
from vision.capture import AdbScreenCapture


def test_screencap_retries_without_restarting_adb_server(monkeypatch, tmp_path):
    commands = []
    sleeps = []

    def run(command, **_kwargs):
        commands.append(command)
        if len(commands) < 3:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout=b"png", stderr=b"")

    monkeypatch.setattr(capture_module.subprocess, "run", run)
    monkeypatch.setattr(capture_module.time, "sleep", sleeps.append)
    output = tmp_path / "capture.png"

    result = AdbScreenCapture().capture(output)

    assert result.image_path == str(output)
    assert output.read_bytes() == b"png"
    assert len(commands) == 3
    assert all("exec-out" in command for command in commands)
    assert sleeps == [0.2, 0.2]


def test_screencap_failure_is_bounded_and_does_not_restart_adb(monkeypatch, tmp_path):
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(capture_module.subprocess, "run", run)
    monkeypatch.setattr(capture_module.time, "sleep", lambda _duration: None)

    with pytest.raises(RuntimeError, match="failed after 3 consecutive attempts"):
        AdbScreenCapture().capture(tmp_path / "capture.png")

    assert len(commands) == 3
    assert all("exec-out" in command for command in commands)
