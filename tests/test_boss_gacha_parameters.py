import pytest

from boss_gacha import BossGachaController, BossGachaPolicy


@pytest.mark.parametrize(
    ("max_attempts", "message"),
    [
        (0, "positive"),
        (-1, "positive"),
        (1001, "<= 1000"),
    ],
)
def test_policy_rejects_invalid_attempt_limits(max_attempts, message):
    with pytest.raises(ValueError, match=message):
        BossGachaPolicy({"3": "対象"}, max_attempts=max_attempts)


@pytest.mark.parametrize("target_bosses", [{}, None])
def test_policy_requires_target_bosses(target_bosses):
    with pytest.raises((ValueError, TypeError), match="target_bosses"):
        BossGachaPolicy(target_bosses)


def test_policy_rejects_empty_allowed_bosses():
    with pytest.raises(ValueError, match="allowed_bosses"):
        BossGachaPolicy({"3": "対象"}, allowed_bosses={})


@pytest.mark.parametrize(
    ("observed", "expected_status"),
    [
        ({}, "safety_stop"),
        ({"3": "対象", "5": "別"}, "withdraw_and_retry"),
        ({"3": "対象", "5": "対象5"}, "matched"),
    ],
)
def test_controller_parameterized_outcomes(observed, expected_status):
    policy = BossGachaPolicy(
        {"3": "対象", "5": "対象5"},
        max_attempts=3,
        allowed_bosses={"3": ("対象", "代替"), "5": ("対象5",)},
    )
    result = BossGachaController(policy).evaluate(observed)
    assert result["status"] == expected_status
    assert result["attempt"] == 1


@pytest.mark.parametrize("attempts", [0, 1, 999, 1000])
def test_controller_accepts_non_negative_attempt_initial_values(attempts):
    controller = BossGachaController(BossGachaPolicy({"3": "対象"}), attempts=attempts)
    assert controller.attempts == attempts


def test_controller_rejects_negative_initial_attempts():
    with pytest.raises(ValueError, match="non-negative"):
        BossGachaController(BossGachaPolicy({"3": "対象"}), attempts=-1)


def test_controller_uses_allowed_bosses_for_alternatives():
    controller = BossGachaController(
        BossGachaPolicy({"3": "対象"}, allowed_bosses={"3": ("対象", "代替")})
    )
    assert controller.evaluate({"3": "代替"})["status"] == "matched"


def test_controller_reports_missing_area_before_mismatch():
    result = BossGachaController(BossGachaPolicy({"3": "対象", "5": "対象5"})).evaluate({"3": "対象"})
    assert result == {"status": "safety_stop", "reason": "boss_names_missing", "attempt": 1}
