from boss_gacha import BossGachaController, BossGachaPolicy
import pytest


def test_policy_rejects_more_than_one_thousand_attempts():
    with pytest.raises(ValueError, match="<= 1000"):
        BossGachaPolicy({"3": "対象"}, max_attempts=1001)


def test_controller_is_independent_and_retries_until_match():
    controller = BossGachaController(BossGachaPolicy({"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}, 2))
    assert controller.evaluate({"3": "別", "5": "別"})["status"] == "withdraw_and_retry"
    assert controller.evaluate({"3": "別", "5": "別"})["status"] == "max_attempts"


def test_controller_reports_match():
    controller = BossGachaController(BossGachaPolicy({"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}))
    assert controller.evaluate({3: "ベノムサラマンドラ", 5: "ゴブリンロード"})["status"] == "matched"
