"""Resolve and persist the one ADB client used by the live workflow."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADB_RUNTIME_CONFIG = ROOT / ".local_adb_runtime.json"
GUI_SETTINGS = ROOT / ".local_gui_settings.json"
ADB_PATH_ENV = "PRICONNER_ADB_PATH"


def resolve_adb_path(requested: str | None = None) -> str | None:
    """Use an explicit/configured client; never silently replace a stale one."""
    configured = requested or os.environ.get(ADB_PATH_ENV)
    if not configured and ADB_RUNTIME_CONFIG.is_file():
        try:
            data = json.loads(ADB_RUNTIME_CONFIG.read_text(encoding="utf-8"))
            configured = data.get("adb_path") if isinstance(data, dict) else None
        except (OSError, ValueError, TypeError):
            configured = None
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(configured)
        if found:
            return str(Path(found).resolve())
        raise FileNotFoundError(f"configured_adb_not_found:{configured}")
    found = shutil.which("adb")
    return str(Path(found).resolve()) if found else None


def pin_adb_environment(adb_path: str) -> None:
    """Make child processes inherit the selected absolute ADB executable first."""
    resolved = str(Path(adb_path).resolve())
    os.environ[ADB_PATH_ENV] = resolved
    os.environ["PATH"] = str(Path(resolved).parent) + os.pathsep + os.environ.get("PATH", "")


def snapshot_adb_environment() -> tuple[str | None, str | None]:
    return os.environ.get("PATH"), os.environ.get(ADB_PATH_ENV)


def restore_adb_environment(snapshot: tuple[str | None, str | None]) -> None:
    path, adb_path = snapshot
    for key, value in (("PATH", path), (ADB_PATH_ENV, adb_path)):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def save_adb_path(adb_path: str) -> None:
    resolved = str(Path(adb_path).resolve())
    ADB_RUNTIME_CONFIG.write_text(
        json.dumps({"adb_path": resolved}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_adb_serial(
    default: str = "127.0.0.1:5555", *, settings_path: Path | None = None,
) -> str:
    """Use the GUI's saved serial as the shared live-workflow default."""
    settings_path = settings_path or GUI_SETTINGS
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default
    serial = data.get("serial") if isinstance(data, dict) else None
    return str(serial).strip() if isinstance(serial, str) and serial.strip() else default
