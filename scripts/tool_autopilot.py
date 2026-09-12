"""Auto-pilot CLI: drive the full labyrinth traversal end-to-end.

This wires the pure :class:`decision.autopilot.AutoPilot` state machine to the
real guarded ``task_`` live scripts over ADB.  It is the single entry point for
hands-off play:

    python scripts/tool_autopilot.py --execute --passports 10 --serial 127.0.0.1:5555

Without ``--execute`` it only reports the current screen and exits, mirroring
the preflight contract used elsewhere in the project.  ``--dry-run`` runs the
state machine against a scripted fake invoker so the sequencing logic can be
verified without touching the device.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import time
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.autopilot import AutoPilot
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config


def _emit(payload: dict) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)

DEFAULT_CONFIG_PATH = ROOT / "configs" / "autopilot.json"
PROGRESS_LOG_PATH = ROOT / "output" / "autopilot_progress.jsonl"
DEFAULT_ALLOWED_BOSSES = {
    "3": ["ベノムサラマンドラ"],
    "5": ["ゴブリンロード"],
}


def _progress_log(event: str, **fields: Any) -> None:
    """Append one machine-readable progress event for every orchestration step."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    PROGRESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
def load_default_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load launch defaults from the autopilot config file.

    A missing or invalid file yields an empty mapping so the CLI keeps
    working with its built-in defaults.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_allowed_bosses(config: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return the canonical ``allowed_bosses`` configuration mapping."""
    raw = config.get("allowed_bosses", DEFAULT_ALLOWED_BOSSES)
    if not isinstance(raw, dict):
        return {area: list(names) for area, names in DEFAULT_ALLOWED_BOSSES.items()}
    result: dict[str, list[str]] = {}
    for area, names in raw.items():
        if isinstance(names, list) and names and all(isinstance(name, str) and name for name in names):
            result[str(area)] = list(names)
    return result or {area: list(names) for area, names in DEFAULT_ALLOWED_BOSSES.items()}


def _kill_process_tree(pid: int) -> None:
    """Terminate a child process and everything it spawned (OCR server)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, check=False)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _last_json_object(text: str):
    """Return the last JSON object printed on stdout, if any.

    Guarded scripts print one JSON result per run, but some (boss gacha) emit
    a pretty-printed multi-line object.  Scanning for balanced JSON objects
    tolerates both single-line and indented output as well as preceding
    progress lines.
    """
    decoder = json.JSONDecoder()
    last = None
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if index >= length or text[index] != "{":
            line_end = text.find("\n", index)
            index = length if line_end == -1 else line_end + 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            line_end = text.find("\n", index)
            index = length if line_end == -1 else line_end + 1
            continue
        if isinstance(value, dict):
            last = value
        index = end
    return last


