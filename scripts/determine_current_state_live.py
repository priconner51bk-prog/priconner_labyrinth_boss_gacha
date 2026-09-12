"""起動前に現在状態を決め打ち判定する。AI判断は行わない。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "jp.co.cygames.princessconnectredive"


def run(command: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def adb_devices() -> dict[str, str]:
    result = run(["adb", "devices"])
    devices: dict[str, str] = {}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]
    return devices


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--package", default=PACKAGE)
    args = parser.parse_args()

    devices = adb_devices()
    status = devices.get(args.serial)
    if status is None:
        process = run(["tasklist", "/FI", "IMAGENAME eq HD-Player.exe"])
        emulator_process = "HD-Player.exe" in process.stdout
        print(json.dumps({
            "status": "no_adb_device",
            "next_action": "launch_emulator" if not emulator_process else "wait_emulator_boot",
            "serial": args.serial,
            "emulator_process": emulator_process,
        }, ensure_ascii=False))
        return 0
    if status != "device":
        print(json.dumps({"status": "adb_not_ready", "adb_status": status, "serial": args.serial}, ensure_ascii=False))
        return 0

    package_check = run(["adb", "-s", args.serial, "shell", "pidof", args.package])
    if package_check.returncode != 0 or not package_check.stdout.strip():
        print(json.dumps({"status": "app_not_running", "serial": args.serial, "package": args.package, "next_action": "launch_app"}, ensure_ascii=False))
        return 0

    screen_script = ROOT / "scripts/task_check_current_screen_live.py"
    screen = run([sys.executable, str(screen_script), "--serial", args.serial], timeout=30.0)
    try:
        screen_result = json.loads(screen.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        screen_result = {"status": "screen_unknown", "raw": screen.stdout[-500:]}
    print(json.dumps({"status": "app_running", "serial": args.serial, "package": args.package, "screen": screen_result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
