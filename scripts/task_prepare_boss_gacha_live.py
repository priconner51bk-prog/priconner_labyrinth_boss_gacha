"""BlueStacks起動、プリコネ起動・再起動からラビリンス入口まで誘導する。"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import os
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
from scripts.adb_runtime import (
    pin_adb_environment,
    resolve_adb_path,
    resolve_adb_serial,
    restore_adb_environment,
    save_adb_path,
    snapshot_adb_environment,
)
from scripts.task_enter_labyrinth_live import _acquire_device_lock


def _configure_stdio() -> None:
    # Diagnostic payloads can contain OCR replacement characters that CP932
    # cannot encode. Configure only when invoked so importing the module does
    # not mutate pytest/GUI capture streams.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LAUNCHER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
DEFAULT_INSTANCE = "Nougat32"
DEFAULT_SERIAL = "127.0.0.1:5555"
DEFAULT_PACKAGE = "jp.co.cygames.princessconnectredive"
CONTROL_WINDOW_TITLE = "ボスガチャ操作"


def _control_window_handle() -> int | None:
    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd_type = ctypes.wintypes.HWND
    bool_type = ctypes.wintypes.BOOL
    lparam_type = ctypes.wintypes.LPARAM
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(bool_type, hwnd_type, lparam_type), lparam_type]
    user32.EnumWindows.restype = bool_type
    user32.GetWindowTextW.argtypes = [hwnd_type, ctypes.wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(bool_type, hwnd_type, lparam_type)

    @callback_type
    def collect(hwnd: int, _lparam: int) -> bool:
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == CONTROL_WINDOW_TITLE:
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return handles[0] if handles else None


def _open_control_window(adb_path: str, timeout: float = 15.0) -> dict[str, object]:
    """準備完了後にガチャ設定・操作用のTkウィンドウを表示する。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
    user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
    handle = _control_window_handle()
    started = False
    process = None
    if handle is None:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.is_file() else Path(sys.executable)
        environment = os.environ.copy()
        environment["PRICONNER_ADB_PATH"] = adb_path
        environment["PATH"] = str(Path(adb_path).parent) + os.pathsep + environment.get("PATH", "")
        process = subprocess.Popen(
            [str(executable), str(ROOT / "main.py")], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        started = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            handle = _control_window_handle()
            if handle is not None:
                break
            if process.poll() is not None:
                raise RuntimeError(f"python_gui_exited:{process.returncode}")
            time.sleep(0.25)
    if handle is None:
        raise TimeoutError("python_gui_window_timeout")
    user32.ShowWindow(handle, 9)  # SW_RESTORE
    user32.SetForegroundWindow(handle)
    return {"status": "shown", "started": started,
            "pid": process.pid if process is not None else None, "title": CONTROL_WINDOW_TITLE}


def _run_step(name: str, command: list[str], *, timeout: float, env: dict[str, str]) -> tuple[int, dict]:
    try:
        result = run_without_console(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=False, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        payload = {"step": name, "status": "safety_stop", "reason": "step_timeout",
                   "timeout_seconds": timeout}
        for key, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            if value:
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                payload[key] = str(value)[-1000:]
        return 2, payload
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, {"step": name, "status": "safety_stop", "reason": f"step_failed:{type(exc).__name__}"}
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        payload = {"status": "safety_stop", "reason": "child_output_not_json", "output": result.stdout[-500:]}
    if not isinstance(payload, dict):
        payload = {"status": "safety_stop", "reason": "child_output_not_object"}
    payload = {"step": name, **payload}
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()[-1000:]
    return result.returncode, payload


def _run_preparation(args) -> int:
    try:
        adb_path = resolve_adb_path(args.adb)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": str(exc)}, ensure_ascii=False))
        return 2
    if not adb_path:
        print(json.dumps({"status": "safety_stop", "reason": "adb_not_found", "adb": args.adb}, ensure_ascii=False))
        return 2
    try:
        save_adb_path(adb_path)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"adb_config_write_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    pin_adb_environment(adb_path)
    env = os.environ.copy()
    steps: list[dict] = []

    code, step = _run_step("bluestacks_and_first_app_launch", [
        sys.executable, str(ROOT / "scripts/ensure_bluestacks_live.py"),
        "--serial", args.serial, "--package", args.package, "--launcher", str(args.launcher),
        "--instance", args.instance, "--adb", adb_path, "--timeout", str(args.boot_timeout),
    ], timeout=args.boot_timeout + 150, env=env)
    steps.append(step)
    if code != 0 or step.get("status") != "ready":
        print(json.dumps({"status": "safety_stop", "failed_step": step.get("step"), "steps": steps}, ensure_ascii=False))
        return 2

    code, step = _run_step("app_restart_and_labyrinth_navigation", [
        sys.executable, str(ROOT / "scripts/task_enter_labyrinth_live.py"),
        "--serial", args.serial, "--adb", adb_path, "--package", args.package, "--lock-held",
    ], timeout=args.flow_timeout + 30, env=env)
    steps.append(step)
    if code != 0 or step.get("status") != "completed" or step.get("screen_after") != "labyrinth_top":
        print(json.dumps({"status": "safety_stop", "failed_step": step.get("step"), "steps": steps}, ensure_ascii=False))
        return 2

    gui = {"status": "skipped"}
    if not args.no_gui:
        try:
            gui = _open_control_window(adb_path)
        except (OSError, subprocess.SubprocessError, TimeoutError, RuntimeError) as exc:
            print(json.dumps({"status": "safety_stop", "reason": str(exc),
                              "screen_after": "labyrinth_top", "steps": steps}, ensure_ascii=False))
            return 2
    print(json.dumps({"status": "completed", "screen_after": "labyrinth_top", "adb_path": adb_path,
                      "gui": gui, "steps": steps}, ensure_ascii=False))
    return 0


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="BlueStacks起動→プリコネ起動・再起動→ラビリンス入口")
    parser.add_argument("--serial", default=resolve_adb_serial(DEFAULT_SERIAL))
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--adb", help="ADB実行ファイルまたはPATH上のadb")
    parser.add_argument("--boot-timeout", type=float, default=180, help="BlueStacks/Android起動待ち秒数")
    parser.add_argument("--flow-timeout", type=float, default=600, help="再起動から入口誘導までの上限秒数")
    parser.add_argument("--no-gui", action="store_true", help="完了後にPython操作ウィンドウを開かない")
    parser.add_argument("--lock-held", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if os.name != "nt":
        print(json.dumps({"status": "safety_stop", "reason": "unsupported_os", "expected": "Windows"}, ensure_ascii=False))
        return 2
    if args.boot_timeout <= 0 or args.flow_timeout <= 0:
        parser.error("timeouts must be positive")
    lock = None
    if not args.lock_held:
        lock = _acquire_device_lock(args.serial)
        if lock is None:
            print(json.dumps({"status": "safety_stop", "reason": "device_busy", "serial": args.serial}, ensure_ascii=False))
            return 2
    environment_snapshot = snapshot_adb_environment()
    try:
        return _run_preparation(args)
    finally:
        restore_adb_environment(environment_snapshot)
        if lock is not None:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