def build_live_invoker(serial: str, *, timeout_seconds: float = 300.0):
    """Return an invoker that runs a guarded live script and parses its JSON."""

    def invoke(script: str, args: list[str]) -> dict:
        script_path = ROOT / "scripts" / script
        if not script_path.exists():
            raise FileNotFoundError(script)
        command = [sys.executable, str(script_path), "--serial", serial, *args]
        started = time.monotonic()
        _progress_log("script_started", script=script, args=args, serial=serial)
        # Output goes to a temp file, not a pipe: the scripts spawn a
        # detached OCR server that inherits pipe handles, which would keep
        # the pipe open and deadlock subprocess.run's timeout.
        # Use a per-invocation path.  The child OCR server can inherit the
        # output handle briefly after the worker exits on Windows, so reusing
        # one PID-based path can make the next cleanup fail with WinError 32.
        out_path = ROOT / "output" / f".autopilot_{script}_{os.getpid()}_{time.time_ns()}.out"
        try:
            with open(out_path, "w", encoding="utf-8") as out_handle:
                process = subprocess.Popen(command, cwd=str(ROOT), stdout=out_handle,
                                           stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                # Boss-gacha performs up to ten guarded attempts.  Its
                # measured worst-case batch is close to five minutes, so the
                # ordinary invoker must use the same 15-minute budget as the
                # streaming/dashboard invoker below.  Otherwise the child is
                # killed just before it can emit its final JSON result.
                script_timeout = 900.0 if script == "task_boss_gacha_live.py" else timeout_seconds
                try:
                    process.wait(timeout=script_timeout)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(process.pid)
                    result = {"status": "safety_stop", "reason": f"script_timeout:{script_timeout:.0f}s:{script}"}
                    _progress_log("script_finished", script=script, status=result["status"],
                                  reason=result["reason"], duration_ms=round((time.monotonic() - started) * 1000, 1))
                    return result
        finally:
            text = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
            try:
                out_path.unlink(missing_ok=True)
            except PermissionError:
                # Parsing the captured output is still safe.  Retain the
                # locked diagnostic artifact rather than turning a completed
                # child result into an uncaught wrapper error.
                _progress_log("output_cleanup_deferred", script=script, path=str(out_path))
        result = _last_json_object(text)
        if result is None:
            tail = " ".join(text.split())[-200:]
            result = {"status": "safety_stop", "reason": f"no_json_output:{script}", "tail": tail}
            _progress_log("script_finished", script=script, status=result["status"],
                          reason=result["reason"], duration_ms=round((time.monotonic() - started) * 1000, 1))
            return result
        if not isinstance(result, dict):
            result = {"status": "safety_stop", "reason": f"non_object_json:{script}"}
            _progress_log("script_finished", script=script, status=result["status"],
                          reason=result["reason"], duration_ms=round((time.monotonic() - started) * 1000, 1))
            return result
        _progress_log("script_finished", script=script, status=result.get("status"),
                      reason=result.get("reason"), duration_ms=round((time.monotonic() - started) * 1000, 1))
        return result

    return invoke


def _dry_run_invoker():
    """A scripted invoker that plays a full winning traversal for offline checks."""
    nodes = [
        {"id": "n1", "type": "normal", "x": 100, "y": 300},
        {"id": "n2", "type": "extreme", "x": 300, "y": 300},
        {"id": "n3", "type": "relic", "x": 300, "y": 450},
        {"id": "n4", "type": "area_boss", "x": 600, "y": 300},
    ]
    table = {
        "task_boss_gacha_live.py": {"status": "matched", "boss_names": {"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}},
        "task_scan_map_live.py": {"status": "scanned", "nodes": nodes},
        "task_move_map_node_live.py": {"status": "moved"},
        "task_confirm_move_live.py": {"status": "confirmed"},
        "task_select_relic_live.py": {"status": "selected"},
        "task_run_normal_battle_live.py": {"status": "started"},
        "task_start_area_boss_live.py": {"status": "started"},
        "task_wait_battle_result_live.py": {"status": "result_detected", "text": "勝利"},
        "task_select_character_bonus_live.py": {"status": "selected"},
        "task_next_live.py": {"status": "advanced"},
        "task_close_live.py": {"status": "closed"},
    }

    def invoke(script: str, args: list[str]) -> dict:
        if script not in table:
            return {"status": "safety_stop", "reason": f"dry_run_unexpected_script:{script}"}
        return dict(table[script])

    return invoke


def main() -> int:
    parser = argparse.ArgumentParser(description="ラビリンス自動操縦（task_スクリプトを連鎖実行）")
    parser.add_argument("--execute", action="store_true", help="ADB入力を有効化（省略時はpreflightのみ）")
    parser.add_argument("--passports", type=int, default=None, help="今回利用を許可するパスポート枚数。0なら安全停止")
    parser.add_argument("--serial", default=None,
                        help="ADB target serial (default from --config)")
    parser.add_argument("--avoid-hell", dest="avoid_hell", action="store_true", default=True)
    parser.add_argument("--allow-hell", dest="avoid_hell", action="store_false")
    parser.add_argument("--battle-character-indices", default=None,
                        help="戦闘で選択するカード位置（例: 1,4,6,9,12）。未指定時は既存パーティを維持")
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--difficulty", type=int, default=None,
                        help="ラビリンス難易度1〜10（既定は--configまたは10）")
    parser.add_argument("--guild", default=None,
                        help="出発時に選択するギルド（既定は--configまたはpreferred_guilds先頭）")
    parser.add_argument("--area3-boss", action="append", default=None,
                        help="エリア3の対象ボス名。複数指定可（いずれかに一致すればOK）")
    parser.add_argument("--area5-boss", action="append", default=None,
                        help="エリア5の対象ボス名。複数指定可（いずれかに一致すればOK）")
    parser.add_argument("--dry-run", action="store_true", help="デバイスに触れず配列ロジックを検証")
    parser.add_argument("--web", action="store_true",
                        help="run the dashboard (progress + start/stop/resume/finish)")
    parser.add_argument("--port", type=int, default=8765, help="port for --web")
    parser.add_argument("--state-file", default=str(ROOT / "output" / "autopilot_state.json"),
                        help="run-state file used for resume")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                        help="JSON file providing defaults for --serial/--passports")
    args = parser.parse_args()
    config = load_default_config(args.config)
    if args.serial is None:
        args.serial = str(config.get("serial", "127.0.0.1:5555"))
    if args.passports is None:
        args.passports = int(config.get("passports", 0))
    if args.passports < 0:
        parser.error("--passports must be non-negative")
    if args.difficulty is None:
        args.difficulty = int(config.get("difficulty", 10))
    if args.guild is None:
        args.guild = str(config.get("guild", "美食殿"))
    configured_allowed_bosses = load_allowed_bosses(config)
    if args.area3_boss is None:
        args.area3_boss = list(configured_allowed_bosses.get("3", DEFAULT_ALLOWED_BOSSES["3"]))
    if args.area5_boss is None:
        args.area5_boss = list(configured_allowed_bosses.get("5", DEFAULT_ALLOWED_BOSSES["5"]))
    if not 1 <= args.difficulty <= 10:
        parser.error("--difficulty must be between 1 and 10")

    if args.web:
        return run_web_server(args)

    if args.dry_run:
        pilot = AutoPilot(_dry_run_invoker(), passports=max(1, args.passports),
                          avoid_hell=args.avoid_hell, difficulty=args.difficulty,
                          guild=args.guild,
                          allowed_bosses={"3": args.area3_boss, "5": args.area5_boss})
        outcome = pilot.run(max_steps=args.max_steps)
        _emit({"mode": "dry_run", **outcome, "state": pilot.state.to_dict()})
        return 0 if outcome["action"] == "completed" else 2

    # Preflight: report the current screen before any input.
    try:
        capture = AdbScreenCapture(serial=args.serial)
        probe = load_template_probe_config(ROOT / "configs" / "live_screen_templates.json", capture)
        screen_id = probe.observe_screen()
    except Exception as exc:
        _emit({"status": "safety_stop", "reason": f"screen_observation_failed:{type(exc).__name__}",
               "execute": args.execute})
        return 2
    _emit({"screen_id": screen_id, "execute": args.execute, "passports": args.passports})
    _progress_log("screen_detected", screen_id=screen_id, execute=args.execute,
                  passports=args.passports, serial=args.serial)
    if not args.execute:
        return 0
    if args.passports <= 0:
        _emit({"status": "safety_stop", "reason": "passport_count_not_positive"})
        return 2

    def _step_log(outcome: dict) -> None:
        result = outcome.get("result", {}) or {}
        payload = {"step": outcome.get("action"), "phase": outcome.get("phase"),
                   "status": result.get("status", "")}
        if result.get("reason"):
            payload["reason"] = result["reason"]
        # 何待ちかを人間が読める形で明示する。
        status = result.get("status", "")
        if status == "user_confirmation_required":
            payload["waiting"] = f"ユーザー確認待ち: {result.get('reason', '')}"
        elif status in {"safety_stop", "stopped"}:
            payload["waiting"] = f"安全停止: {result.get('reason', '')}"
        _progress_log("autopilot_step", **payload)
        _emit(payload)

    pilot = AutoPilot(build_live_invoker(args.serial), passports=args.passports,
                      avoid_hell=args.avoid_hell, battle_character_indices=args.battle_character_indices,
                      difficulty=args.difficulty, guild=args.guild,
                      allowed_bosses={"3": args.area3_boss, "5": args.area5_boss},
                      step_logger=_step_log, state_file=args.state_file)
    pilot.load_state()
    # CLIで明示的に実行した場合は、前回の停止フラグを引き継がず、
    # 保存済みフェーズから現在画面へ再接続する。
    if args.execute:
        pilot.resume()
    outcome = pilot.run(max_steps=args.max_steps)
    _progress_log("autopilot_finished", action=outcome.get("action"),
                  phase=outcome.get("phase"), status=outcome.get("status"),
                  reason=outcome.get("reason"), serial=args.serial)
    _emit({"mode": "live", **outcome, "state": pilot.state.to_dict()})
    return 0 if outcome["action"] == "completed" else 2


def build_streaming_invoker(serial: str, state: dict[str, Any], *, timeout_seconds: float = 300.0):
    """Like build_live_invoker, but streams the child's output line by line.

    Progress lines (``gacha_progress``) are mirrored into ``state`` so the
    dashboard can show the gacha loop (attempt N / max) while the boss gacha
    runs.  A stop request kills the child process tree immediately, so the
    user can interrupt even mid-gacha.
    """
    import threading

    def invoke(script: str, args: list[str]) -> dict:
        script_path = ROOT / "scripts" / script
        if not script_path.exists():
            raise FileNotFoundError(script)
        command = [sys.executable, str(script_path), "--serial", serial, *args]
        state["active_script"] = script
        state["gacha"] = None
        try:
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                       errors="replace",
                                       creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            lines: list[str] = []

            def _reader() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    lines.append(line.rstrip("\n"))
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict) and value.get("gacha_progress"):
                        state["gacha"] = {k: v for k, v in value.items() if k != "gacha_progress"}
                    if len(lines) > 4000:
                        del lines[:1000]

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()
            # ボスガチャは最大10試行を内部で行うため、通常タスクの
            # 5分上限では最終JSONを出す前に切れてしまう。進捗行だけを
            # 最終結果と誤認して再ガチャを無限反復しないよう、専用に
            # 長い上限を設定する。
            script_timeout = 900.0 if script == "task_boss_gacha_live.py" else timeout_seconds
            deadline = time.monotonic() + script_timeout
            timed_out = False
            stopped = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if state.get("stop_requested"):
                    stopped = True
                    _kill_process_tree(process.pid)
                    break
                time.sleep(0.2)
            else:
                timed_out = True
                _kill_process_tree(process.pid)
            reader_thread.join(timeout=5)
            if stopped:
                return {
                    "status": "safety_stop",
                    "reason": str(state.get("stop_reason") or "stopped_by_user"),
                }
            if timed_out:
                return {
                    "status": "safety_stop",
                    "reason": f"script_timeout:{script_timeout:.0f}s:{script}",
                }
            result = _last_json_object("\n".join(lines))
            if result is None:
                tail = " ".join(" ".join(lines).split())[-200:]
                return {"status": "safety_stop", "reason": f"no_json_output:{script}", "tail": tail}
            if not isinstance(result, dict):
                return {"status": "safety_stop", "reason": f"non_object_json:{script}"}
            return result
        finally:
            state["active_script"] = None

    return invoke


