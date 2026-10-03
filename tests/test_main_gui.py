import json
import subprocess
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

import main
from main import BossGachaWindow


@pytest.fixture(autouse=True)
def isolated_gui_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "GUI_SETTINGS", tmp_path / "gui_settings.json")


@pytest.fixture(scope="module")
def tk_interpreter():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.stdout = []
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode or 0

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_gui_start_enables_stop_and_stop_kills_child_process(tk_interpreter):
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        with patch("main.subprocess.Popen", FakeProcess), patch("main.messagebox.askyesno", return_value=True):
            window.start()
            process = window.process
            assert str(window.stop_button["state"]) == "normal"
            assert process is not None
            window.stop()
            assert process.killed
    finally:
        root.destroy()


def test_gui_distinguishes_success_failure_and_safety_stop(tk_interpreter):
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        window._update_status_from_output('{"status":"matched"}')
        assert str(window.status["text"]).startswith("成功")
        window._update_status_from_output('{"status":"max_attempts","max_attempts":100}')
        assert str(window.status["text"]).startswith("失敗")
        window._update_status_from_output('{"status":"safety_stop"}')
        assert str(window.status["text"]).startswith("停止")
        window._update_status_from_output('{"status":"safety_stop","reason":"startup_network_timeout"}')
        assert "通信タイムアウト" in str(window.status["text"])
        window._update_status_from_output('{"status":"safety_stop","reason":"communication_retries_exhausted","attempt_count":3}')
        assert "3回続いた" in str(window.status["text"])
    finally:
        root.destroy()


def test_gui_uses_automatic_resume_and_default_guild(tk_interpreter):
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        assert window.guild.get() == "自警団（カォン）"
        assert "トゥインクルウィッシュ" in window.GUILDS
        assert "サレンディア救護院" in window.GUILDS
        assert "王宮騎士団（NIGHTMARE）" in window.GUILDS
        assert "リトルリリカル" in window.GUILDS
        assert len(window.GUILDS) == 14
        assert window.passports.get() == "1000"
        assert window.AREA3_BOSSES == ("マダムエレクトラ", "フロストハウンド", "ダークガーゴイル", "グレーターゴーレム", "ベノムサラマンドラ")
        assert window.AREA5_BOSSES == ("キマイラ", "ゴブリンロード", "ラースドラゴン", "アルティマガーディアン", "ジャバウォック")
        policy = json.loads((Path(main.ROOT) / "configs" / "labyrinth_target_policy.json").read_text(encoding="utf-8"))
        assert [name for name, var in window.area3_vars.items() if var.get()] == [policy["target_bosses"]["3"]]
        assert [name for name, var in window.area5_vars.items() if var.get()] == [policy["target_bosses"]["5"]]
        command = window._command(resume=True)
        assert "--resume-screen" not in command
        assert "--guild" in command and command[command.index("--guild") + 1] == "自警団（カォン）"
        assert command[command.index("--adb") + 1] == main.resolve_adb_path()
        assert command[command.index("--area3-boss") + 1] == policy["target_bosses"]["3"]
        assert command[command.index("--area5-boss") + 1] == policy["target_bosses"]["5"]
    finally:
        root.destroy()


def test_gui_adb_restart_reconnects_tcp_serial(tk_interpreter, monkeypatch):
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            stdout = "List of devices attached\n127.0.0.1:5555\tdevice\n" if command[-1] == "devices" else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        class ImmediateThread:
            def __init__(self, target, daemon=True):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(main.subprocess, "run", run)
        monkeypatch.setattr(main.threading, "Thread", ImmediateThread)
        window.restart_adb()
        root.update()

        adb_command = main.resolve_adb_path()
        assert commands == [
            [adb_command, "kill-server"], [adb_command, "start-server"],
            [adb_command, "connect", "127.0.0.1:5555"], [adb_command, "devices"],
        ]
        assert str(window.status["text"]) == "待機中"
    finally:
        root.destroy()


def test_gui_restores_saved_settings_and_cli_arguments(tk_interpreter):
    main.GUI_SETTINGS.write_text(json.dumps({
        "serial": "localhost:5556",
        "passports": "7",
        "guild": "フォレスティエ",
        "area3": ["ベノムサラマンドラ", "フロストハウンド"],
        "area5": ["ゴブリンロード", "キマイラ"],
    }, ensure_ascii=False), encoding="utf-8")
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        assert window.serial.get() == "localhost:5556"
        assert window.passports.get() == "7"
        assert window.guild.get() == "フォレスティエ"
        command = window._command()
        assert command[command.index("--serial") + 1] == "localhost:5556"
        assert command[command.index("--passports") + 1] == "7"
        assert command[command.index("--guild") + 1] == "フォレスティエ"
        assert [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--area3-boss"] == [
            "フロストハウンド", "ベノムサラマンドラ"]
        assert [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--area5-boss"] == [
            "キマイラ", "ゴブリンロード"]
        window._save_gui_settings()
        saved = json.loads(main.GUI_SETTINGS.read_text(encoding="utf-8"))
        assert saved["area3"] == ["フロストハウンド", "ベノムサラマンドラ"]
        assert saved["area5"] == ["キマイラ", "ゴブリンロード"]
    finally:
        root.destroy()


def test_gui_missing_input_error_uses_attempts_label(tk_interpreter):
    root = tk.Toplevel(tk_interpreter)
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        window.passports.delete(0, "end")
        with pytest.raises(ValueError, match="試行回数"):
            window._command()
    finally:
        root.destroy()
