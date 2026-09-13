"""全ギルドの選択・確認・キャンセルを反復する実機試験ランナー。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], serial: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, *command, "--serial", serial],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    payload = {}
    for line in reversed(result.stdout.splitlines()):
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    return result.returncode, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/labyrinth_guild_starting_members.json")
    args = parser.parse_args()
    data = json.loads(args.config.read_text(encoding="utf-8"))
    guilds = list(data["guilds"])
    results = []
    for index, guild in enumerate(guilds):
        code, selected = run(["scripts/task_select_guild_live.py", "--guild", guild], args.serial)
        row = {"index": index, "guild": guild, "select": selected}
        if code != 0:
            row["status"] = "safety_stop"
            results.append(row)
            break
        code, cancelled = run(["scripts/task_cancel_guild_selection_live.py"], args.serial)
        row["cancel"] = cancelled
        if code != 0:
            row["status"] = "safety_stop"
            results.append(row)
            break
        row["status"] = "passed"
        results.append(row)
        if index + 1 < len(guilds):
            swipe = subprocess.run(
                ["adb", "-s", args.serial, "shell", "input", "swipe", "1100", "400", "250", "400", "500"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if swipe.returncode != 0:
                row["status"] = "safety_stop"
                row["reason"] = "swipe_failed"
                break
            # カルーセルのアニメーション完了後、一覧画面が安定してから次へ進む。
            stable = False
            for _ in range(10):
                time.sleep(0.5)
                check = subprocess.run(
                    [sys.executable, "scripts/task_check_current_screen_live.py", "--serial", args.serial],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                )
                if any('"screen_id": "guild_select"' in line for line in check.stdout.splitlines()):
                    stable = True
                    break
            if not stable:
                row["status"] = "safety_stop"
                row["reason"] = "guild_select_not_stable_after_swipe"
                break
    print(json.dumps({"status": "passed" if len(results) == len(guilds) and all(r["status"] == "passed" for r in results) else "incomplete", "total": len(guilds), "results": results}, ensure_ascii=False))
    return 0 if len(results) == len(guilds) else 2


if __name__ == "__main__":
    raise SystemExit(main())
