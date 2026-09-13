"""ライブ画面テンプレートのファイル名を template_ 接頭辞へ統一する。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/live_screen_templates.json"


def main() -> int:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for group in ("screens", "targets"):
        for item in data[group].values():
            path = str(item.get("image", ""))
            if not path.startswith("data/observations/live/"):
                continue
            old = ROOT / path
            if old.name.startswith("template_"):
                continue
            new_name = f"template_{old.name}"
            new = old.with_name(new_name)
            mapping[path] = str(new.relative_to(ROOT)).replace("\\", "/")
    for old_path, new_path in mapping.items():
        old = ROOT / old_path
        new = ROOT / new_path
        if old.exists():
            if new.exists() and old.resolve() != new.resolve():
                raise FileExistsError(new)
            old.rename(new)
    for group in ("screens", "targets"):
        for item in data[group].values():
            path = str(item.get("image", ""))
            if path in mapping:
                item["image"] = mapping[path]
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"renamed": len(mapping), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
