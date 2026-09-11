"""ラビリンスパスポート枚数の安全なOCR抽出。"""

from __future__ import annotations

import re
from collections.abc import Iterable


_COUNT = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_ANCHORS = ("ラビリンスパスポート", "迷宮パスポート", "パスポート")


def parse_passport_count(lines: Iterable[object]) -> int | None:
    """OCR行からパスポート枚数を抽出する。

    アンカー行の直後または同一行の数値だけを候補にする。アンカーが
    見つからない場合は誤認識防止のため ``None`` を返す。
    """
    values = [str(line.text if hasattr(line, "text") else line).strip() for line in lines]
    values = [value for value in values if value]
    for index, value in enumerate(values):
        compact_value = re.sub(r"\s+", "", value)
        if not any(anchor in compact_value for anchor in _ANCHORS):
            continue
        same_line = _COUNT.findall(compact_value)
        if same_line:
            return int(same_line[-1])
        for following in values[index + 1 : index + 3]:
            match = _COUNT.search(following)
            if match:
                return int(match.group(1))
    return None
