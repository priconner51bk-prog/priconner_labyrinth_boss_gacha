"""Read-only preflight for a saved boss-gacha result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from diagnostics.safety_stop_analysis import analyze_safety_stop

KNOWN_SCREENS = {
    "title", "startup_splash", "notice", "startup_error", "quest_menu",
    "labyrinth_top", "guild_select", "guild_confirm", "bonus", "initial_char",
    "character_join", "boss_map", "boss_detail", "withdraw_confirm", "item_reward",
}


def preflight(payload: object, *, base: Path, require_files: bool = False) -> dict[str, object]:
    def stop(reason: str, **extra) -> dict[str, object]:
        return {"status": "safety_stop", "reason": reason, **extra}

    if not isinstance(payload, dict):
        return stop("saved_result_not_object")
    saved_status = payload.get("status")
    if saved_status not in {"matched", "max_attempts", "safety_stop"}:
        return stop("saved_status_invalid", saved_status=saved_status)
    attempt, maximum = payload.get("attempt"), payload.get("max_attempts")
    if not (isinstance(attempt, int) and not isinstance(attempt, bool)
            and isinstance(maximum, int) and not isinstance(maximum, bool)
            and 0 <= attempt <= maximum <= 1000 and maximum >= 1):
        return stop("saved_attempt_bounds_invalid")
    allowed = payload.get("allowed_bosses")
    if not (isinstance(allowed, dict)
            and all(isinstance(allowed.get(area), list) and allowed[area]
                    and all(isinstance(name, str) and name.strip() for name in allowed[area])
                    for area in ("3", "5"))):
        return stop("saved_allowed_bosses_invalid")
    last_screen = payload.get("last_screen")
    if last_screen not in KNOWN_SCREENS:
        return stop("saved_last_screen_unknown", last_screen=last_screen)
    action = payload.get("last_action")
    if not (isinstance(action, dict) and isinstance(action.get("type"), str)
            and action["type"].strip() and action.get("screen_before") in KNOWN_SCREENS):
        return stop("saved_last_action_invalid")
    evidence = payload.get("evidence_paths")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
        return stop("saved_evidence_missing")
    missing = []
    if require_files:
        missing = [item for item in evidence if not ((Path(item) if Path(item).is_absolute() else base / item).is_file())]
        if missing:
            return stop("saved_evidence_file_missing", missing=missing)

    if saved_status in {"matched", "max_attempts"}:
        return {"status": "completed", "saved_status": saved_status,
                "attempt": attempt, "max_attempts": maximum,
                "last_screen": last_screen, "next_local_screen": None,
                "resume_rule": "do_not_rerun_completed_result", "evidence_status": "ok"}
    reason = str(payload.get("reason", "")).strip()
    analysis = analyze_safety_stop(reason)
    if not reason or analysis["reason_class"] == "unclassified":
        return stop("saved_safety_stop_unclassified", saved_reason=reason)
    return {"status": "ready", "saved_status": saved_status,
            "attempt": attempt, "max_attempts": maximum,
            "last_screen": last_screen, "last_action": action,
            "evidence_status": "ok", "next_local_screen": last_screen,
            "resume_rule": "observe_current_screen_and_match_last_screen_before_any_input",
            "safety_analysis": analysis}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--require-files", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.loads(args.result.read_text(encoding="utf-8-sig"))
        result = preflight(payload, base=args.result.parent, require_files=args.require_files)
    except (OSError, ValueError) as exc:
        result = {"status": "safety_stop", "reason": f"saved_result_unreadable:{type(exc).__name__}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"ready", "completed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
