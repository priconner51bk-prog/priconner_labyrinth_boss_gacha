"""ADBキャプチャを使った軽量な画面・対象表示プローブ。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Mapping
import json

import cv2


@dataclass(frozen=True)
class TemplateRegion:
    image: str | Path
    left: int
    top: int
    right: int
    bottom: int


class AdbTemplateScreenProbe:
    """画面全体を解析せず、登録済みROIの一致だけで判定する。"""

    def __init__(self, capture, *, screens: Mapping[str, TemplateRegion], targets: Mapping[str, TemplateRegion], threshold: float = 0.82):
        if not screens or not targets:
            raise ValueError("screens and targets must not be empty")
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self.capture = capture
        self.screens = dict(screens)
        self.targets = dict(targets)
        self.threshold = threshold
        self._last_image = None
        self._template_cache = {}

    _SCREEN_TARGETS = {
        "labyrinth_top": {"出発", "挑戦中"}, "quest_menu": {"ラビリンス"},
        "guild_select": {"フォレスティエ", "美食殿"}, "guild_confirm": {"ギルド選択確認"}, "bonus": {"閉じる", "出発ボーナス閉じる"},
        "boss_detail": {"閉じる"}, "character_join": {"キャラ加入閉じる"},
        "move_confirm": {"移動先確認OK"},
        "event_confirm": {"イベント移動OK"},
        "event_battle_choice": {"イベント通常選択"},
        "item_reward": {"アイテム報酬閉じる", "閉じる", "出発ボーナス閉じる"},
        "relic_choice": {"遺物選択"},
        "shop": {"ショップ購入1", "ショップ購入2", "ショップ購入3"},
        "shop_purchase_confirm": {"購入確認OK"},
        "shop_purchase_complete": {"購入完了OK"},
        "shop_exit_confirm": {"ショップ終了OK"},
        "battle_tile_normal": {"挑戦する"},
        "battle_party": {"バトル開始"},
        "battle_party_ready": {"EX装備"}, "battle_victory": {"勝利次へ"}, "battle_reward": {"報酬次へ"},
        "character_bonus": {"キャラボーナス選択"},
        "ex_equipment": {"おまかせ装備"}, "ex_auto_dialog": {"EX自動設定OK"},
        "ex_auto_dialog": {"EX自動設定OK"}, "ex_equipment_conflict": {"EX装備競合警告", "EX競合キャンセル"},
        "battle_victory": {"勝利次へ"},
        "initial_char": {"マップ"}, "boss_map": {"左BOSS", "右BOSS", "撤退する"},
        "boss_detail": {"閉じる"}, "withdraw_confirm": {"撤退確認OK"},
    }

    def _capture(self):
        path = Path(tempfile.gettempdir()) / "labyrinth_probe_current.png"
        self.capture.capture(path)
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError("ADB画面を読み込めません")
        self._last_image = image
        return image

    def _score(self, current, reference, region: TemplateRegion) -> float:
        c = current[region.top:region.bottom, region.left:region.right]
        key = str(region.image)
        rimg = self._template_cache.get(key)
        if rimg is None:
            rimg = cv2.imread(key, cv2.IMREAD_GRAYSCALE)
            if rimg is not None:
                self._template_cache[key] = rimg
        if rimg is None:
            raise FileNotFoundError(region.image)
        r = rimg[region.top:region.bottom, region.left:region.right]
        if c.shape != r.shape or c.size == 0:
            return 0.0
        # Normalized correlation is undefined for flat ROIs and OpenCV
        # reports a misleading perfect match.  Require exact equality there
        # so a common solid/blank button region cannot classify a screen.
        if float(c.std()) == 0.0 or float(r.std()) == 0.0:
            return 1.0 if bool((c == r).all()) else 0.0
        result = cv2.matchTemplate(c, r, cv2.TM_CCOEFF_NORMED)
        return float(result[0, 0])

    def _classify(self, image) -> str | None:
        # Conflict warning is a safety-critical override: it must win over
        # the visually similar base EX-equipment screen.
        conflict = self.screens.get("ex_equipment_conflict")
        if conflict is not None and self._score(image, conflict, conflict) >= self.threshold:
            return "ex_equipment_conflict"
        # 画面固有ボタンの存在は、動的なキャラクター画像より強い識別子。
        # 優先順位は遷移の入口から出口へ固定する。
        # ボス詳細は「閉じる」ボタンが報酬ダイアログと共通のため、先に
        # 固定ヘッダーROIで判定して誤分類を防ぐ。
        boss_detail = self.screens.get("boss_detail")
        if boss_detail is not None and self._score(image, boss_detail, boss_detail) >= self.threshold:
            return "boss_detail"
        for screen_id, label in (("guild_select", "フォレスティエ"), ("quest_menu", "ラビリンス"),
                                 ("labyrinth_top", "挑戦中"), ("labyrinth_top", "出発"),
                                 ("boss_map", "左BOSS"), ("boss_map", "右BOSS"),
                                 # 報酬ダイアログは古い全画面テンプレートと
                                 # 撤退確認背景が似るため、固有の閉じるボタンを
                                 # 撤退確認より先に判定する。
                                 ("bonus", "出発ボーナス閉じる"),
                                 ("item_reward", "アイテム報酬閉じる"),
                                 # 終了確認は移動確認と背景が似るため先に判定する。
                                 ("withdraw_confirm", "撤退確認OK"),
                                 ("move_confirm", "移動先確認OK"),
                                 ("event_confirm", "イベント移動OK"),
                                 ("event_battle_choice", "イベント通常選択"),
                                 ("boss_detail", "閉じる"),
                                 ("item_reward", "アイテム報酬閉じる"),
                                 ("relic_choice", "遺物選択"),
                                 ("shop_purchase_confirm", "購入確認OK"),
                                 ("shop_purchase_complete", "購入完了OK"),
                                 ("shop_exit_confirm", "ショップ終了OK"),
                                 ("shop", "ショップ購入1"),
                                 ("battle_tile_normal", "挑戦する"),
                                 ("battle_party", "バトル開始"),
                                 ("battle_party_ready", "EX装備"),
                                 ("ex_equipment", "おまかせ装備"),
                                 ("ex_auto_dialog", "EX自動設定OK"),
                                 ("ex_equipment_conflict", "EX装備競合警告"),
                                 ("ex_equipment_conflict", "EX競合キャンセル"),
                                 ("battle_victory", "勝利次へ"),
                                 ("battle_reward", "報酬次へ"),
                                 ("character_bonus", "キャラボーナス選択"),
                                 ("guild_confirm", "ギルド選択確認"),
                                 ("initial_char", "マップ")):
            # 「閉じる」は複数のダイアログで共通するため、ボタンROI
            # だけでは画面を確定しない。画面固有ヘッダー（上記の
            # boss_detail等）で既に確定した場合のみ利用する。
            if label == "閉じる":
                continue
            region = self.targets.get(label)
            if region is not None and self._score(image, region, region) >= self.threshold:
                return screen_id
        scores = {name: self._score(image, ref, ref) for name, ref in self.screens.items()}
        name, score = max(scores.items(), key=lambda item: item[1])
        return name if score >= self.threshold else None

    def observe_screen(self) -> str | None:
        return self._classify(self._capture())

    def target_visible(self, label: str) -> bool:
        region = self.targets.get(label)
        if region is None:
            return False
        image = self._last_image if self._last_image is not None else self._capture()
        screen = self._classify(image)
        if screen is None or label not in self._SCREEN_TARGETS.get(screen, set()):
            return False
        return self._score(image, region, region) >= self.threshold


def load_template_probe_config(path: str | Path, capture):
    """JSON設定から実機用テンプレートプローブを生成する。"""
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    root = source.parent.parent

    def regions(key: str) -> dict[str, TemplateRegion]:
        result = {}
        for name, value in data.get(key, {}).items():
            image = Path(value["image"])
            if not image.is_absolute():
                image = root / image
            result[name] = TemplateRegion(image, *[int(value[field]) for field in ("left", "top", "right", "bottom")])
        return result

    screen_regions = regions("screens")
    target_regions = regions("targets")
    missing = sorted({str(region.image) for region in (*screen_regions.values(), *target_regions.values()) if not region.image.is_file()})
    if missing:
        raise FileNotFoundError(f"画面テンプレートが未配置です: {missing[0]}")
    return AdbTemplateScreenProbe(capture, screens=screen_regions, targets=target_regions,
                                  threshold=float(data.get("threshold", 0.82)))

