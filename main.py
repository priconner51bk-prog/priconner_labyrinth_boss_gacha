"""GUI と CLI の両方からボスガチャを起動するエントリーポイント。"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent


def _run_mode(mode: str, forwarded: list[str]) -> int:
    module_name = {"debug": "scripts.debug_boss_gacha", "live": "scripts.task_boss_gacha_live"}[mode]
    module = importlib.import_module(module_name)
    sys.argv = [f"{module_name}.py", *forwarded]
    return int(module.main())


class BossGachaWindow:
    """実機処理を別プロセスで実行し、停止時は即時 kill する GUI。"""

    RESUME_SCREENS = (
        "guild_select", "guild_confirm", "bonus", "item_reward",
        "initial_char", "boss_map", "boss_detail", "withdraw_confirm",
    )

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ボスガチャ操作")
        self.root.geometry("700x560")
        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()

        form = ttk.Frame(root, padding=12)
        form.pack(fill="x")
        self.serial = self._entry(form, "ADB serial", "127.0.0.1:5555", 0)
        self.passports = self._entry(form, "パスポート枚数", "10", 1)
        self.guild = self._entry(form, "ギルド（任意）", "", 2)
        self.difficulty = self._entry(form, "難易度", "10", 3)
        self.area3 = self._entry(form, "エリア3 許容ボス", "", 4)
        self.area5 = self._entry(form, "エリア5 許容ボス", "", 5)
        ttk.Label(form, text="再開画面").grid(row=6, column=0, sticky="w", pady=3)
        self.resume_screen = ttk.Combobox(form, values=("", *self.RESUME_SCREENS), state="readonly", width=30)
        self.resume_screen.set("")
        self.resume_screen.grid(row=6, column=1, sticky="ew", pady=3)
        self.default_models = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="PaddleOCR 標準日本語モデル", variable=self.default_models).grid(row=7, column=1, sticky="w", pady=3)
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

    def _command(self, *, resume: bool = False) -> list[str]:
        serial, passports = self.serial.get().strip(), self.passports.get().strip()
        area3, area5 = self.area3.get().strip(), self.area5.get().strip()
        if not serial or not passports or not area3 or not area5:
            raise ValueError("ADB serial、パスポート枚数、エリア3/5のボス名を入力してください。")
        command = [sys.executable, "-u", str(ROOT / "scripts" / "task_boss_gacha_live.py"), "--execute",
                   "--serial", serial, "--passports", passports, "--difficulty", self.difficulty.get().strip() or "10",
                   "--area3-boss", area3, "--area5-boss", area5]
        if self.guild.get().strip():
            command += ["--guild", self.guild.get().strip()]
        if self.default_models.get():
            command.append("--default-models")
        if resume:
            screen = self.resume_screen.get().strip()
            if not screen:
                raise ValueError("再開する画面を選択してください。")
            command += ["--resume-screen", screen]
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
            self.output.see("end")
        self.output.configure(state="disabled")
        if self.process and self.process.poll() is not None:
            self.process = None
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.resume_button.configure(state="normal")
            self.status.configure(text="停止／終了。再開画面を選択できます。")
        self.root.after(100, self._drain_output)

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
