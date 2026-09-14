from types import SimpleNamespace

from boss_gacha.guild_selection import guild_button_point, scan_directions


def row(text, x, y, confidence=.9):
    return SimpleNamespace(text=text, confidence=confidence, bbox=(x-70, y, x+70, y+20))


def test_multiline_name_and_neighbor_card():
    lines = [row("トゥインクル", 550, 435), row("ウィッシュ", 550, 470), row("美食殿", 190, 450)]
    assert guild_button_point(lines, "トゥインクルウィッシュ") == (550, 565)


def test_does_not_join_neighbor_cards_or_low_confidence():
    assert guild_button_point([row("トゥインクル", 190, 435), row("ウィッシュ", 550, 470)], "トゥインクルウィッシュ") is None
    assert guild_button_point([row("美食殿", 190, 450, .3)], "美食殿") is None


def test_ambiguous_duplicate_and_partial_name_rejected():
    assert guild_button_point([row("美食殿", 190, 450), row("美食殿", 550, 450)], "美食殿") is None
    assert guild_button_point([row("トゥインクル", 550, 435)], "トゥインクルウィッシュ") is None


def test_scan_reaches_every_card_from_every_start_at_one_card_per_swipe():
    for initial in range(14):
        position = initial
        seen = {position}
        for start, end in scan_directions(14):
            position = max(0, min(13, position + (-1 if end[0] > start[0] else 1)))
            seen.add(position)
        assert seen == set(range(14))


def test_scan_starts_by_revealing_right_side_from_left_edge():
    assert scan_directions(14)[0] == ((1100, 400), (250, 400))
