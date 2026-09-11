"""実機ガチャで再発した選択・画面分類を固定データで検証する。"""

from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boss_gacha import BossGachaController, BossGachaPolicy
from boss_gacha.guild_selection import scan_directions
from vision.template_screen_probe import load_template_probe_config


class _NoCapture:
    def capture(self, _path):
        raise AssertionError("固定画像テストではADB取得を呼び出さない")


def test_departure_bonus_is_not_misclassified_as_withdraw_confirm():
    probe = load_template_probe_config(ROOT / "configs" / "live_screen_templates.json", _NoCapture())
    image_path = ROOT / "data" / "observations" / "live" / "task_boss_gacha_withdraw_confirm_ocr.png"
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    assert probe._classify(image) == "bonus"


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
    assert all((ROOT / "data/template_migration/templates/guild_cards" / f"{slug}.png").is_file() for slug in names.values())


def test_collected_guild_templates_match_their_source_captures():
    import cv2

    cases = [
        ("guild_select_current_capture.png", ["mishoku", "twinkle_wish", "salendia"]),
        ("guild_select_current_capture_02.png", ["royal_nightmare", "labyrinth", "carmina"]),
        ("guild_select_current_capture_03.png", ["diabolos", "ranch_elizabeth", "mercurius"]),
        ("guild_select_current_capture_04.png", ["twilight_caravan", "little_lyrical", "kaon"]),
        ("guild_select_current_capture_05.png", [("kaon", 0), ("forestier", 2), ("lucent_academy", 3)]),
    ]
    for source_name, template_names in cases:
        source = cv2.imread(str(ROOT / "data/observations/live" / source_name))
        assert source is not None
        for index, item in enumerate(template_names):
            if isinstance(item, tuple):
                template_name, card_index = item
            else:
                template_name, card_index = item, index
            template = cv2.imread(
                str(ROOT / "data/template_migration/templates/guild_cards" / f"{template_name}.png")
            )
            assert template is not None
            # カード列はスワイプ途中の端数で数pxずれるため、画面全体から
            # 最良位置を探し、固定座標への依存を避ける。
            score = float(cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED).max())
            assert score >= 0.82, (source_name, template_name, score)
