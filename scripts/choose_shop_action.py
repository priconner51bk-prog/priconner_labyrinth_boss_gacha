"""ショップ候補の決定をJSONで返すCLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from decision.labyrinth_shop import choose_shop_action


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--area", type=int, required=True)
    parser.add_argument("--rupies", type=int, required=True)
    parser.add_argument("--relic-count", type=int, required=True)
    parser.add_argument("--refresh-count", type=int, default=0)
    args = parser.parse_args(argv)
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    result = choose_shop_action(candidates, area=args.area, rupies=args.rupies, relic_count=args.relic_count, refresh_count=args.refresh_count)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
