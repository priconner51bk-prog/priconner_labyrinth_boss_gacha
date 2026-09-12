from unittest.mock import patch

from scripts.live_cli_utils import advance_error_to_title, advance_startup_screen, relaunch_game_from_title


def test_relaunch_game_from_title_taps_touch_to_start_position():
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch("scripts.live_cli_utils.subprocess.run", side_effect=run), patch("scripts.live_cli_utils.time.sleep"):
        result = relaunch_game_from_title("emulator-5554")

    assert result["ok"] is True
    assert calls[-1][-2:] == ["640", "670"]


def test_startup_waits_then_taps_title_once_and_accepts_known_screen():
    screens = iter(["splash", "launching", "title", "launching", "labyrinth_top"])
    taps = []
    clock = iter([0.0, 0.0, 0.2, 0.4, 0.6, 0.8])

    result = advance_startup_screen(
        lambda: next(screens),
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"labyrinth_top"},
        monotonic=lambda: next(clock),
        sleep=lambda _: None,
    )

    assert result["ok"] is True
    assert result["title_tap_count"] == 1
    assert result["screen_sequence"] == ["splash", "launching", "title", "launching", "labyrinth_top"]
    assert taps == ["tap"]


def test_startup_stops_when_title_reappears_without_second_tap():
    screens = iter(["title", "launching", "title"])
    taps = []

    result = advance_startup_screen(
        lambda: next(screens),
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"labyrinth_top"},
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )

    assert result["ok"] is False
    assert result["stop_reason"] == "title_reappeared"
    assert result["title_tap_count"] == 1
    assert taps == ["tap"]


def test_startup_stops_on_unknown_screen_without_tap():
    taps = []

    result = advance_startup_screen(
        lambda: None,
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"labyrinth_top"},
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )

    assert result["ok"] is False
    assert result["stop_reason"] == "unknown_startup_screen"
    assert taps == []


def test_startup_tolerates_blank_transition_after_known_splash():
    screens = iter(["startup_splash", None, "title", None, "labyrinth_top"])
    taps = []

    result = advance_startup_screen(
        lambda: next(screens),
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"labyrinth_top"},
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )

    assert result["ok"] is True
    assert result["title_tap_count"] == 1
    assert taps == ["tap"]


def test_error_to_title_taps_once_and_accepts_title():
    screens = iter(["startup_error", None, "title"])
    taps = []

    result = advance_error_to_title(
        lambda: next(screens), lambda: True,
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"title"}, monotonic=lambda: 0.0, sleep=lambda _: None,
    )

    assert result["ok"] is True
    assert result["title_button_tap_count"] == 1
    assert result["screen_sequence"] == ["startup_error", None, "title"]
    assert taps == ["tap"]


def test_error_to_title_rejects_unconfirmed_button_without_input():
    taps = []

    result = advance_error_to_title(
        lambda: "startup_error", lambda: False,
        lambda: taps.append("tap") or {"ok": True}, known_screens={"title"},
    )

    assert result["ok"] is False
    assert result["stop_reason"] == "title_button_not_confirmed"
    assert taps == []


def test_error_to_title_does_not_tap_twice_when_error_reappears():
    screens = iter(["startup_error", "startup_error"])
    taps = []

    result = advance_error_to_title(
        lambda: next(screens), lambda: True,
        lambda: taps.append("tap") or {"ok": True},
        known_screens={"title"}, monotonic=lambda: 0.0, sleep=lambda _: None,
    )

    assert result["ok"] is False
    assert result["stop_reason"] == "startup_error_reappeared"
    assert result["title_button_tap_count"] == 1
    assert taps == ["tap"]


def test_error_to_title_rejects_wrong_initial_screen_without_input():
    taps = []

    result = advance_error_to_title(
        lambda: "notice", lambda: True,
        lambda: taps.append("tap") or {"ok": True}, known_screens={"title"},
    )

    assert result["ok"] is False
    assert result["stop_reason"] == "startup_error_not_confirmed"
    assert taps == []
