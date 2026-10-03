"""BlueStacksを起動し、Android起動完了とプリコネ起動を確認する。"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from scripts.process_utils import run_without_console
except ModuleNotFoundError:  # Direct `python scripts/<task>.py` invocation.
    from process_utils import run_without_console

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.adb_runtime import resolve_adb_path, resolve_adb_serial

DEFAULT_LAUNCHER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
DEFAULT_PACKAGE = "jp.co.cygames.princessconnectredive"
DEFAULT_SERIAL = "127.0.0.1:5555"
DEFAULT_INSTANCE = "Nougat32"
MAX_ADB_CONNECT_ATTEMPTS = 3

def _configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def adb_device_diagnostics(serial: str, *, adb: str = "adb") -> dict[str, object]:
    """Report the requested serial and attached devices without selecting a fallback.

    A different attached Android device is not a safe substitute for the
    configured BlueStacks endpoint, so expose the mismatch for diagnosis.
    """
    try:
        result = run(["adb", "devices", "-l"], timeout=10, adb=adb)
        entries = [
            line.strip() for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("List of devices") and not line.startswith("*")
        ]
        found = any(line.split() and line.split()[0] == serial for line in entries)
        diagnostic: dict[str, object] = {
            "adb_path": str(Path(adb).resolve()) if Path(adb).is_file() else adb,
            "requested_serial": serial,
            "requested_serial_available": found,
            "available_devices": entries,
        }
        version = run(["adb", "version"], timeout=10, adb=adb)
        if version.stdout.strip():
            diagnostic["adb_version"] = version.stdout.splitlines()[0].strip()
        if result.returncode != 0 or result.stderr.strip():
            diagnostic["adb_error"] = result.stderr.strip()[-500:]
        return diagnostic
    except (OSError, subprocess.SubprocessError) as exc:
        return {"requested_serial": serial, "diagnostic_error": type(exc).__name__}


def run(command: list[str], *, timeout: float = 10.0, adb: str = "adb") -> subprocess.CompletedProcess[str]:
    if command and command[0] == "adb":
        command = [adb, *command[1:]]
    return run_without_console(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, check=False)


def device_state(serial: str, *, adb: str = "adb") -> str | None:
    result = run(["adb", "-s", serial, "get-state"], adb=adb)
    return result.stdout.strip() if result.returncode == 0 else None


def player_running() -> bool:
    result = run(["tasklist", "/FI", "IMAGENAME eq HD-Player.exe", "/NH"])
    return result.returncode == 0 and "HD-Player.exe" in result.stdout.casefold()


def show_player_window(timeout: float = 30.0, *, target_pid: int | None = None) -> dict[str, object] | None:
    """BlueStacksの既存ウィンドウを復元し、ユーザーから見える状態にする。"""
    if os.name != "nt":
        return None

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd_type = ctypes.wintypes.HWND
    bool_type = ctypes.wintypes.BOOL
    dword_type = ctypes.wintypes.DWORD
    lparam_type = ctypes.wintypes.LPARAM
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(bool_type, hwnd_type, lparam_type), lparam_type]
    user32.EnumWindows.restype = bool_type
    user32.GetWindowThreadProcessId.argtypes = [hwnd_type, ctypes.POINTER(dword_type)]
    user32.GetWindowThreadProcessId.restype = dword_type
    user32.IsWindowVisible.argtypes = [hwnd_type]
    user32.IsWindowVisible.restype = bool_type
    user32.IsIconic.argtypes = [hwnd_type]
    user32.IsIconic.restype = bool_type
    user32.ShowWindow.argtypes = [hwnd_type, ctypes.c_int]
    user32.ShowWindow.restype = bool_type
    user32.SetForegroundWindow.argtypes = [hwnd_type]
    user32.SetForegroundWindow.restype = bool_type
    user32.BringWindowToTop.argtypes = [hwnd_type]
    user32.BringWindowToTop.restype = bool_type
    user32.GetForegroundWindow.restype = hwnd_type
    user32.AttachThreadInput.argtypes = [dword_type, dword_type, bool_type]
    user32.AttachThreadInput.restype = bool_type
    user32.GetWindowTextW.argtypes = [hwnd_type, ctypes.wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.restype = dword_type

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        processes = run(["tasklist", "/FI", "IMAGENAME eq HD-Player.exe", "/FO", "CSV", "/NH"])
        pids: set[int] = set()
        if processes.returncode == 0:
            for row in csv.reader(processes.stdout.splitlines()):
                if len(row) > 1 and row[0].casefold() == "hd-player.exe":
                    try:
                        pids.add(int(row[1]))
                    except ValueError:
                        pass
        if target_pid is not None:
            pids.intersection_update({target_pid})

        windows: list[tuple[int, str, bool, int]] = []
        callback_type = ctypes.WINFUNCTYPE(bool_type, hwnd_type, lparam_type)

        @callback_type
        def collect(hwnd: int, _lparam: int, process_ids: set[int] = pids,
                    found_windows: list[tuple[int, str, bool, int]] = windows) -> bool:
            pid = dword_type()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in process_ids:
                title_buffer = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
                title = title_buffer.value
                if title:
                    found_windows.append((int(hwnd), title, bool(user32.IsWindowVisible(hwnd)), int(pid.value)))
            return True

        user32.EnumWindows(collect, 0)
        if windows:
            player_windows = [item for item in windows if item[1].casefold() == "bluestacks app player"]
            candidates = player_windows or windows
            hwnd, title, _was_visible, process_id = next((item for item in candidates if item[2]), candidates[0])
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_pid = dword_type()
            foreground_thread = user32.GetWindowThreadProcessId(
                foreground_hwnd, ctypes.byref(foreground_pid)) if foreground_hwnd else 0
            current_thread = int(kernel32.GetCurrentThreadId())
            attached = bool(foreground_thread and user32.AttachThreadInput(
                current_thread, foreground_thread, True))
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            time.sleep(0.25)
            visible = bool(user32.IsWindowVisible(hwnd)) and not bool(user32.IsIconic(hwnd))
            foreground = user32.GetForegroundWindow() == hwnd
            # SetForegroundWindow is routinely denied when this process was
            # started by a background Python task. A visible, restored player
            # window is sufficient for the requested launch; don't report a
            # false launch failure solely because another app owns focus.
            if visible:
                return {"title": title, "pid": process_id, "visible": True, "foreground": foreground}
        time.sleep(1)
    return None


def launch_emulator(launcher: Path, instance: str) -> int | None:
    if not launcher.exists():
        return None
    command = [str(launcher)]
    if instance:
        command.extend(["--instance", instance])
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return int(process.pid)


def _launch_package(serial: str, package: str, *, adb: str) -> tuple[bool, str]:
    """ホーム画面からの起動と同じLauncher intentを使う。"""
    started = run(["adb", "-s", serial, "shell", "monkey", "-p", package,
                   "-c", "android.intent.category.LAUNCHER", "1"], timeout=20, adb=adb)
    if started.returncode == 0:
        return True, "monkey"
    resolved = run(["adb", "-s", serial, "shell", "cmd", "package", "resolve-activity",
                    "--brief", package], timeout=15, adb=adb)
    component = next((line.strip() for line in reversed(resolved.stdout.splitlines())
                      if "/" in line and line.strip().startswith(package + "/")), "")
    if not component:
        return False, "no_launcher_activity"
    result = run(["adb", "-s", serial, "shell", "am", "start", "-n", component], timeout=20, adb=adb)
    return result.returncode == 0, component


def _package_alive(serial: str, package: str, *, adb: str) -> bool:
    result = run(["adb", "-s", serial, "shell", "pidof", package], adb=adb)
    if result.returncode == 0 and result.stdout.strip():
        return True
    processes = run(["adb", "-s", serial, "shell", "ps", "-A"], adb=adb)
    return any(package in line for line in processes.stdout.splitlines())


def wait_for_android_boot(serial: str, *, adb: str, timeout: float) -> None:
    """Wait for Android readiness, with at most three failed TCP ADB connects."""
    deadline = time.monotonic() + timeout
    boot_polls = 0
    connect_attempts = 0
    state_timeouts = 0
    unavailable_state_attempts = 0
    next_connect_at = time.monotonic()
    while time.monotonic() < deadline:
        try:
            state = device_state(serial, adb=adb)
            state_timeouts = 0
        except (OSError, subprocess.SubprocessError) as exc:
            state_timeouts += 1
            if state_timeouts >= 3:
                raise RuntimeError("adb_state_retries_exhausted") from exc
            time.sleep(1)
            continue
        if state == "device":
            unavailable_state_attempts = 0
            boot = run(["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"], adb=adb)
            if boot.returncode == 0 and boot.stdout.strip() == "1":
                boot_polls += 1
                if boot_polls >= 2:
                    return
            else:
                boot_polls = 0
        else:
            boot_polls = 0
            if ":" in serial and time.monotonic() >= next_connect_at:
                if connect_attempts >= MAX_ADB_CONNECT_ATTEMPTS:
                    raise RuntimeError("adb_connection_retries_exhausted")
                connect_attempts += 1
                try:
                    run(["adb", "connect", serial], timeout=15, adb=adb)
                except (OSError, subprocess.SubprocessError):
                    if connect_attempts >= MAX_ADB_CONNECT_ATTEMPTS:
                        raise RuntimeError("adb_connection_retries_exhausted")
                next_connect_at = time.monotonic() + 30.0
            elif ":" not in serial:
                unavailable_state_attempts += 1
                if unavailable_state_attempts >= MAX_ADB_CONNECT_ATTEMPTS:
                    raise RuntimeError("adb_device_unavailable_retries_exhausted")
        time.sleep(2)
    raise TimeoutError("android_boot_timeout")


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="BlueStacksのAndroid起動を待ち、プリコネを起動")
    parser.add_argument("--serial", default=resolve_adb_serial(DEFAULT_SERIAL))
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--adb", help="ADB実行ファイルまたはPATH上のadb")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--timeout", type=float, default=180.0, help="ADB接続とAndroid起動を待つ秒数")
    args = parser.parse_args()

    try:
        args.adb = resolve_adb_path(args.adb)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": str(exc)}, ensure_ascii=False))
        return 2
    if not args.adb:
        print(json.dumps({"status": "safety_stop", "reason": "adb_not_found"}, ensure_ascii=False))
        return 2

    if os.name != "nt":
        print(json.dumps({"status": "safety_stop", "reason": "unsupported_os", "expected": "Windows"}, ensure_ascii=False))
        return 2
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    launched_pid: int | None = None
    try:
        server = run(["adb", "start-server"], timeout=15, adb=args.adb)
        if server.returncode != 0:
            raise RuntimeError("adb_server_start_failed")
        if device_state(args.serial, adb=args.adb) != "device":
            launched_pid = launch_emulator(args.launcher, args.instance)
            if not launched_pid:
                raise FileNotFoundError(f"BlueStacks launcher not found: {args.launcher}")

        window = show_player_window(target_pid=launched_pid)
        if window is None:
            raise RuntimeError("bluestacks_window_not_visible")

        wait_for_android_boot(args.serial, adb=args.adb, timeout=args.timeout)

        size = run(["adb", "-s", args.serial, "shell", "wm", "size"], adb=args.adb)
        dimensions = re.findall(r"(\d+)x(\d+)", size.stdout)
        actual_size = f"{dimensions[-1][0]}x{dimensions[-1][1]}" if dimensions else "unknown"
        if size.returncode != 0 or actual_size != "1280x720":
            raise RuntimeError(f"unsupported_screen_size:{actual_size}")

        launched_ok, component = _launch_package(args.serial, args.package, adb=args.adb)
        if not launched_ok:
            raise RuntimeError(f"app_launch_failed:{component}")
        app_deadline = time.monotonic() + 120
        while time.monotonic() < app_deadline:
            if _package_alive(args.serial, args.package, adb=args.adb):
                print(json.dumps({"status": "ready", "serial": args.serial, "package": args.package,
                                  "component": component, "emulator_started": launched_pid is not None,
                                  "resolution": actual_size, "window": window,
                                  "adb_path": str(Path(args.adb).resolve())}, ensure_ascii=False))
                return 0
            time.sleep(2)
        raise TimeoutError("app_start_timeout")
    except (OSError, subprocess.SubprocessError, TimeoutError, RuntimeError) as exc:
        reason = str(exc) if str(exc) else type(exc).__name__
        failure = {"status": "safety_stop", "reason": reason, "serial": args.serial,
                   "launcher": str(args.launcher), "instance": args.instance,
                   "emulator_started": launched_pid is not None,
                   "adb_diagnostics": adb_device_diagnostics(args.serial, adb=args.adb)}
        if reason.startswith("adb_connection_retries_exhausted"):
            failure["adb_connect_attempts"] = MAX_ADB_CONNECT_ATTEMPTS
        print(json.dumps(failure, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
