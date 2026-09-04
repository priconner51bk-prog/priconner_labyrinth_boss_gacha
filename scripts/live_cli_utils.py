"""実機CLI共通の安全エラーメッセージ。"""

from __future__ import annotations

import subprocess


def screen_error_message(exc: BaseException, serial: str) -> str:
    """画面取得失敗を、復旧方法付きの短いメッセージへ変換する。"""
    if isinstance(exc, subprocess.CalledProcessError):
        return (
            f"ADB接続失敗: {serial} が見つかりません。"
            "BlueStacksのADBを起動し、adb connectで再接続してください。"
        )
    return f"画面取得失敗: {type(exc).__name__}: {exc}"


