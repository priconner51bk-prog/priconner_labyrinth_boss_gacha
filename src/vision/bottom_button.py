"""共通下段ボタン位置のOCRユーティリティ。"""

from __future__ import annotations

from typing import Iterable


# 1280x720のゲーム画面では、主要な確定・キャンセルボタンがこのY帯にある。
BOTTOM_BUTTON_Y_RANGE = (560, 710)


def bottom_button_center(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    """OCR bboxから下段ボタンの中心を返す。X幅は文字列ごとに変わる。"""
    x1, y1, x2, y2 = bbox
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def is_bottom_button(bbox: tuple[int, int, int, int], *, y_range: tuple[int, int] = BOTTOM_BUTTON_Y_RANGE) -> bool:
    """bbox中心が共通の下段ボタンY帯にあるか判定する。"""
    _, center_y = bottom_button_center(bbox)
    return y_range[0] <= center_y <= y_range[1]


def find_bottom_button(lines: Iterable[object], label: str) -> list[object]:
    """指定文字列を含む下段ボタン候補を返す。"""
    result = []
    for line in lines:
        text = getattr(line, "text", "")
        bbox = getattr(line, "bbox", None)
        confidence = float(getattr(line, "confidence", 0.0))
        if confidence >= 0.70 and bbox and label in text and is_bottom_button(tuple(bbox)):
            result.append(line)
    return result
