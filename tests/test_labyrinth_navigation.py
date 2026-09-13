from scripts import labyrinth_route


def test_navigate_to_screen_returns_ready_when_already_at_target():
    result = labyrinth_route.navigate_to_screen("boss_map", screen_probe=lambda: "boss_map")

    assert result["status"] == "ready"
    assert result["steps"] == 0


def test_navigate_to_screen_stops_when_transition_is_not_defined():
    result = labyrinth_route.navigate_to_screen("boss_map", screen_probe=lambda: "labyrinth_top")

    assert result["status"] == "safety_stop"
    assert result["reason"] == "unconfirmed_transition"
    assert result["screen_id"] == "labyrinth_top"


def test_navigate_to_screen_uses_only_confirmed_initial_character_transition(monkeypatch):
    screen = {"value": "initial_char"}
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])

    monkeypatch.setattr(labyrinth_route, "run_adb_coordinate_sequence", fake_run)
    def probe():
        value = screen["value"]
        if calls:
            value = "boss_map"
        return value

    result = labyrinth_route.navigate_to_screen("boss_map", screen_probe=probe)

    assert result["status"] == "ready"
    assert result["trace"] == ["initial_char", "boss_map"]
    assert calls == [[(90, 640)]]
