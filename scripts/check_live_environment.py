"""実機実行前の ADB・解像度・テンプレート確認。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="ボスガチャ実機環境の診断")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--adb", default="adb")
    args = parser.parse_args()
    result: dict[str, object] = {"serial": args.serial, "checks": []}
    checks: list[dict[str, object]] = result["checks"]  # type: ignore[assignment]

    try:
        version = subprocess.run([args.adb, "version"], check=True, capture_output=True, text=True)
        checks.append({"name": "adb", "ok": True, "detail": version.stdout.splitlines()[0] if version.stdout else "available"})
        state = subprocess.run([args.adb, "-s", args.serial, "get-state"], check=True, capture_output=True, text=True)
        checks.append({"name": "device", "ok": state.stdout.strip() == "device", "detail": state.stdout.strip()})
        size = subprocess.run([args.adb, "-s", args.serial, "shell", "wm", "size"], check=True, capture_output=True, text=True)
        matches = re.findall(r"(\d+)x(\d+)", size.stdout)
        actual = f"{matches[-1][0]}x{matches[-1][1]}" if matches else "unknown"
        checks.append({"name": "screen_size", "ok": actual == "1280x720", "detail": actual, "expected": "1280x720"})
    except (OSError, subprocess.SubprocessError) as exc:
        checks.append({"name": "adb", "ok": False, "detail": str(exc)})

    template_config = ROOT / "configs" / "live_screen_templates.json"
    missing: list[str] = []
    try:
        data = json.loads(template_config.read_text(encoding="utf-8"))
        for group in ("screens", "targets"):
            for value in data.get(group, {}).values():
                path = ROOT / value["image"] if not Path(value["image"]).is_absolute() else Path(value["image"])
                if not path.is_file() and str(path) not in missing:
                    missing.append(str(path))
        checks.append({"name": "screen_templates", "ok": not missing, "missing_count": len(missing), "first_missing": missing[0] if missing else None})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks.append({"name": "screen_templates", "ok": False, "detail": str(exc)})

    result["ok"] = all(bool(check.get("ok")) for check in checks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
