"""実機CLI共通の安全エラーメッセージ。"""

from __future__ import annotations

import subprocess
import time
from typing import Callable, Iterable


def screen_error_message(exc: BaseException, serial: str) -> str:
    """画面取得失敗を、復旧方法付きの短いメッセージへ変換する。"""
    if isinstance(exc, subprocess.CalledProcessError):
        return (
            f"ADB接続失敗: {serial} が見つかりません。"
            "BlueStacksのADBを起動し、adb connectで再接続してください。"
        )
    return f"画面取得失敗: {type(exc).__name__}: {exc}"


def relaunch_game_from_title(serial: str) -> dict[str, object]:
    """タイトル画面の開始位置を1回だけタップする。"""
    try:
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "tap", "640", "670"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        return {"ok": False, "stage": "title_tap", "error": screen_error_message(exc, serial)}
    return {"ok": True, "stage": "title_tap"}


def advance_startup_screen(
    observe: Callable[[], str | None],
    tap_title: Callable[[], dict[str, object]],
    *,
    known_screens: Iterable[str],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    """起動画面を監視し、タイトルを一度だけ通過する。"""
    known = set(known_screens)
    sequence: list[str | None] = []
    title_taps = 0
    deadline = monotonic() + timeout_seconds
    while monotonic() <= deadline and len(sequence) < 120:
        screen = observe()
        sequence.append(screen)
        if screen == "title":
            if title_taps:
                return {"ok": False, "stop_reason": "title_reappeared", "title_tap_count": title_taps, "screen_sequence": sequence}
            result = tap_title()
            if not result.get("ok"):
                return {"ok": False, "stop_reason": "title_tap_failed", "title_tap_count": 0, "screen_sequence": sequence}
            title_taps = 1
        elif screen in known:
            return {"ok": True, "title_tap_count": title_taps, "screen_sequence": sequence}
        elif screen is None:
            if len(sequence) == 1:
                return {"ok": False, "stop_reason": "unknown_startup_screen", "title_tap_count": title_taps, "screen_sequence": sequence}
        elif screen in {"splash", "startup_splash", "launching"}:
            pass
        else:
            return {"ok": False, "stop_reason": "unknown_startup_screen", "title_tap_count": title_taps, "screen_sequence": sequence}
        sleep(0.1)
    return {"ok": False, "stop_reason": "startup_timeout", "title_tap_count": title_taps, "screen_sequence": sequence}


def advance_error_to_title(
    observe: Callable[[], str | None],
    title_button_visible: Callable[[], bool],
    tap_title_button: Callable[[], dict[str, object]],
    *,
    known_screens: Iterable[str],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    """起動エラー画面の「タイトルへ」を一度だけ実行する。"""
    known = set(known_screens)
    sequence: list[str | None] = []
    first = observe()
    sequence.append(first)
    if first != "startup_error":
        return {"ok": False, "stop_reason": "startup_error_not_confirmed", "title_button_tap_count": 0, "screen_sequence": sequence}
    if not title_button_visible():
        return {"ok": False, "stop_reason": "title_button_not_confirmed", "title_button_tap_count": 0, "screen_sequence": sequence}
    result = tap_title_button()
    if not result.get("ok"):
        return {"ok": False, "stop_reason": "title_button_tap_failed", "title_button_tap_count": 0, "screen_sequence": sequence}
    deadline = monotonic() + timeout_seconds
    while monotonic() <= deadline and len(sequence) < 120:
        screen = observe()
        sequence.append(screen)
        if screen == "startup_error":
            return {"ok": False, "stop_reason": "startup_error_reappeared", "title_button_tap_count": 1, "screen_sequence": sequence}
        if screen in known:
            return {"ok": True, "title_button_tap_count": 1, "screen_sequence": sequence}
        sleep(0.1)
    return {"ok": False, "stop_reason": "title_transition_timeout", "title_button_tap_count": 1, "screen_sequence": sequence}


