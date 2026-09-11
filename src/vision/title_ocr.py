"""共通タイトル位置のOCRユーティリティ。"""

from __future__ import annotations

from typing import Iterable


# BlueStacksのゲーム画面はタイトルのY位置がほぼ共通する。
TITLE_Y_RANGE = (20, 100)
TITLE_CENTER_X = 640
TITLE_CENTER_TOLERANCE = 260


def centered_title_text(lines: Iterable[object], *, image_width: int = 1280) -> str:
    """共通タイトル帯にある中央寄せ文字だけを連結して返す。

    タイトルごとの固定幅ROIは持たず、OCRが返した文字列のbbox幅を使う。
    そのため、短いタイトルと長いタイトルを同じ座標系で扱える。
    """
    selected: list[tuple[float, str]] = []
    for line in lines:
        text = getattr(line, "text", "")
        bbox = getattr(line, "bbox", None)
        confidence = float(getattr(line, "confidence", 0.0))
        if not text or bbox is None or confidence < 0.70 or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = (float(value) for value in bbox)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        if not (TITLE_Y_RANGE[0] <= center_y <= TITLE_Y_RANGE[1]):
            continue
        if abs(center_x - image_width / 2.0) > TITLE_CENTER_TOLERANCE:
            continue
        selected.append((x1, str(text).replace(" ", "")))
    return "".join(text for _, text in sorted(selected, key=lambda item: item[0]))


def classify_title_ocr(lines: Iterable[object], *, image_width: int = 1280) -> dict[str, object]:
    """Recognize the title screen only when title and start text are unambiguous."""
    line_list = list(lines)
    title = centered_title_text(line_list, image_width=image_width)
    if not title:
        title_parts = []
        for line in line_list:
            text = str(getattr(line, "text", "")).replace(" ", "")
            bbox = getattr(line, "bbox", None)
            confidence = float(getattr(line, "confidence", 0.0))
            if bbox and len(bbox) == 4 and confidence >= 0.70:
                center_x = (float(bbox[0]) + float(bbox[2])) / 2
                center_y = (float(bbox[1]) + float(bbox[3])) / 2
                if abs(center_x - image_width / 2) <= TITLE_CENTER_TOLERANCE and 120 <= center_y <= 300:
                    title_parts.append(text)
        title = "".join(title_parts)
    starts = []
    ambiguous_bottom = 0
    for line in line_list:
        text = str(getattr(line, "text", "")).replace(" ", "").upper()
        confidence = float(getattr(line, "confidence", 0.0))
        bbox = getattr(line, "bbox", None)
        if "TOUCHTOSTART" in text and confidence >= 0.70 and bbox and len(bbox) == 4:
            center = (float(bbox[0]) + float(bbox[2])) / 2
            if abs(center - image_width / 2) <= TITLE_CENTER_TOLERANCE:
                starts.append(text)
        if bbox and len(bbox) == 4 and confidence >= 0.70:
            center_y = (float(bbox[1]) + float(bbox[3])) / 2
            if 560 <= center_y <= 680:
                ambiguous_bottom += 1
    if title and len(starts) == 1 and ambiguous_bottom == 1 and ("プリンセスコネクト" in title or "PRINCESSCONNECT" in title.upper() or "RE:DIVE" in title.upper()):
        return {"screen_id": "title", "title": title}
    return {"screen_id": None, "title": title}
