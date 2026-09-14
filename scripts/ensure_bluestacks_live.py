"""BlueStacks/ADB/アプリを決め打ち手順で起動・復旧する。AI判断は行わない。"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
DEFAULT_PACKAGE = "jp.co.cygames.princessconnectredive"


def run(command: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def device_state(serial: str) -> str | None:
    result = run(["adb", "-s", serial, "get-state"])
    return result.stdout.strip() if result.returncode == 0 else None


def launch_emulator(launcher: Path, instance: str) -> bool:
    if not launcher.exists():
        return False
    command = [str(launcher)]
    if instance:
        command.extend(["--instance", instance])
    subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return True


def launch_android_package(serial: str, package: str) -> tuple[bool, str]:
    """パッケージのLauncher ActivityをADBだけで起動する。"""
    resolved = run(["adb", "-s", serial, "shell", "cmd", "package", "resolve-activity", "--brief", package])
    component = next((line.strip() for line in reversed(resolved.stdout.splitlines()) if "/" in line and line.strip().startswith(package + "/")), "")
    if component:
        started = run(["adb", "-s", serial, "shell", "am", "start", "-n", component], timeout=15.0)
        return started.returncode == 0, component
    fallback = run(["adb", "-s", serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout=15.0)
    return fallback.returncode == 0, "monkey"


def main() -> int:
    parser = argparse.ArgumentParser(description="決め打ちのBlueStacks/ADB起動復旧")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--instance", default="P64")
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    # 起動・操作の前に、現在状態を必ず確認する。
    state_script = ROOT / "scripts/determine_current_state_live.py"
    current = run(["python", str(state_script), "--serial", args.serial, "--package", args.package], timeout=35.0)
    try:
        current_state = json.loads(current.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        current_state = {"status": "state_unknown"}
    if current_state.get("status") == "app_running":
        print(json.dumps({"status": "already_running", "current": current_state}, ensure_ascii=False))
        return 0

    run(["adb", "start-server"])
    state = device_state(args.serial)
    launched = False
    if state != "device":
        launched = launch_emulator(args.launcher, args.instance)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        state = device_state(args.serial)
        if state == "device":
            launched_ok, component = launch_android_package(args.serial, args.package)
            if not launched_ok:
                print(json.dumps({"status": "safety_stop", "reason": "app_launch_failed", "serial": args.serial, "component": component}, ensure_ascii=False))
                return 2
            print(json.dumps({"status": "ready", "serial": args.serial, "package": args.package, "component": component, "emulator_started": launched}, ensure_ascii=False))
            return 0
        time.sleep(2.0)
    print(json.dumps({
        "status": "safety_stop",
        "reason": "adb_device_timeout",
        "serial": args.serial,
        "launcher": str(args.launcher),
        "instance": args.instance,
        "emulator_started": launched,
    }, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
