"""Read-only BlueStacks/ADB/game startup diagnostics for C10a."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Callable


DEFAULT_LAUNCHER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
DEFAULT_PACKAGE = "jp.co.cygames.princessconnectredive"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)


def diagnose_startup(
    *, serial: str, package: str, launcher: Path, instance: str,
    bluestacks_error_text: str = "",
    run: Callable[[list[str]], subprocess.CompletedProcess[str]] = _run,
    path_is_file: Callable[[Path], bool] = Path.is_file,
) -> dict[str, object]:
    """Inspect each startup dependency without launching or sending input."""
    common = {"launcher": str(launcher), "instance": instance,
              "serial": serial, "package": package, "input_count": 0}
    normalized_error = bluestacks_error_text.strip().casefold()
    if "failed to read configuration file" in normalized_error:
        return {"status": "safety_stop", "stage": "bluestacks_configuration",
                "reason": "bluestacks_configuration_unreadable",
                "detail": bluestacks_error_text.strip(), **common}
    if not serial.strip() or not package.strip() or not instance.strip():
        return {"status": "safety_stop", "stage": "arguments",
                "reason": "startup_identity_missing", **common}
    if not path_is_file(launcher):
        return {"status": "safety_stop", "stage": "bluestacks_launcher",
                "reason": "bluestacks_launcher_missing", **common}

    adb = run(["adb", "version"])
    if adb.returncode != 0:
        return {"status": "safety_stop", "stage": "adb_client",
                "reason": "adb_client_unavailable", "detail": (adb.stderr or adb.stdout).strip(), **common}
    state = run(["adb", "-s", serial, "get-state"])
    device_state = state.stdout.strip() if state.returncode == 0 else "unavailable"
    if device_state != "device":
        return {"status": "safety_stop", "stage": "adb_device",
                "reason": "adb_device_not_ready", "device_state": device_state,
                "detail": (state.stderr or state.stdout).strip(), **common}

    resolved = run(["adb", "-s", serial, "shell", "cmd", "package",
                    "resolve-activity", "--brief", package])
    component = next((line.strip() for line in reversed(resolved.stdout.splitlines())
                      if line.strip().startswith(package + "/")), "")
    if resolved.returncode != 0 or not component:
        return {"status": "safety_stop", "stage": "android_package",
                "reason": "package_launcher_unresolved", "device_state": device_state,
                "detail": (resolved.stderr or resolved.stdout).strip(), **common}

    process = run(["adb", "-s", serial, "shell", "pidof", package])
    running = process.returncode == 0 and bool(process.stdout.strip())
    return {"status": "ready" if running else "needs_launch",
            "stage": "current_state", "reason": None if running else "app_not_running",
            "device_state": device_state, "component": component,
            "app_running": running, **common}


def main() -> int:
    parser = argparse.ArgumentParser(description="ボスガチャ起動環境の読み取り専用診断")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--instance", default="Nougat32")
    parser.add_argument("--bluestacks-error", default="",
                        help="BlueStacksダイアログから記録したエラー文（任意）")
    args = parser.parse_args()
    try:
        result = diagnose_startup(serial=args.serial, package=args.package,
                                  launcher=args.launcher, instance=args.instance,
                                  bluestacks_error_text=args.bluestacks_error)
    except (OSError, subprocess.SubprocessError) as exc:
        result = {"status": "safety_stop", "stage": "diagnostic",
                  "reason": f"diagnostic_failed:{type(exc).__name__}", "input_count": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"ready", "needs_launch"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
