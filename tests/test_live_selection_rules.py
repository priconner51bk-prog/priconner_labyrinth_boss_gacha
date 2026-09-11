"""実機ガチャで再発した選択・画面分類を固定データで検証する。"""

from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boss_gacha import BossGachaController, BossGachaPolicy
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
