"""Build and verify the small, reproducible Windows distribution ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "distribution" / "priconner_labyrinth_boss_gacha.zip"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)

# Each archive name maps to one reviewed source. No directory is copied wholesale.
FILES = {
    "main.py": "main.py",
    "README.md": "distribution/README.md",
    "SECURITY.md": "SECURITY.md",
    "requirements.txt": "requirements.txt",
    "docs/SETUP.md": "docs/SETUP.md",
    "docs/OPERATIONS.md": "docs/OPERATIONS.md",
    "docs/CONFIGURATION.md": "docs/CONFIGURATION.md",
    "scripts/__init__.py": "scripts/__init__.py",
    "scripts/debug_boss_gacha.py": "scripts/debug_boss_gacha.py",
    "scripts/adb_runtime.py": "scripts/adb_runtime.py",
    "scripts/task_boss_gacha_live.py": "scripts/task_boss_gacha_live.py",
    "scripts/task_run_boss_gacha_live.py": "scripts/task_run_boss_gacha_live.py",
    "scripts/process_utils.py": "scripts/process_utils.py",
    "scripts/ensure_bluestacks_live.py": "scripts/ensure_bluestacks_live.py",
    "scripts/task_check_current_screen_live.py": "scripts/task_check_current_screen_live.py",
    "scripts/task_close_live.py": "scripts/task_close_live.py",
    "scripts/task_enter_labyrinth_live.py": "scripts/task_enter_labyrinth_live.py",
    "scripts/task_launch_labyrinth_live.py": "scripts/task_launch_labyrinth_live.py",
    "scripts/task_prepare_boss_gacha_live.py": "scripts/task_prepare_boss_gacha_live.py",
    "scripts/task_startup_live.py": "scripts/task_startup_live.py",
    "scripts/labyrinth_route.py": "scripts/labyrinth_route.py",
    "scripts/live_cli_utils.py": "scripts/live_cli_utils.py",
    "scripts/check_live_environment.py": "scripts/check_live_environment.py",
    "scripts/start_boss_gacha.ps1": "scripts/start_boss_gacha.ps1",
    **{f"configs/{name}.json": f"configs/{name}.json" for name in (
        "boss_area3", "boss_area5", "labyrinth_guild_order",
        "labyrinth_guild_starting_members", "labyrinth_target_policy",
        "live_screen_templates",
    )},
    **{f"src/boss_gacha/{name}": f"src/boss_gacha/{name}" for name in (
        "__init__.py", "controller.py", "guild_selection.py", "live_flow.py",
        "live_workflow.py", "name_matching.py", "runner.py",
    )},
    **{f"src/decision/{name}": f"src/decision/{name}" for name in (
        "__init__.py", "operation_log.py", "timing.py", "timing_trace.py",
    )},
    **{f"src/contracts/{name}": f"src/contracts/{name}" for name in (
        "__init__.py", "models.py",
    )},
    **{f"src/vision/{name}": f"src/vision/{name}" for name in (
        "__init__.py", "capture.py", "observation.py", "template_screen_probe.py",
    )},
}


def files() -> dict[str, Path]:
    selected = {name: ROOT / source for name, source in FILES.items()}
    for base in (
        ROOT / "data/template_migration/templates/boss_names",
        ROOT / "data/template_migration/templates/guild_names",
    ):
        selected.update({p.relative_to(ROOT).as_posix(): p for p in base.glob("*.png")})
    config = json.loads((ROOT / "configs/live_screen_templates.json").read_text(encoding="utf-8"))
    references = {entry["image"] for group in ("screens", "targets") for entry in config[group].values()}
    for name in references:
        if not name.startswith(("data/observations/live/template_", "data/observations/live/optimized/template_", "data/template_migration/templates/")):
            raise ValueError(f"Unreviewed template path: {name}")
        selected[name] = ROOT / name
    missing = [name for name, source in selected.items() if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing distribution sources: {missing}")
    return dict(sorted(selected.items()))


def build_bytes(selected: dict[str, Path]) -> bytes:
    content = {name: source.read_bytes() for name, source in selected.items()}
    sums = {name: hashlib.sha256(data).hexdigest() for name, data in content.items()}
    content["SHA256SUMS.json"] = (json.dumps(sums, indent=2, sort_keys=True) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def verify(archive_bytes: bytes, selected: dict[str, Path]) -> None:
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        expected = set(selected) | {"SHA256SUMS.json"}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError(f"Unexpected archive entries: {sorted(set(names) ^ expected)}")
        if any("__pycache__" in name or name.endswith(".pyc") or "egg-info" in name for name in names):
            raise ValueError("Generated archive includes Python build artifacts")
        sums = json.loads(archive.read("SHA256SUMS.json"))
        for name, source in selected.items():
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(archive.read(name)).hexdigest() != digest or sums.get(name) != digest:
                raise ValueError(f"Source/ZIP hash mismatch: {name}")
        for name in names:
            if not name.endswith(".md"):
                continue
            markdown = archive.read(name).decode("utf-8")
            for target in re.findall(r"\]\(([^)]+)\)", markdown):
                if target.startswith(("https:", "http:", "#")):
                    continue
                relative = target.split("#", 1)[0].replace("\\", "/")
                resolved = (Path(name).parent / relative).as_posix()
                if resolved not in expected:
                    raise ValueError(f"Broken Markdown link: {name} -> {target}")
        config = json.loads(archive.read("configs/live_screen_templates.json"))
        for group in ("screens", "targets"):
            for item in config[group].values():
                if item["image"] not in expected:
                    raise ValueError(f"Missing screen template: {item['image']}")


def smoke_test(archive_bytes: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="boss_gacha_dist_") as temp:
        root = Path(temp)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            archive.extractall(root)
        for args in (("main.py", "--help"), ("main.py", "live", "--help"),
                     ("scripts/task_boss_gacha_live.py", "--help"),
                     ("scripts/task_prepare_boss_gacha_live.py", "--help"),
                     ("scripts/task_run_boss_gacha_live.py", "--help"),
                     ("scripts/check_live_environment.py", "--help")):
            result = subprocess.run([sys.executable, *args], cwd=root, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20, check=False, env=env)
            if result.returncode:
                raise RuntimeError(f"ZIP help failed {args}: {result.stderr}")
        result = subprocess.run(
            [sys.executable, "scripts/check_live_environment.py", "--adb", "__missing_adb_offline__"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            check=False, env=env,
        )
        report = json.loads(result.stdout)
        checks = {entry["name"]: entry for entry in report["checks"]}
        if result.returncode != 2 or checks["screen_templates"]["ok"] is not True:
            raise RuntimeError(f"ZIP offline preflight failed: {report}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the existing ZIP matches current sources")
    args = parser.parse_args()
    selected = files()
    data = build_bytes(selected)
    verify(data, selected)
    smoke_test(data)
    if args.check:
        if not ZIP_PATH.is_file() or ZIP_PATH.read_bytes() != data:
            parser.error("Distribution ZIP is missing or stale; run scripts/build_distribution.py")
    else:
        ZIP_PATH.write_bytes(data)
    print(f"PASS entries={len(selected) + 1} sha256={hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
