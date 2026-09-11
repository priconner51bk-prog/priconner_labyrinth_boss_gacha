"""画面OCRから、登録済みの完全な名前または別名を一意に決定する。"""

import re
import unicodedata


def match_boss_name(text: str, candidates: dict[str, set[str]]) -> str | None:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))

    observed = normalize(text)
    if not observed:
        return None
    matches = {
        name for name, aliases in candidates.items()
        if any(normalize(alias) and normalize(alias) in observed for alias in aliases)
    }
    return next(iter(matches)) if len(matches) == 1 else None
