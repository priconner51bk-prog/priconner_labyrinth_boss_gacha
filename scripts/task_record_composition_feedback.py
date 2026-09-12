"""ユーザー補助で決めた編成と戦闘結果を学習用JSONLへ記録する。"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from decision.character_priority_learning import build_enemy_composition_id

def main() -> int:
    p = argparse.ArgumentParser(description="編成選択・勝敗フィードバックを記録")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--indices", required=True, help="選択カード番号。複数編成は ; 区切り")
    p.add_argument("--outcome", choices=("victory", "defeat"), required=True)
    p.add_argument("--enemy", default="unknown")
    p.add_argument("--stage", default="unknown")
    p.add_argument("--enemy-composition", default="", help="敵編成を表す安定したJSONまたは文字列")
    p.add_argument("--difficulty", default="", help="難易度。敵編成キーに含める")
    p.add_argument("--source", choices=("initial", "battle"), default="battle")
    p.add_argument("--selection-reason", default="specified_indices")
    p.add_argument("--output", type=Path, default=ROOT / "data/knowledge/composition_feedback.jsonl")
    a = p.parse_args()
    manifest = a.manifest if a.manifest.is_absolute() else ROOT / a.manifest
    if not manifest.exists():
        p.error("manifest_not_found")
    try:
        groups = [[int(v.strip()) for v in group.split(",") if v.strip()] for group in a.indices.split(";")]
    except ValueError:
        p.error("indices_invalid")
    if not groups or any(not group or len(set(group)) != len(group) for group in groups):
        p.error("indices_invalid")
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        p.error("manifest_invalid")
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": a.source, "enemy": a.enemy, "stage": a.stage,
        "enemy_composition": a.enemy_composition,
        "enemy_composition_id": build_enemy_composition_id(
            enemy=a.enemy, stage=a.stage, composition=a.enemy_composition, difficulty=a.difficulty
        ),
        "difficulty": a.difficulty,
        "selection_reason": a.selection_reason,
        "priority_credit": a.selection_reason != "pool_under_five_all",
        "outcome": a.outcome, "selected_indices": groups,
        "manifest": str(manifest.relative_to(ROOT)),
        "candidate_cards": manifest_data.get("cards", manifest_data.get("candidates", [])) if isinstance(manifest_data, dict) else [],
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"status": "recorded", "output": str(a.output.relative_to(ROOT))}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