def run_web_server(args) -> int:
    """Run the auto-pilot behind a small dashboard with start/stop controls."""
    import threading

    from flask import Flask, Response, jsonify

    state_file = Path(args.state_file)
    ui_state: dict[str, Any] = {
        "stop_requested": False,
        "stop_reason": None,
        "active_script": None,
        "gacha": None,
    }
    pilot = AutoPilot(build_streaming_invoker(args.serial, ui_state), passports=args.passports,
                      avoid_hell=args.avoid_hell, battle_character_indices=args.battle_character_indices,
                      difficulty=args.difficulty, guild=args.guild,
                      allowed_bosses={"3": args.area3_boss, "5": args.area5_boss},
                      state_file=state_file)
    pilot.load_state()

    app = Flask(__name__)
    run_lock = threading.Lock()
    runner: dict[str, Any] = {"thread": None}

    def _run_loop() -> None:
        while True:
            outcome = pilot.step()
            if outcome["action"] in {"stopped", "completed"}:
                break

    def _start_run() -> None:
        if runner["thread"] is not None and runner["thread"].is_alive():
            return
        state = pilot.state
        if state.status == "completed":
            return
        if state.status in {"idle", "new"}:
            if state.passports <= 0:
                state.passports = args.passports
                state.max_passports = args.passports
            if state.passports <= 0:
                return
        state.status = "running"
        state.stop_reason = None
        pilot._stop_reason = None
        thread = threading.Thread(target=_run_loop, daemon=True)
        runner["thread"] = thread
        thread.start()

    # 親プロセスが更新・再起動された場合でも、実行中として保存された
    # フェーズから自動復帰する。停止済み/完了済みはユーザー操作なしに
    # 再開しない。
    if pilot.state.status == "running":
        _start_run()

    @app.get("/api/status")
    def api_status():
        payload = pilot.status()
        payload["running_thread"] = bool(runner["thread"] is not None
                                         and runner["thread"].is_alive())
        payload["active_script"] = ui_state.get("active_script")
        payload["gacha"] = ui_state.get("gacha")
        log = list(pilot.state.log[-100:])
        log.reverse()
        payload["recent_log"] = log
        return jsonify(payload)

    @app.post("/api/<command>")
    def api_command(command: str):
        with run_lock:
            if command == "start":
                ui_state["stop_requested"] = False
                ui_state["stop_reason"] = None
                _start_run()
            elif command == "stop":
                ui_state["stop_requested"] = True
                ui_state["stop_reason"] = "stopped_by_user"
                pilot.request_stop()
            elif command == "resume":
                ui_state["stop_requested"] = False
                ui_state["stop_reason"] = None
                pilot.resume()
                _start_run()
            elif command == "finish":
                ui_state["stop_requested"] = True
                ui_state["stop_reason"] = "finished_by_user"
                pilot.request_finish()
            else:
                return jsonify({"ok": False, "error": f"unknown_command:{command}"}), 400
        pilot.save_state()
        return jsonify({"ok": True, "status": pilot.state.status})

    @app.get("/api/screenshot")
    def api_screenshot():
        try:
            capture = AdbScreenCapture(serial=args.serial)
            frame = capture.capture(ROOT / "output" / "autopilot_dashboard.png")
            return Response(Path(frame.image_path).read_bytes(), mimetype="image/png")
        except Exception as exc:
            return jsonify({"error": f"screenshot_failed:{type(exc).__name__}"}), 500

    @app.get("/")
    def index():
        return DASHBOARD_HTML

    url = f"http://127.0.0.1:{args.port}"
    _emit({"mode": "web", "url": url, "state_file": str(state_file),
           "state": pilot.state.to_dict()})
    app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
    return 0


