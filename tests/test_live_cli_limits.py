"""CLI引数から実際のrunner終了までを、ADB/OCRなしで検証する。"""

import json
from unittest.mock import Mock

import pytest
from scripts import task_boss_gacha_live as cli


@pytest.mark.parametrize("count,expected", [(1, 1), (2, 2), (99, 99), (100, 100), (1000, 1000)])
def test_cli_attempt_limit(count, expected, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute", "--default-models", "--attempts", str(count),
                                    "--area3-boss", "ベノムサラマンドラ", "--area5-boss", "ゴブリンロード"])
    probe = Mock()
    probe.observe_screen.return_value = "initial_char"
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "OperationLogger", Mock())
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    monkeypatch.setattr(cli, "choose_ocr_device", lambda *a: "cpu")
    monkeypatch.setattr(cli.PaddleOCRAdapter, "from_default_models", Mock())
    begin, withdraw = Mock(), Mock()
    monkeypatch.setattr(cli.LiveBossGachaWorkflow, "begin_attempt", begin)
    monkeypatch.setattr(cli.LiveBossGachaWorkflow, "read_boss_names", lambda *a, **k: {"3": "別", "_early_reject": "true"})
    monkeypatch.setattr(cli.LiveBossGachaWorkflow, "withdraw", withdraw)
    assert cli.main() == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == "max_attempts"
    assert result["attempt"] == result["max_attempts"] == expected
    assert begin.call_count == withdraw.call_count == expected


def test_zero_attempts_does_not_load_ocr_or_send_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute", "--attempts", "1"])
    probe = Mock()
    probe.observe_screen.return_value = "initial_char"
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    ocr, tap = Mock(), Mock()
    monkeypatch.setattr(cli.PaddleOCRAdapter, "from_default_models", ocr)
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["reason"] == "allowed_bosses_not_configured"
    ocr.assert_not_called()
    tap.assert_not_called()


def test_title_recovery_only_relaunches_and_reobserves_known_screen(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--title-recovery-only"])
    probe = Mock()
    probe.observe_screen.side_effect = [None] * 40 + ["labyrinth_top"]
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    recovery = Mock(return_value={"ok": True, "stage": "title_tap"})
    monkeypatch.setattr(cli, "relaunch_game_from_title", recovery)

    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result == {"status": "title_recovery_ok", "screen_id": "labyrinth_top", "execute": False}
    recovery.assert_called_once()


def test_title_screen_id_also_triggers_title_recovery(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--title-recovery-only"])
    probe = Mock()
    probe.observe_screen.side_effect = ["title", "labyrinth_top"]
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    recovery = Mock(return_value={"ok": True, "stage": "title_tap"})
    monkeypatch.setattr(cli, "relaunch_game_from_title", recovery)

    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == "title_recovery_ok"
    assert result["screen_id"] == "labyrinth_top"
    recovery.assert_called_once()


def test_notice_is_closed_once_before_continuing(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute"])
    probe = Mock()
    probe.observe_screen.side_effect = ["notice", "initial_char"]
    probe.target_visible.return_value = True
    probe.target_center.return_value = (640, 640)
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 2
    tap.assert_called_once()
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[1] == {"status": "notice_closed", "close_tap_count": 1,
                         "close_button_point": [640, 640],
                         "screen_id": "initial_char", "execute": True}
    assert output[-1]["reason"] == "allowed_bosses_not_configured"


def test_notice_preflight_does_not_tap(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live"])
    probe = Mock()
    probe.observe_screen.return_value = "notice"
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 0
    tap.assert_not_called()
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "notice_detected"


def test_notice_without_confirmed_close_button_sends_no_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute"])
    probe = Mock()
    probe.observe_screen.return_value = "notice"
    probe.target_visible.return_value = False
    probe.target_center.return_value = None
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 2
    tap.assert_not_called()
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["reason"] == "notice_close_button_not_confirmed"
    assert result["close_tap_count"] == 0


def test_title_is_tapped_once_without_relaunch(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute"])
    probe = Mock()
    probe.observe_screen.side_effect = ["title", "initial_char"]
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap, relaunch = Mock(), Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)
    monkeypatch.setattr(cli, "relaunch_game_from_title", relaunch)

    assert cli.main() == 2
    tap.assert_called_once()
    relaunch.assert_not_called()
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[1]["status"] == "startup_transition"
    assert output[1]["title_tap_count"] == 1


def test_startup_splash_waits_for_title_then_preflight_stops_without_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live"])
    probe = Mock()
    probe.observe_screen.side_effect = ["startup_splash", "title"]
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 0
    tap.assert_not_called()
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[1] == {"status": "startup_detected", "screen_id": "startup_splash", "execute": False}


def test_startup_error_uses_confirmed_target_center_then_title_flow(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute"])
    probe = Mock()
    probe.observe_screen.side_effect = ["startup_error", "title", "initial_char"]
    probe.target_visible.return_value = True
    probe.target_center.return_value = (640, 585)
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 2
    assert tap.call_count == 2
    assert tap.call_args_list[0].args[0] == [(640, 585)]
    assert tap.call_args_list[1].args[0] == [(640, 670)]
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[1]["status"] == "error_title_transition"
    assert output[1]["title_button_tap_count"] == 1
    assert output[-1]["reason"] == "allowed_bosses_not_configured"


def test_startup_error_without_confirmed_button_sends_no_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live", "--execute"])
    probe = Mock()
    probe.observe_screen.return_value = "startup_error"
    probe.target_visible.return_value = False
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *a: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture", Mock())
    monkeypatch.setattr(cli, "ensure_adb_device", lambda serial: {"ok": True, "serial": serial})
    monkeypatch.setattr(cli, "TimingTrace", Mock())
    tap = Mock()
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)

    assert cli.main() == 2
    tap.assert_not_called()
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["stop_reason"] == "title_button_not_confirmed"
