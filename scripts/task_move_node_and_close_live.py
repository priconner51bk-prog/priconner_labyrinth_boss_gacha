"""移動済みマスの確認から次画面の閉じるまでを安全に連結する。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, args: list[str]) -> int:
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                               cwd=ROOT, check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="マス選択・移動確認・ダイアログ終了をスクリプトで実行")
    parser.add_argument("--x", type=int, required=True, help="OCRで確認済みマスの中心X")
    parser.add_argument("--y", type=int, required=True, help="OCRで確認済みマスの中心Y")
    parser.add_argument("--type", choices=("normal", "extreme", "hell", "relic", "connect_sign", "shop", "event"), required=True)
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    common = ["--serial", args.serial]
    status = run("task_move_map_node_live.py", ["--x", str(args.x), "--y", str(args.y), "--type", args.type, *common])
    if status != 0:
        return status
    status = run("task_confirm_move_live.py", common)
    if status != 0:
        return status
    return run("task_close_live.py", common)


if __name__ == "__main__":
    raise SystemExit(main())
