"""実機の画面ID・対象表示をタップ前に確認する診断ツール。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config
from live_cli_utils import screen_error_message


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/live_screen_templates.json"))
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    probe = load_template_probe_config(args.config, AdbScreenCapture(serial=args.serial))
    try:
        screen = probe.observe_screen()
    except Exception as exc:
        print(f"screen_id=unknown")
        print(f"safety_stop=screen_observation_failed:{type(exc).__name__}")
        print(f"error={screen_error_message(exc, args.serial)}")
        return 2
    print(f"screen_id={screen or 'unknown'}")
    for label in ("出発", "ラビリンス", "フォレスティエ", "マップ", "左BOSS", "右BOSS", "閉じる", "撤退する"):
        try:
            visible = probe.target_visible(label)
        except Exception as exc:
            print(f"target[{label}]=unknown")
            print(f"safety_stop=target_observation_failed:{type(exc).__name__}")
            return 2
        print(f"target[{label}]={'visible' if visible else 'hidden'}")
    return 0 if screen is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
