import json
import sys

from scripts import task_run_boss_gacha_live as run_gacha


def test_single_command_runs_headless_prepare_then_gacha_with_saved_settings(monkeypatch, tmp_path, capsys):
    commands = []
    child_results = iter([
        (0, {"status": "completed", "screen_after": "labyrinth_top",
             "steps": [{"window": {"pid": 45678}}]}),
        (0, {"status": "matched", "attempt": 2}),
    ])
    monkeypatch.setattr(run_gacha, "_read_settings", lambda: {
        "passports": "37",
        "guild": "自警団（カォン）",
        "area3": ["ベノムサラマンドラ"],
        "area5": ["ゴブリンロード"],
    })
    monkeypatch.setattr(run_gacha, "resolve_adb_path", lambda _requested=None: r"C:\platform-tools\adb.exe")
    monkeypatch.setattr(run_gacha, "save_adb_path", lambda _path: None)
    monkeypatch.setattr(run_gacha, "pin_adb_environment", lambda _path: None)
    monkeypatch.setattr(run_gacha, "restore_adb_environment", lambda _snapshot: None)
    monkeypatch.setattr(run_gacha, "snapshot_adb_environment", lambda: (None, None))
    monkeypatch.setattr(run_gacha, "_acquire_device_lock", lambda _serial: tmp_path / "device.lock")

    def fake_child(command, *, env, name):
        assert env is not None
        commands.append((name, command))
        return next(child_results)

    monkeypatch.setattr(run_gacha, "_run_child", fake_child)
    monkeypatch.setattr(sys, "argv", ["task_run_boss_gacha_live.py"])

    assert run_gacha.main() == 0

    prepare = commands[0][1]
    gacha = commands[1][1]
    assert commands[0][0] == "preparation"
    assert "--no-gui" in prepare and "--lock-held" in prepare
    assert commands[1][0] == "gacha"
    assert "--execute" in gacha and "--lock-held" in gacha
    assert gacha[gacha.index("--bluestacks-pid") + 1] == "45678"
    assert gacha[gacha.index("--passports") + 1] == "37"
    assert gacha[gacha.index("--guild") + 1] == "自警団（カォン）"
    assert gacha.count("--area3-boss") == 1
    assert gacha.count("--area5-boss") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "matched"
    assert result["gacha"]["attempt"] == 2
