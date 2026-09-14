"""操作ログと画面変化観測を使った待機時間の調整。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveWaitPolicy:
    """画面変化を検出した時点で次操作へ進む待機ポリシー。"""

    minimum_seconds: float = 0.30
    poll_seconds: float = 0.10
    timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.minimum_seconds < 0 or self.poll_seconds <= 0 or self.timeout_seconds < self.minimum_seconds:
            raise ValueError("待機時間の設定が不正です")

    def wait_for_change(
        self,
        previous_token: str | None,
        observe: Callable[[], str | None],
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> tuple[str | None, float]:
        """最小待機後、観測トークンが変わるまでポーリングする。"""
        started = time.monotonic()
        sleep_fn(self.minimum_seconds)
        token = observe()
        while token == previous_token and time.monotonic() - started < self.timeout_seconds:
            sleep_fn(self.poll_seconds)
            token = observe()
        return token, time.monotonic() - started

    def wait_for_change_checked(
        self,
        previous_token: str | None,
        observe: Callable[[], str | None],
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> tuple[str | None, float, bool]:
        """画面変化の有無を明示的に返す。空振り判定に使用する。"""
        token, elapsed = self.wait_for_change(previous_token, observe, sleep_fn=sleep_fn)
        return token, elapsed, token != previous_token


def wait_until_hidden(
    visible: Callable[[], bool],
    *,
    minimum_seconds: float = 0.15,
    poll_seconds: float = 0.08,
    timeout_seconds: float = 1.5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """特定UI要素が消えるまで確認する軽量待機。失敗時はFalse。"""
    if minimum_seconds < 0 or poll_seconds <= 0 or timeout_seconds < minimum_seconds:
        raise ValueError("待機時間の設定が不正です")
    started = time.monotonic()
    sleep_fn(minimum_seconds)
    while visible():
        if time.monotonic() - started >= timeout_seconds:
            return False
        sleep_fn(poll_seconds)
    return True


def wait_until_visible(
    visible: Callable[[], bool],
    *,
    minimum_seconds: float = 0.15,
    poll_seconds: float = 0.08,
    timeout_seconds: float = 3.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """特定UI要素が現れるまで確認する軽量待機。"""
    if minimum_seconds < 0 or poll_seconds <= 0 or timeout_seconds < minimum_seconds:
        raise ValueError("待機時間の設定が不正です")
    started = time.monotonic()
    sleep_fn(minimum_seconds)
    while not visible():
        if time.monotonic() - started >= timeout_seconds:
            return False
        sleep_fn(poll_seconds)
    return True


