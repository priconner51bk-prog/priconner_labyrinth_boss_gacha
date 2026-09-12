import pytest

from boss_gacha.name_matching import match_boss_name


@pytest.mark.parametrize("text,expected", [
    ("", None), ("   ", None), ("ガーゴイル", None),
    ("ダーク ガーゴイル", "ダークガーゴイル"),
    ("ジークガーゴイル", "ダークガーゴイル"),
    ("ダークガーゴイル ゴブリンロード", None),
])
def test_only_complete_unambiguous_names_match(text, expected):
    assert match_boss_name(text, {
        "ダークガーゴイル": {"ダークガーゴイル", "ジークガーゴイル"},
        "ゴブリンロード": {"ゴブリンロード"},
    }) == expected
