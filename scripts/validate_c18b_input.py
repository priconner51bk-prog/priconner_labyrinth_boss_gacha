"""Validate the complete H-02/H-03 failure bundle required by C-18B."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_GROUPS = {"H-02", "H-03"}


def validate(path: Path, require_files: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read manifest: {exc}"]

    if not isinstance(payload, dict):
        return ["manifest must be a JSON object"]

    cases = payload.get("cases")
    expected = payload.get("expected_failure_count")
    reported = payload.get("reported_failure_count")
    if not isinstance(payload.get("batch_id"), str) or not payload["batch_id"].strip():
        errors.append("batch_id must be a non-empty string")
    if not isinstance(cases, list) or not cases:
        return errors + ["cases must be a non-empty array"]
    if not isinstance(expected, int) or expected < 1:
        errors.append("expected_failure_count must be a positive integer")
    elif expected != len(cases):
        errors.append(f"expected_failure_count={expected} but cases={len(cases)}")
    if not isinstance(reported, int) or reported < 1:
        errors.append("reported_failure_count must be a positive integer")
    elif reported != len(cases):
        errors.append(f"reported_failure_count={reported} but cases={len(cases)}")

    seen: set[str] = set()
    manifest_dir = path.parent
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{prefix}.case_id must be a non-empty string")
        elif case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        else:
            seen.add(case_id)
        if case.get("task_group") not in ALLOWED_GROUPS:
            errors.append(f"{prefix}.task_group must be H-02 or H-03")
        for field in ("script_name", "screen_id", "status", "reason", "screenshot_path"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        steps = case.get("ordered_steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"{prefix}.ordered_steps must be a non-empty array")
        else:
            orders: list[int] = []
            for step_index, step in enumerate(steps):
                step_prefix = f"{prefix}.ordered_steps[{step_index}]"
                if not isinstance(step, dict):
                    errors.append(f"{step_prefix} must be an object")
                    continue
                if not isinstance(step.get("order"), int) or step["order"] < 1:
                    errors.append(f"{step_prefix}.order must be a positive integer")
                else:
                    orders.append(step["order"])
                for field in ("action", "screen_id", "status"):
                    if not isinstance(step.get(field), str) or not step[field].strip():
                        errors.append(f"{step_prefix}.{field} must be a non-empty string")
            if orders and orders != list(range(1, len(steps) + 1)):
                errors.append(f"{prefix}.ordered_steps orders must be contiguous from 1")
        if require_files and isinstance(case.get("screenshot_path"), str):
            evidence = Path(case["screenshot_path"])
            if not evidence.is_absolute():
                evidence = manifest_dir / evidence
            if not evidence.is_file():
                errors.append(f"{prefix}.screenshot_path does not exist: {case['screenshot_path']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--require-files", action="store_true")
    args = parser.parse_args()
    errors = validate(args.manifest, args.require_files)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("C-18B input: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
