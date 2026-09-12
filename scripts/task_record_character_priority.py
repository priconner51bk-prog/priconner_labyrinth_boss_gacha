"""ユーザーがピックしたキャラと戦闘結果を、シーン別のキャラ優先順位学習へ記録する。

学習データが基準を満たすまでの間はユーザーがキャラピックを行う。このコマンドは
そのピック結果（キャラ名・プール・敵・ステージ・勝敗）をJSONLへ残し、
``character_priority_learning`` がシーン別の優先順位を学習するためのデータ源にする。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _names_from_args(raw: str) -> list[str]:
    names = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="ユーザーキャラピックと勝敗をシーン別優先順位学習へ記録")
    parser.add_argument("--enemy", required=True, help="敵名（例: ゴブリンロード / 正月キャル / normal）")
    parser.add_argument("--stage", required=True, help="ステージ（例: area5 / 3-5 / initial / normal）")
    parser.add_argument("--outcome", choices=("victory", "defeat"), required=True)
    parser.add_argument("--selected", required=True, help="ピックしたキャラ名。カンマ区切り")
    parser.add_argument("--pool", default="", help="選択可能なキャラプール。カンマ区切り（任意）")
    parser.add_argument("--source", choices=("initial", "battle"), default="battle")
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge/character_priority.jsonl")
    args = parser.parse_args()

    selected = _names_from_args(args.selected)
    pool = _names_from_args(args.pool)
    if not selected:
        parser.error("selected must not be empty")

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "enemy": args.enemy.strip(),
        "stage": args.stage.strip(),
        "outcome": args.outcome,
        "selected_character_names": selected,
        "candidate_names": pool,
        "pool_size": len(pool),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        rel = str(args.output.relative_to(ROOT))
    except ValueError:
        rel = str(args.output)
    print(json.dumps({"status": "recorded", "output": rel, "selected": selected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())