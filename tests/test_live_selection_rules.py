"""実機ガチャで再発した選択・画面分類を固定データで検証する。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boss_gacha import BossGachaController, BossGachaPolicy
from boss_gacha.guild_selection import scan_directions


def test_target_pair_is_match_and_other_pair_is_retry():
    policy = BossGachaPolicy(
        {"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}, max_attempts=1000
    )
    controller = BossGachaController(policy)
    assert controller.evaluate({"3": "ベノムサラマンドラ", "5": "キマイラ"})["status"] == "withdraw_and_retry"
    assert controller.evaluate({"3": "ベノムサラマンドラ", "5": "ゴブリンロード"})["status"] == "matched"


def test_policy_accepts_exactly_1000_attempts():
    policy = BossGachaPolicy({"3": "対象"}, max_attempts=1000)
    controller = BossGachaController(policy)
    for _ in range(999):
        result = controller.evaluate({"3": "別"})
    assert result["status"] == "withdraw_and_retry"
    assert controller.evaluate({"3": "別"})["status"] == "max_attempts"


def test_all_configured_guilds_are_reachable_by_fixed_order_scan():
    import json

    config = json.loads(
        (ROOT / "configs" / "labyrinth_guild_starting_members.json").read_text(encoding="utf-8")
    )
    guilds = list(config["guilds"])
    assert len(guilds) == 14
    for start in range(len(guilds)):
        for target in range(len(guilds)):
            directions = scan_directions(
                len(guilds), current_index=start, target_index=target
            )
            position = start
            for swipe_start, swipe_end in directions:
                position += 1 if swipe_end[0] < swipe_start[0] else -1
            assert position == target


def test_all_configured_guilds_have_ascii_card_templates():
    """全ギルドが実機カードテンプレートへ対応付けられていることを確認する。"""
    import json

    config = json.loads(
        (ROOT / "configs" / "labyrinth_guild_starting_members.json").read_text(encoding="utf-8")
    )
    names = {
        "美食殿": "mishoku", "トゥインクルウィッシュ": "twinkle_wish",
        "サレンディア救護院": "salendia", "王宮騎士団（NIGHTMARE）": "royal_nightmare",
        "ラビリンス": "labyrinth", "カルミナ": "carmina",
        "ディアボロス": "diabolos", "牧場（エリザベスパーク）": "ranch_elizabeth",
        "メルクリウス財団": "mercurius", "トワイライトキャラバン": "twilight_caravan",
        "リトルリリカル": "little_lyrical", "自警団（カォン）": "kaon",
        "フォレスティエ": "forestier", "ルーセント学院": "lucent_academy",
    }
    assert set(config["guilds"]) == set(names)
    assert all((ROOT / "data/template_migration/templates/guild_names" / f"{slug}.png").is_file() for slug in names.values())


