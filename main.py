"""GUI と CLI の両方からボスガチャを起動するエントリーポイント。"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent


def _config_names(filename: str) -> tuple[str, ...]:
    try:
        data = json.loads((ROOT / "configs" / filename).read_text(encoding="utf-8"))
        bosses = sorted(data.get("bosses", []), key=lambda item: int(item.get("order", 10**9)))
        return tuple(str(item["name"]) for item in bosses)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _guild_names() -> tuple[str, ...]:
    try:
        data = json.loads((ROOT / "configs" / "labyrinth_guild_starting_members.json").read_text(encoding="utf-8"))
        guilds = data.get("guilds", {})
        if isinstance(guilds, dict):
            return tuple(str(name) for name in guilds)
    except (OSError, ValueError, TypeError):
        pass
    return ("美食殿", "フォレスティエ")


def _run_mode(mode: str, forwarded: list[str]) -> int:
    module_name = {"debug": "scripts.debug_boss_gacha", "live": "scripts.task_boss_gacha_live"}[mode]
    module = importlib.import_module(module_name)
    sys.argv = [f"{module_name}.py", *forwarded]
    return int(module.main())


class BossGachaWindow:
    """実機処理を別プロセスで実行し、停止時は即時 kill する GUI。"""

    GUILDS = _guild_names()
    DIFFICULTIES = tuple(str(value) for value in range(1, 11))
    AREA3_BOSSES = _config_names("boss_area3.json")
    AREA5_BOSSES = _config_names("boss_area5.json")
    RESUME_SCREENS = {
        "ギルド選択画面": "guild_select", "ギルド確認画面": "guild_confirm",
        "出発ボーナス": "bonus", "アイテム報酬": "item_reward",
        "初期キャラ画面": "initial_char", "ボス一覧マップ": "boss_map",
        "ボス詳細画面": "boss_detail", "撤退確認画面": "withdraw_confirm",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ボスガチャ操作")
        self.root.geometry("700x560")
        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()

        form = ttk.Frame(root, padding=12)
        form.pack(fill="x")
        self.serial = self._entry(form, "ADB serial", "127.0.0.1:5555", 0)
        self.passports = self._entry(form, "試行回数（1回1枚）", "100", 1)
        ttk.Label(form, text="ギルド").grid(row=2, column=0, sticky="w", pady=3)
        self.guild = ttk.Combobox(form, values=self.GUILDS, state="readonly", width=30)
        self.guild.set("美食殿")
        self.guild.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="難易度").grid(row=3, column=0, sticky="w", pady=3)
        self.difficulty = ttk.Combobox(form, values=self.DIFFICULTIES, state="readonly", width=30)
        self.difficulty.set("10")
        self.difficulty.grid(row=3, column=1, sticky="ew", pady=3)
        self.area3_vars = self._boss_checks(form, "エリア3 許容ボス", self.AREA3_BOSSES, 4, "ベノムサラマンドラ")
        self.area5_vars = self._boss_checks(form, "エリア5 許容ボス", self.AREA5_BOSSES, 5, "ゴブリンロード")
        ttk.Label(form, text="再開画面").grid(row=9, column=0, sticky="w", pady=3)
        self.resume_screen = ttk.Combobox(form, values=("", *self.RESUME_SCREENS), state="readonly", width=30)
        self.resume_screen.set("")
        self.resume_screen.grid(row=9, column=1, sticky="ew", pady=3)
        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(root, padding=(12, 0))
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="開始", command=self.start)
        self.start_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(buttons, text="停止（即時）", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.resume_button = ttk.Button(buttons, text="再開", command=self.resume, state="disabled")
        self.resume_button.pack(side="left", padx=6)

        self.status = ttk.Label(root, text="待機中", padding=(12, 8))
        self.status.pack(fill="x")
        self.output = tk.Text(root, height=20, state="disabled", wrap="none")
        self.output.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.root.after(100, self._drain_output)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _entry(self, parent: ttk.Frame, label: str, value: str, row: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, width=32)
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        return entry

    def _boss_checks(self, parent: ttk.Frame, label: str, names: tuple[str, ...], row: int, default: str) -> dict[str, tk.BooleanVar]:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=3)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky="w", pady=3)
        variables: dict[str, tk.BooleanVar] = {}
        for index, name in enumerate(names):
            variable = tk.BooleanVar(value=name == default)
            variables[name] = variable
            ttk.Checkbutton(frame, text=name, variable=variable).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12), pady=1)
        return variables

    def _command(self, *, resume: bool = False) -> list[str]:
        serial, passports = self.serial.get().strip(), self.passports.get().strip()
        area3 = [name for name, variable in self.area3_vars.items() if variable.get()]
        area5 = [name for name, variable in self.area5_vars.items() if variable.get()]
        if not serial or not passports or not area3 or not area5:
            raise ValueError("ADB serial、パスポート枚数、エリア3/5のボス名を入力してください。")
        command = [sys.executable, "-u", str(ROOT / "scripts" / "task_boss_gacha_live.py"), "--execute",
                   "--serial", serial, "--passports", passports, "--difficulty", self.difficulty.get().strip() or "10",
                   "--area3-boss", area3[0], "--area5-boss", area5[0], "--guild", self.guild.get().strip()]
        for name in area3[1:]:
            command += ["--area3-boss", name]
        for name in area5[1:]:
            command += ["--area5-boss", name]
        # OCRはこのプロジェクトで評価済みのPP-OCRv4標準モデルに固定する。
        command.append("--default-models")
        if resume:
            screen_label = self.resume_screen.get().strip()
            if not screen_label:
                raise ValueError("再開する画面を選択してください。")
            command += ["--resume-screen", self.RESUME_SCREENS.get(screen_label, screen_label)]
        return command

    def start(self) -> None:
        self._launch(resume=False)

    def resume(self) -> None:
        self._launch(resume=True)

    def _launch(self, *, resume: bool) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("実行中", "すでに実行中です。")
            return
        try:
            command = self._command(resume=resume)
        except ValueError as exc:
            messagebox.showerror("入力エラー", str(exc))
            return
        action = "再開" if resume else "開始"
        if not messagebox.askyesno(
            "ADB入力の確認",
            f"BlueStacks にADB入力を送信してガチャを{action}します。\n\n"
            "対象画面・ボス名・パスポート枚数を確認しましたか？",
        ):
            self.status.configure(text="キャンセルしました")
            return
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT), environment.get("PYTHONPATH", "")))
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.resume_button.configure(state="disabled")
        self.status.configure(text="実行中" if not resume else "再開中")
        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._watch_process, args=(self.process,), daemon=True).start()

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self.output_queue.put(line.rstrip())

    def _watch_process(self, process: subprocess.Popen[str]) -> None:
        self.output_queue.put(f"[終了] exit code: {process.wait()}")

    def _drain_output(self) -> None:
        self.output.configure(state="normal")
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            self.output.insert("end", line + "\n")
            self._update_status_from_output(line)
            self.output.see("end")
        self.output.configure(state="disabled")
        if self.process and self.process.poll() is not None:
            self.process = None
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.resume_button.configure(state="normal")
            if self.status.cget("text") in {"実行中", "再開中", "停止処理中"}:
                self.status.configure(text="停止（手動または異常終了）／再開可能")
        self.root.after(100, self._drain_output)

    def _update_status_from_output(self, line: str) -> None:
        """CLIの最終JSONを、人が見分けやすい3分類で表示する。"""
        try:
            payload = json.loads(line)
        except ValueError:
            return
        labels = {
            "matched": "成功：対象ボスの組み合わせに一致",
            "max_attempts": f"失敗：{payload.get('max_attempts', 100)}回の試行上限に到達",
            "safety_stop": "停止：安全停止（入力を継続しません）",
        }
        label = labels.get(payload.get("status"))
        if label:
            self.status.configure(text=label)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.output_queue.put("[停止] 即時停止を実行しました。")
            self.status.configure(text="停止処理中")

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.root.destroy()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"debug", "live"} and any(
        option in {"-h", "--help"} for option in sys.argv[2:]
    ):
        return _run_mode(sys.argv[1], sys.argv[2:])
    parser = argparse.ArgumentParser(description="ボスガチャ GUI / CLI ランチャー")
    parser.add_argument("mode", nargs="?", choices=("debug", "live"), help="CLI モード。省略すると GUI を起動")
    args, forwarded = parser.parse_known_args()
    if args.mode:
        return _run_mode(args.mode, forwarded)
    root = tk.Tk()
    BossGachaWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
