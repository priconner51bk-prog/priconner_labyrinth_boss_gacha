from __future__ import annotations

from collections.abc import Iterable


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return normalized Levenshtein distance for OCR text."""
    reference = str(reference or "")
    hypothesis = str(hypothesis or "")
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for row, ref_char in enumerate(reference, start=1):
        current = [row]
        for column, hyp_char in enumerate(hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (ref_char != hyp_char),
            ))
        previous = current
    return previous[-1] / len(reference)


def evaluate_ocr_text(reference: str, hypothesis: str, confidences: Iterable[float] = ()) -> dict[str, object]:
    """Build an offline OCR quality record without storing image data."""
    scores = [float(score) for score in confidences]
    return {
        "reference_length": len(str(reference or "")),
        "hypothesis_length": len(str(hypothesis or "")),
        "cer": round(character_error_rate(reference, hypothesis), 6),
        "exact_match": str(reference or "") == str(hypothesis or ""),
        "mean_confidence": round(sum(scores) / len(scores), 6) if scores else 0.0,
        "line_count": len(scores),
    }
