"""ギルド横スクロールの安全境界・画面安定性の試験。

この試験群は、次の実機運用契約を固定する。

* ADBスワイプの送信結果が不明なら再送せず、画面を再観測して停止する。
* 想定外画面ではADB入力を発行しない。
* ギルド走査は各スワイプ前にギルド選択画面を安定確認する。
* テンプレート検出の有無にかかわらず、対象ギルドを選択できる。
* 横スクロールは有限範囲を走査し、無限ループしない。

失敗した項目は未実装または実装との仕様不一致を示し、合格扱いにしない。
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import task_boss_gacha_live as cli
from scripts.labyrinth_route import SwipeOutcomeUnknownError, run_adb_swipe


def _swipe_commands(mock_run) -> list[list[str]]:
    return [call.args[0] for call in mock_run.call_args_list if "swipe" in call.args[0]]


def test_swipe_does_not_resend_when_adb_reports_failure_after_delivery():
    """端末が入力を受けてもADBが失敗を返す場合、重複入力せず再観測して停止。"""
    delivered = []
    observations = []

    def fake_run(command, **kwargs):
        delivered.append(command)
        raise subprocess.CalledProcessError(1, command)

    def guard():
        observations.append("observed")
        return True

    with patch("scripts.labyrinth_route.subprocess.run", side_effect=fake_run), \
         patch("scripts.labyrinth_route.ensure_adb_connection"), \
         patch("scripts.labyrinth_route.AdbCoordinateScaler") as scaler:
        scaler.return_value.point.side_effect = lambda point: point
        with pytest.raises(SwipeOutcomeUnknownError, match="送信結果不明.*再送しません") as error:
            run_adb_swipe((250, 400), (1100, 400), serial="127.0.0.1:5555",
                          healthcheck=True, screen_guard=guard)
    assert len(delivered) == 1
    assert observations == ["observed", "observed"]
    assert isinstance(error.value.__cause__, subprocess.CalledProcessError)


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


@pytest.mark.parametrize("observation", [False, RuntimeError("観測失敗")])
def test_swipe_stops_when_reobservation_fails(observation):
    """送信失敗後の画面が不明でも、追加の入力を発行しない。"""
    guard_calls = []

    def guard():
        guard_calls.append(True)
        if len(guard_calls) == 2:
            if isinstance(observation, Exception):
                raise observation
            return observation
        return True

    with patch("scripts.labyrinth_route.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "adb")) as mock_run, \
         patch("scripts.labyrinth_route.ensure_adb_connection"), \
         patch("scripts.labyrinth_route.AdbCoordinateScaler") as scaler:
        scaler.return_value.point.side_effect = lambda point: point
        with pytest.raises(SwipeOutcomeUnknownError, match="安全停止.*送信結果不明"):
            run_adb_swipe((250, 400), (1100, 400), serial="127.0.0.1:5555",
                          healthcheck=True, screen_guard=guard)
    assert len(_swipe_commands(mock_run)) == 1
    assert len(guard_calls) == 2


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


@pytest.mark.parametrize("failed_swipe", [1, 3])
def test_guild_scan_propagates_unknown_swipe_outcome(tmp_path, monkeypatch, capsys, failed_swipe):
    """スクロールバー・ページ走査のどちらでも不明送信後に追加入力しない。"""
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "labyrinth_target_policy.json").write_text(
        json.dumps({"target_bosses": {"3": "boss3", "5": "boss5"}}), encoding="utf-8"
    )
    (configs / "labyrinth_guild_starting_members.json").write_text(
        json.dumps({"selection_policy": {"preferred_guilds": ["guild"]},
                    "guilds": {"guild": {}}}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["live", "--execute", "--attempts", "1",
                                  "--area3-boss", "boss3", "--area5-boss", "boss5"])
    probe = Mock()
    probe.observe_screen.return_value = "guild_select"
    probe.target_visible.return_value = False
    probe.targets = {}
    monkeypatch.setattr(cli, "load_template_probe_config", lambda *args: probe)
    monkeypatch.setattr(cli, "AdbScreenCapture",
                        lambda **kwargs: Mock(capture=lambda path: path.write_bytes(b"not a png")))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    tap = Mock(side_effect=AssertionError("unexpected tap"))
    monkeypatch.setattr(cli, "run_adb_coordinate_sequence", tap)
    swipe = Mock(side_effect=[None] * (failed_swipe - 1) + [SwipeOutcomeUnknownError("unknown delivery")])
    monkeypatch.setattr(cli, "run_adb_swipe", swipe)

    assert cli.main() == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == "safety_stop"
    assert "SwipeOutcomeUnknownError:unknown delivery" in result["reason"]
    assert swipe.call_count == failed_swipe
    tap.assert_not_called()


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
