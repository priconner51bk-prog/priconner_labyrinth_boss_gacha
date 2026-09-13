"""固定テンプレート画像を指定範囲で最小化する補助ツール。"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def crop_image(image, left: int, top: int, right: int, bottom: int):
    """Return a non-empty crop fully contained within the source image."""
    height, width = image.shape[:2]
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(
            f"切り出し範囲が画像外です: ({left}, {top}, {right}, {bottom}) "
            f"for {width}x{height}"
        )
    return image[top:bottom, left:right]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--left", type=int, required=True)
    parser.add_argument("--top", type=int, required=True)
    parser.add_argument("--right", type=int, required=True)
    parser.add_argument("--bottom", type=int, required=True)
    args = parser.parse_args()
    image = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"画像を読み込めません: {args.source}")
    try:
        crop = crop_image(image, args.left, args.top, args.right, args.bottom)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.destination), crop):
        raise SystemExit(f"画像を書き込めません: {args.destination}")
    print(f"{args.destination}: {crop.shape[1]}x{crop.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
