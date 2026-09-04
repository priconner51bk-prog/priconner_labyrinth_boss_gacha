from unittest.mock import patch

import tkinter as tk

from main import BossGachaWindow


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


def test_gui_start_enables_stop_and_stop_kills_child_process():
    root = tk.Tk()
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


def test_gui_distinguishes_success_failure_and_safety_stop():
    root = tk.Tk()
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        window._update_status_from_output('{"status":"matched"}')
        assert str(window.status["text"]).startswith("成功")
        window._update_status_from_output('{"status":"max_attempts","max_attempts":100}')
        assert str(window.status["text"]).startswith("失敗")
        window._update_status_from_output('{"status":"safety_stop"}')
        assert str(window.status["text"]).startswith("停止")
    finally:
        root.destroy()


def test_gui_uses_automatic_resume_and_default_guild():
    root = tk.Tk()
    root.withdraw()
    try:
        window = BossGachaWindow(root)
        assert window.guild.get() == "美食殿"
        assert "トゥインクルウィッシュ" in window.GUILDS
        assert "サレンディア救護院" in window.GUILDS
        assert "王宮騎士団（NIGHTMARE）" in window.GUILDS
        assert "リトルリリカル" in window.GUILDS
        assert len(window.GUILDS) == 14
        assert window.passports.get() == "100"
        assert window.AREA3_BOSSES == ("マダムエレクトラ", "フロストハウンド", "ダークガーゴイル", "グレーターゴーレム", "ベノムサラマンドラ")
        assert window.AREA5_BOSSES == ("キマイラ", "ゴブリンロード", "ラースドラゴン", "アルティマガーディアン", "ジャバウォック")
        command = window._command(resume=True)
        assert "--resume-screen" not in command
        assert "--guild" in command and command[command.index("--guild") + 1] == "美食殿"
    finally:
        root.destroy()
