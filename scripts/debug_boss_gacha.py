"""ボスガチャ判定のデバッグ実行（ADB操作なし）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# リポジトリ直下から実行しても、サブプロジェクトのパッケージを解決できるようにする。
SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBPROJECT_ROOT / "src"))

from boss_gacha import BossGachaController, BossGachaPolicy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="configs/labyrinth_target_policy.json")
    parser.add_argument("--observations", help="ボス名配列JSON（各要素に3/5を含む）")
    args = parser.parse_args()
    policy = BossGachaPolicy.from_json(args.policy)
    observations = json.loads(Path(args.observations).read_text(encoding="utf-8")) if args.observations else []
    if not observations:
        observations = [{"3": "未指定", "5": "未指定"}] * policy.max_attempts
    controller = BossGachaController(policy)
    for names in observations[: policy.max_attempts]:
        result = controller.evaluate(names)
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] in {"matched", "max_attempts", "safety_stop"}:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
