"""ギルドカードのOCR行を位置情報で結合する純粋処理。座標は1280x720基準。"""

import re
import unicodedata
from itertools import combinations, pairwise


def scan_directions(guild_count: int, *, current_index: int = 0, target_index: int | None = None):
    """前回位置を起点に目的ギルドまでの横スクロールだけを返す。"""
    if guild_count <= 1:
        return []
    if target_index is None:
        # 互換経路: 目的地未指定時は全カードを覆う。
        steps = max(1, guild_count - 1)
        return [((1100, 400), (250, 400))] * steps + [((250, 400), (1100, 400))] * steps
    current_index = max(0, min(current_index, guild_count - 1))
    target_index = max(0, min(target_index, guild_count - 1))
    distance = target_index - current_index
    if distance > 0:
        return [((1100, 400), (250, 400))] * distance
    if distance < 0:
        return [((250, 400), (1100, 400))] * abs(distance)
    return []


def guild_button_point(lines, wanted: str):
    def normalize(text):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))

    rows = []
    for line in lines:
        if line.confidence < .55 or not line.bbox:
            continue
        left, top, right, bottom = line.bbox
        if 0 < left < right < 1280 and 420 <= top < bottom <= 510:
            rows.append((top, bottom, (left + right) // 2, normalize(line.text)))
    rows.sort()
    matches = set()
    for count in range(1, min(3, len(rows)) + 1):
        for group in combinations(rows, count):
            centers = [row[2] for row in group]
            if max(centers) - min(centers) > 55:
                continue
            if any(a[1] > b[0] + 5 or b[0] - a[1] > 30 for a, b in pairwise(group)):
                continue
            if "".join(row[3] for row in group) != normalize(wanted):
                continue
            x = sum(centers) // len(centers)
            if 100 <= x <= 1180:
                matches.add((x, max(520, min(600, group[-1][1] + 75))))
    return next(iter(matches)) if len(matches) == 1 else None
