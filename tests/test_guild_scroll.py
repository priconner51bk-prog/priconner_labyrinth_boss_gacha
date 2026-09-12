"""ギルド横スクロールの安全境界・再試行・画面安定性の試験。

この試験群は、次の実機運用契約を固定する。

* ADBスワイプは一時的な失敗を再試行し、上限到達後に停止する。
* 想定外画面ではADB入力を発行しない。
* ギルド走査は各スワイプ前にギルド選択画面を安定確認する。
* テンプレート検出の有無にかかわらず、対象ギルドを選択できる。
* 横スクロールは有限範囲を走査し、無限ループしない。

失敗した項目は未実装または実装との仕様不一致を示し、合格扱いにしない。
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.labyrinth_route import run_adb_swipe


def _swipe_commands(mock_run) -> list[list[str]]:
    return [call.args[0] for call in mock_run.call_args_list if "swipe" in call.args[0]]


def test_swipe_retries_transient_adb_failure():
    """一時的なADB失敗は再試行後に成功する。"""
    attempts = {"count": 0}

    def fake_run(command, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise subprocess.CalledProcessError(1, command)
        return type("Completed", (), {"stdout": "", "returncode": 0})()

    with patch("scripts.labyrinth_route.subprocess.run", side_effect=fake_run), \
         patch("scripts.labyrinth_route.ensure_adb_connection"), \
         patch("scripts.labyrinth_route.AdbCoordinateScaler") as scaler:
        scaler.return_value.point.side_effect = lambda point: point
        run_adb_swipe((250, 400), (1100, 400), serial="127.0.0.1:5555",
                      healthcheck=True, screen_guard=lambda: True)
    assert attempts["count"] == 2


def test_swipe_stops_when_screen_changes():
    """画面ガード失敗時は入力せず、安全停止する。"""
    with patch("scripts.labyrinth_route.subprocess.run") as mock_run, \
         patch("scripts.labyrinth_route.ensure_adb_connection"), \
         patch("scripts.labyrinth_route.AdbCoordinateScaler") as scaler:
        scaler.return_value.point.side_effect = lambda point: point
        with pytest.raises(RuntimeError, match='想定外画面'):
            run_adb_swipe((250, 400), (1100, 400), serial="127.0.0.1:5555",
                          healthcheck=True, screen_guard=lambda: False)
    assert not mock_run.called


def test_swipe_gives_up_after_three_attempts():
    """ADB失敗が連続した場合は3回で打ち切る。"""
    with patch("scripts.labyrinth_route.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "adb")) as mock_run, \
         patch("scripts.labyrinth_route.ensure_adb_connection"), \
         patch("scripts.labyrinth_route.AdbCoordinateScaler") as scaler:
        scaler.return_value.point.side_effect = lambda point: point
        with pytest.raises(subprocess.CalledProcessError):
            run_adb_swipe((250, 400), (1100, 400), serial="127.0.0.1:5555",
                          healthcheck=True, screen_guard=lambda: True)
    assert len(_swipe_commands(mock_run)) == 3


def test_guild_scan_stabilizes_screen_before_each_swipe():
    """各ページのスワイプにguild_select画面ガードを渡す。"""
    source = (ROOT / "scripts" / "task_boss_gacha_live.py").read_text(encoding="utf-8")
    scan = source[source.index("def dynamic_guild_point"):source.index("dynamic_point = None")]
    loop_index = scan.index("for page in range")
    guard_index = scan.index(
        'screen_guard=lambda: observe_screen_stable() == "guild_select"', loop_index
    )
    swipe_index = scan.index("run_adb_swipe(", loop_index)
    assert loop_index < swipe_index < guard_index


def test_guild_selection_uses_collected_templates_for_labels():
    """収集済みテンプレートを使って対象ギルドを判定する。"""
    source = (ROOT / "scripts" / "task_boss_gacha_live.py").read_text(encoding="utf-8")
    scan = source[source.index("def dynamic_guild_point"):source.index("dynamic_point = None")]
    assert "template_names =" in scan
    assert "cv2.matchTemplate" in scan
    assert "guild_template_probe" in scan


def test_guild_selection_allows_full_cross_screen_scan():
    """横スクロール走査は有限の双方向範囲を対象にする。"""
    source = (ROOT / "scripts" / "task_boss_gacha_live.py").read_text(encoding="utf-8")
    scan = source[source.index("def dynamic_guild_point"):source.index("dynamic_point = None")]
    assert "fallback_steps = max(1, len(guild_order) - 1)" in scan
    assert "fallback =" in scan
    assert "directions.extend(fallback)" in scan