DASHBOARD_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>自動パイロット</title>
<style>
  body { font-family: "Segoe UI", "Hiragino Sans", sans-serif; margin: 16px;
         background: #101418; color: #e6e6e6; }
  h1 { font-size: 18px; }
  .grid { display: grid; grid-template-columns: 340px 1fr; gap: 16px; }
  .panel { background: #1a2027; border: 1px solid #2c3540; border-radius: 8px;
           padding: 12px; }
  .status { font-size: 20px; font-weight: 600; }
  .kv { display: grid; grid-template-columns: 130px 1fr; gap: 4px 8px;
        font-size: 13px; margin-top: 10px; }
  .kv b { color: #9fb2c8; font-weight: 500; }
  button { font-size: 15px; padding: 8px 18px; margin: 4px 6px 0 0; border: 0;
           border-radius: 6px; cursor: pointer; color: #fff; }
  #btn-start { background: #2e7d32; }
  #btn-stop  { background: #ef6c00; }
  #btn-resume{ background: #1565c0; }
  #btn-finish{ background: #c62828; }
  button:disabled { background: #37474f; cursor: default; }
  img#shot { width: 100%; border-radius: 6px; background: #000; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 3px 8px; border-bottom: 1px solid #2c3540;
           max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  th { color: #9fb2c8; position: sticky; top: 0; background: #1a2027; }
  .logbox { max-height: 420px; overflow-y: auto; }
  .t-running { color: #66bb6a; } .t-stopping { color: #ffa726; }
  .t-stopped { color: #ef5350; } .t-completed { color: #42a5f5; }
  .t-idle, .t-new { color: #9e9e9e; }
</style>
</head>
<body>
<h1>迷宮探索 自動パイロット</h1>
<div class="grid">
  <div class="panel">
    <div class="status" id="status">待機中</div>
    <div id="reason" style="font-size:12px;color:#ef9a9a;margin-top:4px;"></div>
    <div class="kv">
      <b>フェーズ</b><span id="phase">-</span>
      <b>ルート</b><span id="route">-</span>
      <b>ボス</b><span id="bosses">-</span>
      <b>護照</b><span id="passports">-</span>
      <b>勝利</b><span id="wins">-</span>
      <b>訪問済み</b><span id="tiles">-</span>
      <b>連敗</b><span id="defeats">-</span>
    </div>
    <div style="margin-top:14px;">
      <button id="btn-start">開始</button>
      <button id="btn-stop">停止</button>
      <button id="btn-resume">再開</button>
      <button id="btn-finish">終了</button>
    </div>
  </div>
  <div>
    <div class="panel" style="margin-bottom:16px;">
      <img id="shot" src="/api/screenshot?nocache=0" alt="screenshot">
    </div>
    <div class="panel logbox">
      <table>
        <thead><tr><th>#</th><th>アクション</th><th>状態</th><th>詳細</th></tr></thead>
        <tbody id="log"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
const STATUS_JA = { idle:"待機中", new:"待機中", running:"実行中", stopping:"停止中",
                   stopped:"停止中(再開可能)", completed:"完了" };
const $ = (id) => document.getElementById(id);

async function cmd(name) {
  await fetch("/api/" + name, { method: "POST" });
  refresh();
}
$("btn-start").onclick  = () => cmd("start");
$("btn-stop").onclick   = () => cmd("stop");
$("btn-resume").onclick = () => cmd("resume");
$("btn-finish").onclick = () => { if (confirm("終了しますか?")) cmd("finish"); };

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

async function refresh() {
  const res = await fetch("/api/status");
  const s = await res.json();
  const el = $("status");
  el.textContent = STATUS_JA[s.status] || s.status;
  el.className = "status t-" + (s.status || "idle");
  $("reason").textContent = s.stop_reason || "";
  $("phase").textContent = s.phase || "-";
  $("route").textContent = s.route_index + " / " + (s.route ? s.route.length : 0);
  $("bosses").textContent = Object.values(s.boss_names || {}).join(", ") || "-";
  $("passports").textContent = s.passports;
  $("wins").textContent = s.battles_won;
  $("tiles").textContent = s.tiles_visited;
  $("defeats").textContent = s.consecutive_defeats;
  const busy = s.running_thread;
  $("btn-start").disabled = busy || s.status === "completed";
  $("btn-stop").disabled  = !busy;
  $("btn-resume").disabled = busy || s.status === "completed" || s.status === "running";
  $("btn-finish").disabled = !busy;
  const rows = (s.recent_log || []).map((e, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + esc(e.action) + "</td><td>" +
    esc(e.status) + "</td><td title='" + esc(JSON.stringify(e.detail || {})) +
    "'>" + esc(JSON.stringify(e.detail || {})).slice(0, 120) + "</td></tr>");
  $("log").innerHTML = rows.join("");
}

let shotTick = 0;
setInterval(() => {
  shotTick++;
  $("shot").src = "/api/screenshot?nocache=" + shotTick;
}, 5000);

setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
