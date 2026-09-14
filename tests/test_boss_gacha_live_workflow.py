import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from boss_gacha import (
    BossGachaController,
    BossGachaPolicy,
    LiveBossGachaWorkflow,
    LiveSafetyStop,
)


def test_workflow_reads_left_then_closes_then_right_then_closes():
    events = []
    screens = iter(["guild_select", "guild_confirm", "bonus", "initial_char", "boss_map", "boss_detail", "boss_map", "boss_detail", "boss_map"])

    def tap(screen, label):
        events.append(("tap", screen, label))
        return True

    def wait_screen(screen):
        actual = next(screens)
        events.append(("wait", screen, actual))
        return actual == screen

    def read(side):
        events.append(("ocr", side))
        return {"left": "ベノムサラマンドラ", "right": "ゴブリンロード"}[side]

    workflow = LiveBossGachaWorkflow(tap=tap, wait_screen=wait_screen, read_boss_name=read)
    workflow.begin_attempt()
    assert workflow.read_boss_names() == {"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}
    assert [event for event in events if event[0] == "ocr"] == [("ocr", "left"), ("ocr", "right")]
    assert [event[2] for event in events if event[0] == "tap"][-5:] == ["マップ", "左BOSS", "閉じる", "右BOSS", "閉じる"]


def test_workflow_stops_when_tap_is_rejected():
    workflow = LiveBossGachaWorkflow(tap=lambda *_: False, wait_screen=lambda _: True, read_boss_name=lambda _: "x")
    with pytest.raises(LiveSafetyStop, match="tap_rejected"):
        workflow.begin_attempt()


def test_workflow_stops_when_ocr_is_missing():
    workflow = LiveBossGachaWorkflow(
        tap=lambda *_: True,
        wait_screen=lambda _: True,
        read_boss_name=lambda side: None if side == "left" else "x",
    )
    with pytest.raises(LiveSafetyStop, match="boss_name_missing:left"):
        workflow.read_boss_names()


def test_workflow_does_not_open_right_boss_after_left_mismatch():
    events = []
    workflow = LiveBossGachaWorkflow(
        tap=lambda screen, label: events.append((screen, label)) or True,
        wait_screen=lambda _screen: True,
        read_boss_name=lambda _side: "対象外",
    )
    assert workflow.read_boss_names(target_left=("対象",)) == {"3": "対象外", "_early_reject": "true"}
    assert not any(label == "右BOSS" for _, label in events)


def test_workflow_builds_max_ten_runner():
    workflow = LiveBossGachaWorkflow(tap=lambda *_: True, wait_screen=lambda _: True, read_boss_name=lambda _: "対象外")
    runner = workflow.runner(
        BossGachaController(BossGachaPolicy({"3": "対象"}, max_attempts=10)),
        passport_count=lambda: 1,
        safety_check=lambda: True,
    )
    result = runner.run()
    assert result["status"] == "max_attempts"
    assert result["attempt"] == 10


def test_workflow_can_resume_from_quest_menu():
    events = []
    workflow = LiveBossGachaWorkflow(
        tap=lambda screen, label: events.append((screen, label)) or True,
        wait_screen=lambda screen: True,
        read_boss_name=lambda _: "x",
    )
    workflow.begin_attempt("quest_menu")
    assert events[:2] == [("quest_menu", "ラビリンス"), ("labyrinth_top", "出発")]


def test_workflow_closes_item_reward_after_departure_bonus():
    events = []
    responses = iter(["item_reward", "item_reward", "initial_char"])
    workflow = LiveBossGachaWorkflow(
        tap=lambda screen, label: events.append((screen, label)) or True,
        wait_screen=lambda _screen: next(responses) == _screen,
        read_boss_name=lambda _: "x",
    )
    workflow.begin_attempt("bonus")
    assert events == [("bonus", "閉じる"), ("item_reward", "閉じる")]


def test_workflow_runner_stops_at_target_pair_without_withdraw():
    events = []
    workflow = LiveBossGachaWorkflow(
        tap=lambda screen, label: events.append((screen, label)) or True,
        wait_screen=lambda screen: True,
        read_boss_name=lambda side: "ベノムサラマンドラ" if side == "left" else "ゴブリンロード",
    )
    runner = workflow.runner(
        BossGachaController(BossGachaPolicy({"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}, 10)),
        passport_count=lambda: 1,
        safety_check=lambda: True,
    )
    result = runner.run()
    assert result["status"] == "matched"
    assert result["attempt"] == 1
    assert not any(label == "撤退する" for _, label in events)
