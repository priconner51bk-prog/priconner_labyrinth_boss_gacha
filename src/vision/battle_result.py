"""戦闘終了画面の最小OCR判定。"""

from __future__ import annotations

from collections.abc import Iterable
import re


def classify_battle_result(lines: Iterable[object]) -> dict[str, str] | None:
    """OCR行から勝敗と戦闘種別を分類する。不明なら ``None``。"""
    text = " ".join(str(item.text if hasattr(item, "text") else item).strip() for item in lines)
    text = re.sub(r"\s+", "", text)
    if "敗北" in text:
        outcome = "defeat"
    elif "勝利" in text:
        outcome = "victory"
    else:
        return None
    if any(token in text for token in ("エリア3", "エリア３", "エリア5", "エリア５")):
        battle_type = "area_boss"
    elif "EXTRIME" in text.upper() or "EXTREME" in text.upper() or "エクストリーム" in text:
        battle_type = "extreme"
    elif "HELL" in text.upper() or "ヘル" in text:
        battle_type = "hell"
    else:
        battle_type = "normal"
    return {"outcome": outcome, "battle_type": battle_type}
