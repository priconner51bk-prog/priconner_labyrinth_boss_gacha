from dataclasses import dataclass

from vision.title_ocr import classify_title_ocr


@dataclass
class Line:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]


def test_accepts_one_centered_title_and_start_phrase():
    result = classify_title_ocr([
        Line("プリンセスコネクト！Re:Dive", .96, (360, 180, 920, 260)),
        Line("TOUCH TO START", .94, (470, 620, 810, 680)),
    ])
    assert result["screen_id"] == "title"


def test_rejects_start_phrase_without_title():
    result = classify_title_ocr([Line("TOUCH TO START", .95, (470, 620, 810, 680))])
    assert result["screen_id"] is None


def test_rejects_low_confidence_or_off_center_text():
    result = classify_title_ocr([
        Line("プリンセスコネクト", .69, (360, 180, 920, 260)),
        Line("TOUCH TO START", .95, (0, 620, 150, 680)),
    ])
    assert result["screen_id"] is None


def test_rejects_ambiguous_duplicate_start_phrases():
    result = classify_title_ocr([
        Line("プリンセスコネクト", .95, (360, 180, 920, 260)),
        Line("TOUCH TO START", .95, (470, 620, 810, 680)),
        Line("スタート", .91, (500, 590, 780, 630)),
    ])
    assert result["screen_id"] is None
