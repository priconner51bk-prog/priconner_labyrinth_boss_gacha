from boss_gacha import BossGachaPhaseCoordinator, GuardedLiveActions
from scripts.labyrinth_route import AdbScreenAdapter


def test_guarded_action_checks_screen_and_target_before_tap():
    calls = []
    flow = GuardedLiveActions(
        observe_screen=lambda: "labyrinth_top",
        target_visible=lambda label: calls.append(f"visible:{label}") or True,
        tap=lambda label: calls.append(f"tap:{label}"),
    )
    result = flow.tap_if_expected("labyrinth_top", "出発")
    assert result.ok is True
    assert calls == ["visible:出発", "tap:出発"]


def test_guarded_action_never_taps_wrong_screen():
    calls = []
    flow = GuardedLiveActions(
        observe_screen=lambda: "story",
        target_visible=lambda label: calls.append(label) or True,
        tap=lambda label: calls.append(f"tap:{label}"),
    )
    result = flow.tap_if_expected("labyrinth_top", "出発")
    assert result.ok is False
    assert "想定画面外" in result.reason
    assert calls == []


def test_phase_coordinator_checks_expected_screen_without_duplicate_tap():
    calls = []
    actions = GuardedLiveActions(
        observe_screen=lambda: "labyrinth_top",
        target_visible=lambda label: calls.append(f"visible:{label}") or True,
        tap=lambda label: calls.append(f"tap:{label}"),
    )
    coordinator = BossGachaPhaseCoordinator(actions)
    assert coordinator.guard_phase("begin_attempt") is True
    assert calls == ["visible:出発"]


def test_phase_coordinator_boss_read_starts_at_initial_character_screen():
    actions = GuardedLiveActions(
        observe_screen=lambda: "initial_char",
        target_visible=lambda label: label == "マップ",
        tap=lambda label: None,
    )
    assert BossGachaPhaseCoordinator(actions).guard_phase("read_boss_names") is True


def test_adb_adapter_rejects_forbidden_return_controls_before_input():
    adapter = AdbScreenAdapter(
        coordinates={"帰還する": (1, 1), "終了する": (2, 2)},
    )
    for label in ("帰還する", "終了する"):
        try:
            adapter.click(label)
        except RuntimeError as exc:
            assert "禁止操作" in str(exc)
        else:
            raise AssertionError(f"forbidden control was not rejected: {label}")
