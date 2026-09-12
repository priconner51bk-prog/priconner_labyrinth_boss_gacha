"""Statically audit local decision code for game-input and cloud SDK dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from evaluation.safety_audit import audit_no_game_io


def collect_python_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src/decision"), Path("src/evaluation")])
    parser.add_argument("--output", type=Path, default=Path("reports/safety_audit.current.json"))
    args = parser.parse_args()
    files = collect_python_files(args.paths)
    findings = audit_no_game_io(files)
    report = {
        "schema_version": "safety-audit.v1",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "files_scanned": len(files),
        "findings": findings,
        "safe": not findings,
        "execution_allowed": False,
        "network_allowed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["safe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
