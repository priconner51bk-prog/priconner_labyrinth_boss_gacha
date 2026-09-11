from __future__ import annotations

from collections import OrderedDict
import hashlib
import subprocess
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .roi import NormalizedROI

DEFAULT_OCR_VERSION = "PP-OCRv5"


def gpu_utilization_percent(*, timeout_seconds: float = 0.5) -> float | None:
    """Return host GPU utilization when ``nvidia-smi`` is available.

    OCR must remain usable on machines without NVIDIA tooling, so an
    unavailable/invalid reading is represented as ``None`` rather than being
    treated as zero load.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=timeout_seconds,
        )
        values = [float(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        return max(values) if values else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def choose_ocr_device(preferred: str = "gpu:0", *, max_gpu_utilization: float = 90.0) -> str:
    """Select OCR device, falling back to CPU when the GPU is saturated."""
    if not 0.0 <= max_gpu_utilization <= 100.0:
        raise ValueError("max_gpu_utilization must be between 0 and 100")
    if not str(preferred).startswith("gpu"):
        return str(preferred)
    utilization = gpu_utilization_percent()
    # Missing telemetry is not proof of capacity; CPU is the safe fallback.
    if utilization is None or utilization >= max_gpu_utilization:
        return "cpu"
    return str(preferred)


class OCRLine(BaseModel):
    """Engine-neutral OCR line used by the observation layer."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: tuple[int, int, int, int] | None = None


def normalize_ocr_result(result: Any) -> list[OCRLine]:
    """Normalize common PaddleOCR result shapes without invoking an OCR model."""
    if hasattr(result, "get") and result.get("rec_texts") is not None:
        texts = result.get("rec_texts")
        scores = result.get("rec_scores", [])
        boxes = result.get("rec_boxes", result.get("rec_polys", []))
        texts = _as_sequence(texts)
        if texts is None:
            return []
        scores = _as_sequence(scores) or []
        boxes = _as_sequence(boxes) or []
        lines: list[OCRLine] = []
        for index, text in enumerate(texts):
            cleaned = str(text or "").strip()
            if not cleaned:
                continue
            try:
                confidence = float(scores[index]) if index < len(scores) else 0.0
            except (TypeError, ValueError):
                confidence = 0.0
            bbox = _normalize_bbox(boxes[index]) if index < len(boxes) else None
            try:
                lines.append(OCRLine(text=cleaned, confidence=confidence, bbox=bbox))
            except ValueError:
                continue
        return lines
    if not isinstance(result, list):
        return []
    lines = []
    for item in result:
        if not hasattr(item, "get"):
            continue
        if item.get("rec_texts") is not None:
            lines.extend(normalize_ocr_result(item))
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            lines.append(OCRLine(text=text, confidence=float(item.get("confidence", 0.0)), bbox=_normalize_bbox(item.get("bbox"))))
        except (TypeError, ValueError):
            continue
    return lines


class PaddleOCRAdapter:
    """Lazy, local-model PaddleOCR adapter for read-only image recognition."""

    def __init__(self, detection_model_dir: str, recognition_model_dir: str, *, device: str = "gpu:0", language: str = "japan"):
        from pathlib import Path

        self.detection_model_dir = Path(detection_model_dir)
        self.recognition_model_dir = Path(recognition_model_dir)
        if language not in {"japan", "jpn"}:
            raise ValueError("language must be japan (jpn)")
        # PaddleOCR's language key is ``japan``; ``jpn`` is accepted here as
        # the user-facing ISO-style alias.
        self.language = "japan"
        self._roi_cache: OrderedDict[str, tuple[OCRLine, ...]] = OrderedDict()
        for model_dir in (self.detection_model_dir, self.recognition_model_dir):
            if not model_dir.is_dir() or not (model_dir / "inference.yml").is_file():
                raise FileNotFoundError(f"local OCR model is unavailable: {model_dir}")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError("PaddleOCR is not installed") from exc
        self._engine = PaddleOCR(
            text_detection_model_name=self.detection_model_dir.name,
            text_detection_model_dir=str(self.detection_model_dir),
            text_recognition_model_name=self.recognition_model_dir.name,
            text_recognition_model_dir=str(self.recognition_model_dir),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=device,
            lang=self.language,
        )

    @classmethod
    def from_default_models(cls, *, device: str = "cpu", language: str = "jpn"):
        """PaddleOCR標準の日本語モデルを利用する実機向け経路。

        初回のみPaddleOCRのモデルキャッシュ取得が発生する。取得に失敗した
        場合は呼び出し側で安全停止し、ゲーム操作へ進めない。
        """
        if language not in {"japan", "jpn"}:
            raise ValueError("language must be japan (jpn)")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError("PaddleOCR is not installed") from exc
        adapter = object.__new__(cls)
        adapter.detection_model_dir = None
        adapter.recognition_model_dir = None
        adapter.language = "japan"
        adapter._roi_cache = OrderedDict()
        adapter._engine = PaddleOCR(
            # 日本語の検出・認識は言語自動解決に任せる。
            # PaddleOCR 3.xでは PP-OCRv4 に日本語認識モデルがないため、
            # lang=japan と PP-OCRv5 の組み合わせを標準経路にする。
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=device,
            lang="japan",
            ocr_version="PP-OCRv5",
        )
        return adapter

    def recognize(self, image_path: str, roi: NormalizedROI | None = None) -> list[OCRLine]:
        input_value: object = image_path
        if roi is not None:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError("ROI付きOCRにはopencv-pythonが必要です") from exc
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"画像を読み込めません: {image_path}")
            input_value = roi.crop_array(image)
            cache_key = hashlib.sha256(
                input_value.tobytes() + str(input_value.shape).encode("ascii")
            ).hexdigest()
            cached = self._roi_cache.get(cache_key)
            if cached is not None:
                self._roi_cache.move_to_end(cache_key)
                return list(cached)
            lines = normalize_ocr_result(self._engine.predict(input_value))
            self._roi_cache[cache_key] = tuple(lines)
            self._roi_cache.move_to_end(cache_key)
            while len(self._roi_cache) > 128:
                self._roi_cache.popitem(last=False)
            return lines
        return normalize_ocr_result(self._engine.predict(input_value))


def _normalize_bbox(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        values = tuple(int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return values  # type: ignore[return-value]


def _as_sequence(value: Any) -> list[Any] | None:
    if isinstance(value, (list, tuple)):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            converted = tolist()
        except Exception:
            return None
        return list(converted) if isinstance(converted, (list, tuple)) else None
    return None
