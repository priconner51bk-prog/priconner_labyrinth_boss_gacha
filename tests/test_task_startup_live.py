"""タイトル画面が安定してから開始入力へ進むことを確認する。"""

from unittest.mock import Mock

from scripts import task_startup_live


def test_observe_title_retries_unknown_render_frames(monkeypatch):
    probe = Mock()
    probe.observe_screen.side_effect = [None, None, "title"]
    monkeypatch.setattr(task_startup_live.time, "sleep", lambda _seconds: None)

    assert task_startup_live.observe_title(None, probe) == "title"
    assert probe.observe_screen.call_count == 3


def test_startup_timeout_returns_to_title_then_retries_once(monkeypatch, capsys):
    probe = Mock()
    probe.observe_screen.side_effect = ["title", "startup_error", "title", "home"]
    probe.target_visible.return_value = True
    probe.target_center.side_effect = lambda label: (640, 675) if label == "Touch To Start" else (640, 585)
    monkeypatch.setattr(task_startup_live, "AdbScreenCapture", Mock())
    monkeypatch.setattr(task_startup_live, "load_template_probe_config", lambda *_args: probe)
    tap = Mock(side_effect=[RuntimeError("タップ後に画面変化がないため停止"), None, None])
    monkeypatch.setattr(task_startup_live, "run_adb_coordinate_sequence", tap)
    monkeypatch.setattr("sys.argv", ["task_startup_live.py"])

    assert task_startup_live.main() == 0
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["screen_after"] == "home"
    assert result["attempts"] == 2
    assert [call.args[0] for call in tap.call_args_list] == [[(640, 675)], [(640, 585)], [(640, 675)]]


def test_startup_timeout_stops_after_three_start_attempts(monkeypatch, capsys):
    probe = Mock()
    probe.observe_screen.side_effect = ["title", "startup_error", "title", "startup_error", "title", "startup_error"]
    probe.target_visible.return_value = True
    probe.target_center.side_effect = lambda label: (640, 675) if label == "Touch To Start" else (640, 585)
    monkeypatch.setattr(task_startup_live, "AdbScreenCapture", Mock())
    monkeypatch.setattr(task_startup_live, "load_template_probe_config", lambda *_args: probe)
    tap = Mock(side_effect=[RuntimeError("タップ後に画面変化がないため停止"), None,
                            RuntimeError("タップ後に画面変化がないため停止"), None,
                            RuntimeError("タップ後に画面変化がないため停止")])
    monkeypatch.setattr(task_startup_live, "run_adb_coordinate_sequence", tap)
    monkeypatch.setattr("sys.argv", ["task_startup_live.py"])

    assert task_startup_live.main() == 2
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["reason"] == "startup_timeout_retries_exhausted"
    assert result["attempts"] == 3
    assert tap.call_count == 5
