import json

import pytest

from boss_gacha import BossGachaController, BossGachaPolicy


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


@pytest.mark.parametrize(
    "allowed",
    [
        {"3": ["対象A"]},
        {"3": ["対象A"], "5": ["対象B"], "7": ["対象C"]},
        {"3": ["対象A"], "5": []},
        {"3": ["対象A"], "5": [""]},
        {"3": ["対象A"], "5": ["   "]},
        {"3": ["対象A"], "5": "対象B"},
    ],
)
def test_policy_rejects_invalid_allowed_bosses(allowed):
    with pytest.raises(ValueError, match="allowed_bosses"):
        BossGachaPolicy({"3": "対象A", "5": "対象B"}, allowed_bosses=allowed)


def test_policy_accepts_multiple_allowed_bosses_for_every_area():
    policy = BossGachaPolicy(
        {"3": "対象A", "5": "対象B"},
        allowed_bosses={"3": ["対象A", "代替A"], "5": ["対象B", "代替B"]},
    )
    controller = BossGachaController(policy)
    assert controller.evaluate({"3": "代替A", "5": "代替B"})["status"] == "matched"
    assert controller.evaluate({"3": "代替A", "5": "対象外"})["status"] == "withdraw_and_retry"


@pytest.mark.parametrize("allowed", [None, {"3": ["対象A"]}, {"3": ["対象A"], "5": []}])
def test_policy_from_json_rejects_invalid_allowed_bosses(tmp_path, allowed):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"target_bosses": {"3": "対象A", "5": "対象B"},
                                "allowed_bosses": allowed}), encoding="utf-8")
    with pytest.raises(ValueError, match="allowed_bosses"):
        BossGachaPolicy.from_json(path)
