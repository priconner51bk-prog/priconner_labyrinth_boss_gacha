"""設定済みROIからテンプレート画像だけを再生成する補助ツール。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/live_screen_templates.json"


def main() -> int:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    out_dir = ROOT / "data/observations/live/optimized"
    out_dir.mkdir(parents=True, exist_ok=True)
    used: dict[str, int] = {}
    changed = 0
    for group in ("screens", "targets"):
        for name, item in data[group].items():
            source = ROOT / item["image"]
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is None:
                continue
            left, top = int(item["left"]), int(item["top"])
            right, bottom = int(item["right"]), int(item["bottom"])
            if image.shape[1] == right - left and image.shape[0] == bottom - top:
                continue
            if image.shape[1] < right or image.shape[0] < bottom:
                continue
            base = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or group
            used[base] = used.get(base, 0) + 1
            suffix = f"_{used[base]}" if used[base] > 1 else ""
            destination = out_dir / f"template_{base}{suffix}.png"
            crop = image[top:bottom, left:right]
            if cv2.imwrite(str(destination), crop):
                item["image"] = str(destination.relative_to(ROOT)).replace("\\", "/")
                changed += 1
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"optimized": changed, "output": str(out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
