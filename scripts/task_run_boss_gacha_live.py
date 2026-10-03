"""BlueStacks起動から対象ボス一致・BlueStacks終了までを1コマンドで実行する。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
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

DEFAULT_AREA3 = ["ベノムサラマンドラ"]
DEFAULT_AREA5 = ["ゴブリンロード"]


def _configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _read_settings() -> dict[str, object]:
    path = ROOT / ".local_gui_settings.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configured_names(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        names = [str(name).strip() for name in value if str(name).strip()]
        if names:
            return names
    return fallback.copy()


def _run_child(command: list[str], *, env: dict[str, str], name: str) -> tuple[int, dict[str, object]]:
    """Stream child progress and parse its last JSON result line."""
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, {"step": name, "status": "safety_stop", "reason": f"child_start_failed:{type(exc).__name__}"}

    result: dict[str, object] = {"step": name, "status": "safety_stop", "reason": "child_result_missing"}
    assert process.stdout is not None
    try:
        for line in process.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            print(line, flush=True)
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                result = candidate
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    result.setdefault("step", name)
    if code != 0 and result.get("status") not in {"safety_stop", "matched"}:
        result = {"step": name, "status": "safety_stop", "reason": "child_failed", "child_result": result}
    return code, result


def _build_parser(settings: dict[str, object]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=resolve_adb_serial())
    parser.add_argument("--adb", help="今回使うADB実行ファイル。省略時は保存済みパス")
    parser.add_argument("--passports", type=int, default=int(settings.get("passports", 1000)))
    parser.add_argument("--guild", default=str(settings.get("guild", "自警団（カォン）")))
    parser.add_argument("--difficulty", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--area3-boss", action="append", help="エリア3の許容ボス。複数指定可")
    parser.add_argument("--area5-boss", action="append", help="エリア5の許容ボス。複数指定可")
    parser.add_argument("--boot-timeout", type=float, default=180)
    parser.add_argument("--flow-timeout", type=float, default=600)
    parser.add_argument("--launcher", type=Path, default=Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe"))
    parser.add_argument("--instance", default="Nougat32")
    parser.add_argument("--package", default="jp.co.cygames.princessconnectredive")
    return parser


def main() -> int:
    _configure_stdio()
    settings = _read_settings()
    parser = _build_parser(settings)
    args = parser.parse_args()
    if args.passports < 0:
        parser.error("--passports must be non-negative")
    if args.boot_timeout <= 0 or args.flow_timeout <= 0:
        parser.error("timeouts must be positive")
    area3 = args.area3_boss or _configured_names(settings.get("area3"), DEFAULT_AREA3)
    area5 = args.area5_boss or _configured_names(settings.get("area5"), DEFAULT_AREA5)

    try:
        adb_path = resolve_adb_path(args.adb)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": str(exc)}, ensure_ascii=False))
        return 2
    if not adb_path:
        print(json.dumps({"status": "safety_stop", "reason": "adb_not_found"}, ensure_ascii=False))
        return 2
    try:
        save_adb_path(adb_path)
    except OSError as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"adb_config_write_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2

    lock = _acquire_device_lock(args.serial)
    if lock is None:
        print(json.dumps({"status": "safety_stop", "reason": "device_busy", "serial": args.serial}, ensure_ascii=False))
        return 2
    environment_snapshot = snapshot_adb_environment()
    try:
        pin_adb_environment(adb_path)
        env = os.environ.copy()
        prepare_command = [
            sys.executable, str(ROOT / "scripts/task_prepare_boss_gacha_live.py"),
            "--serial", args.serial, "--adb", adb_path, "--package", args.package,
            "--launcher", str(args.launcher), "--instance", args.instance,
            "--boot-timeout", str(args.boot_timeout), "--flow-timeout", str(args.flow_timeout),
            "--no-gui", "--lock-held",
        ]
        prepare_code, prepare = _run_child(prepare_command, env=env, name="preparation")
        if prepare_code != 0 or prepare.get("status") != "completed" or prepare.get("screen_after") != "labyrinth_top":
            print(json.dumps({"status": "safety_stop", "failed_step": "preparation",
                              "serial": args.serial, "preparation": prepare}, ensure_ascii=False))
            return 2

        gacha_command = [
            sys.executable, str(ROOT / "scripts/task_boss_gacha_live.py"),
            "--execute", "--passports", str(args.passports), "--serial", args.serial,
            "--adb", adb_path, "--guild", args.guild, "--difficulty", str(args.difficulty),
            "--lock-held",
        ]
        preparation_steps = prepare.get("steps", [])
        player_pid = None
        if preparation_steps and isinstance(preparation_steps[0], dict):
            window = preparation_steps[0].get("window", {})
            if isinstance(window, dict):
                player_pid = window.get("pid")
        if isinstance(player_pid, int) and player_pid > 0:
            gacha_command.extend(("--bluestacks-pid", str(player_pid)))
        for name in area3:
            gacha_command.extend(("--area3-boss", name))
        for name in area5:
            gacha_command.extend(("--area5-boss", name))
        gacha_code, gacha = _run_child(gacha_command, env=env, name="gacha")
        status = "matched" if gacha_code == 0 and gacha.get("status") == "matched" else "safety_stop"
        print(json.dumps({"status": status, "serial": args.serial, "guild": args.guild,
                          "area3_bosses": area3, "area5_bosses": area5,
                          "preparation": prepare, "gacha": gacha}, ensure_ascii=False))
        return 0 if status == "matched" else 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "safety_stop", "reason": "cancelled_by_user"}, ensure_ascii=False))
        return 130
    finally:
        restore_adb_environment(environment_snapshot)
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
