"""ADBキャプチャを使った軽量な画面・対象表示プローブ。"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import cv2
import numpy as np


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
        self._last_color_image = None
        self._template_cache = {}

    _SCREEN_TARGETS: ClassVar[dict[str, set[str]]] = {
        "title": {"Touch To Start"},
        "startup_error": {"タイトルへ"},
        "home": {"クエスト"},
        "notice": {"お知らせウィンドウタイトル", "お知らせ閉じる"},
        "labyrinth_top": {"出発", "挑戦中"}, "quest_menu": {"ラビリンス"},
        "guild_select": {"フォレスティエ", "美食殿"}, "guild_confirm": {"ギルド選択確認", "ギルド選択キャンセル"}, "bonus": {"閉じる", "出発ボーナス閉じる"},
        "boss_detail": {"閉じる"}, "character_join": {"閉じる", "キャラ加入閉じる"},
        "item_reward": {"アイテム報酬閉じる", "閉じる", "出発ボーナス閉じる"},
        "initial_char": {"マップ"}, "boss_map": {"左BOSS", "右BOSS", "撤退する"},
        "withdraw_confirm": {"撤退確認OK", "撤退確認キャンセル"},
    }
    # Title artwork animates behind the Touch To Start text. On the installed
    # 12.7.1 screen the stable text scores 0.936 against its ROI, while the
    # global 0.95 threshold rejects it. Keep this lower threshold scoped to
    # that single screen and target; all other navigation remains unchanged.
    _SCREEN_THRESHOLDS: ClassVar[dict[str, float]] = {"title": 0.90, "network_loading": 0.80}
    _TARGET_THRESHOLDS: ClassVar[dict[str, float]] = {"Touch To Start": 0.90}

    def _capture(self):
        path = Path(tempfile.gettempdir()) / "labyrinth_probe_current.png"
        self.capture.capture(path)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("ADB画面を読み込めません")
        self._last_color_image = image
        self._last_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image

    def _score(self, current, reference, region: TemplateRegion) -> float:
        if current.ndim == 3:
            current = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        c = current[region.top:region.bottom, region.left:region.right]
        key = str(region.image)
        rimg = self._template_cache.get(key)
        if rimg is None:
            rimg = cv2.imread(key, cv2.IMREAD_GRAYSCALE)
            if rimg is not None:
                self._template_cache[key] = rimg
        if rimg is None:
            # 実機由来のスクリーンテンプレートは環境依存で、fresh clone
            # 直後に全件が存在するとは限らない。欠落は一致なしとして
            # 扱い、呼出し側の screen_not_recognized 安全停止へ委譲する。
            return 0.0
        # Cropped ROI templates are stored at their natural origin (0, 0).
        # Full-screen legacy templates keep using the configured coordinates.
        expected_shape = (region.bottom - region.top, region.right - region.left)
        if rimg.shape[:2] == expected_shape:
            r = rimg
        else:
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

    def _matches_shifted_guild_select_header(self, image) -> bool:
        """Match the guild prompt across its animated background.

        The guild-select banner text is stable, but its translucent background
        contains moving art. A fixed-ROI grayscale correlation can therefore
        fail even while the prompt is plainly visible. Edge matching tolerates
        those background changes and a small horizontal alignment offset.
        """
        region = self.screens.get("guild_select")
        if region is None or getattr(image, "ndim", 0) != 3:
            return False
        key = str(region.image)
        cache = getattr(self, "_template_cache", {})
        template = cache.get(key)
        if template is None:
            template = cv2.imread(key, cv2.IMREAD_GRAYSCALE)
            if template is None:
                return False
            cache[key] = template
            self._template_cache = cache
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        left = max(0, region.left - 130)
        top = max(0, region.top - 18)
        right = min(w, region.right + 130)
        bottom = min(h, region.bottom + 18)
        search = gray[top:bottom, left:right]
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            return False
        edges = cv2.Canny(search, 50, 150)
        template_edges = cv2.Canny(template, 50, 150)
        scores = cv2.matchTemplate(edges, template_edges, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(scores)
        match_left = left + point[0]
        match_top = top + point[1]
        return bool(
            score >= 0.88
            and region.left - 16 <= match_left <= region.right + 140
            and abs(match_top - region.top) <= 10
        )

    @staticmethod
    def _has_server_error_dialog_layout(image) -> bool:
        """Recognize the server-error variant with the same title-return button.

        The game uses a different header string for server error 201 than for
        the usual connection timeout.  Both dialogs have the same fixed blue
        header, white message body, and title-return button.  Requiring all
        three regions avoids treating an unrelated screen with a similar
        button as a recoverable network error.
        """
        if image is None or getattr(image, "ndim", 0) != 3:
            return False
        height, width = image.shape[:2]
        if width < 958 or height < 450:
            return False
        header = image[171:218, 325:958]
        body = image[220:450, 325:958]
        hsv = cv2.cvtColor(header, cv2.COLOR_BGR2HSV)
        blue_ratio = float(
            ((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 135) & (hsv[:, :, 1] > 80)).mean()
        )
        white_ratio = float((body.min(axis=2) > 210).mean())
        return blue_ratio >= 0.50 and white_ratio >= 0.80

    def _classify(self, image) -> str | None:
        notice_title = self.targets.get("お知らせウィンドウタイトル")
        notice_close = self.targets.get("お知らせ閉じる")
        if (notice_title is not None and notice_close is not None
                and self._score(image, notice_title, notice_title) >= self.threshold
                and self._score(image, notice_close, notice_close) >= self.threshold):
            return "notice"
        startup_error = self.screens.get("startup_error")
        startup_error_button = self.targets.get("タイトルへ")
        if startup_error is not None and startup_error_button is not None:
            button_confirmed = self._score(image, startup_error_button, startup_error_button) >= self.threshold
            header_confirmed = self._score(image, startup_error, startup_error) >= self.threshold
            if button_confirmed and (header_confirmed or self._has_server_error_dialog_layout(image)):
                return "startup_error"
        if self._is_startup_splash(image):
            return "startup_splash"
        network_loading = self.screens.get("network_loading")
        if (network_loading is not None
                and self._score(image, network_loading, network_loading)
                >= self._SCREEN_THRESHOLDS["network_loading"]):
            return "network_loading"

        # Conflict warning is a safety-critical override: it must win over
        # the visually similar base EX-equipment screen.
        # 画面固有ボタンの存在は、動的なキャラクター画像より強い識別子。
        # 優先順位は遷移の入口から出口へ固定する。
        # ボス詳細は「閉じる」ボタンが報酬ダイアログと共通のため、先に
        # 固定ヘッダーROIで判定して誤分類を防ぐ。
        boss_detail = self.screens.get("boss_detail")
        if boss_detail is not None and self._score(image, boss_detail, boss_detail) >= self.threshold:
            return "boss_detail"
        if self._matches_shifted_guild_select_header(image):
            return "guild_select"
        # Screen templates are authoritative headers; check them before
        # dynamic button templates (a card can contain a visually identical
        # button ROI).
        for screen_id, reference in self.screens.items():
            if screen_id in {"boss_detail", "startup_error"}:
                continue
            threshold = self._SCREEN_THRESHOLDS.get(screen_id, self.threshold)
            if self._score(image, reference, reference) >= threshold:
                return screen_id
        for screen_id, label in (("guild_select", "フォレスティエ"), ("quest_menu", "ラビリンス"),
                                 ("labyrinth_top", "挑戦中"), ("labyrinth_top", "出発"),
                                 ("home", "クエスト"),
                                 ("boss_map", "左BOSS"), ("boss_map", "右BOSS"),
                                 # 報酬ダイアログは古い全画面テンプレートと
                                 # 撤退確認背景が似るため、固有の閉じるボタンを
                                 # 撤退確認より先に判定する。
                                 ("bonus", "出発ボーナス閉じる"),
                                 ("item_reward", "アイテム報酬閉じる"),
                                 # 終了確認は移動確認と背景が似るため先に判定する。
                                 ("withdraw_confirm", "撤退確認OK"),
                                 ("boss_detail", "閉じる"),
                                 ("item_reward", "アイテム報酬閉じる"),
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
        scores = {name: self._score(image, ref, ref) for name, ref in self.screens.items()
                  if name != "startup_error"}
        name, score = max(scores.items(), key=lambda item: item[1])
        return name if score >= self.threshold else None

    @staticmethod
    def _is_notice_screen(image) -> bool:
        """Recognize the stable amber notice header used during startup."""
        if image is None or getattr(image, "ndim", 0) != 3:
            return False
        h, w = image.shape[:2]
        if h < 100 or w < 500:
            return False
        band = image[max(0, int(h*.04)):int(h*.11), int(w*.03):int(w*.97)]
        mean = band.reshape(-1, 3).mean(axis=0)
        return bool(mean[0] > 150 and mean[1] > 90 and mean[2] < 130 and (mean[0]-mean[2]) > 50)

    @staticmethod
    def _is_startup_splash(image) -> bool:
        """Recognize a bright screen with a dark centered splash panel."""
        if image is None or getattr(image, "ndim", 0) != 3:
            return False
        h, w = image.shape[:2]
        if h < 500 or w < 800:
            return False
        center = image[int(h*.40):int(h*.60), int(w*.28):int(w*.72)]
        outer = np.concatenate((image[:int(h*.25)].reshape(-1, 3), image[int(h*.75):].reshape(-1, 3)))
        return bool(center.mean() < 70 and outer.mean() > 180)

    def target_center(self, label: str) -> tuple[int, int] | None:
        region = self.targets.get(label)
        if region is None:
            return None
        return ((region.left + region.right) // 2, (region.top + region.bottom) // 2)

    def observe_screen(self) -> str | None:
        return self._classify(self._capture())

    def target_visible(self, label: str) -> bool:
        region = self.targets.get(label)
        if region is None:
            return False
        image = self._last_color_image if self._last_color_image is not None else self._capture()
        screen = self._classify(image)
        if screen is None or label not in self._SCREEN_TARGETS.get(screen, set()):
            return False
        threshold = self._TARGET_THRESHOLDS.get(label, self.threshold)
        return self._score(image, region, region) >= threshold


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
    return AdbTemplateScreenProbe(capture, screens=screen_regions, targets=target_regions,
                                  threshold=float(data.get("threshold", 0.82)))

