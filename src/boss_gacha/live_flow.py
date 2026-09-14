"""実機ボスガチャの画面確認付きアクション境界。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class LiveActionResult:
    ok: bool
    reason: str = ""


class GuardedLiveActions:
    """画面IDと対象表示を確認してから、1操作だけ実行する。

    判定不能・画面不一致・対象非表示はすべて安全停止として返す。
    """

    def __init__(
        self,
        *,
        observe_screen: Callable[[], str | None],
        target_visible: Callable[[str], bool],
        tap: Callable[[str], None],
    ) -> None:
        self.observe_screen = observe_screen
        self.target_visible = target_visible
        self.tap = tap

    def tap_if_expected(self, screen_id: str, label: str) -> LiveActionResult:
        current = self.observe_screen()
        if current != screen_id:
            return LiveActionResult(False, f"安全停止: 想定画面外 {current!r}（期待 {screen_id!r}）")
        try:
            visible = bool(self.target_visible(label))
        except Exception as exc:
            return LiveActionResult(False, f"安全停止: 対象確認失敗 {label}: {type(exc).__name__}")
        if not visible:
            return LiveActionResult(False, f"安全停止: 対象非表示 {screen_id}/{label}")
        try:
            self.tap(label)
        except Exception as exc:
            return LiveActionResult(False, f"安全停止: タップ失敗 {label}: {type(exc).__name__}")
        return LiveActionResult(True, f"タップ完了: {screen_id}/{label}")


class BossGachaPhaseCoordinator:
    """ボスガチャ定型フェーズを画面ID・対象ラベルへ束縛する。"""

    PHASES: ClassVar[dict[str, tuple[str, str]]] = {
        "begin_attempt": ("labyrinth_top", "出発"),
        # 読み取りフェーズの入口は初期キャラ画面。ここからマップを開き、
        # 左→右の順でボス詳細を確認する。
        "read_boss_names": ("initial_char", "マップ"),
        "withdraw": ("boss_map", "撤退する"),
    }

    def __init__(self, actions: GuardedLiveActions) -> None:
        self.actions = actions
        self.last_failure: str | None = None

    def guard_phase(self, phase: str) -> bool:
        expected = self.PHASES.get(phase)
        if expected is None:
            # 判定・パスポート確認など、タップを伴わないフェーズは許可。
            return phase in {"safety_check", "passport_count", "evaluate"}
        result = self._check_only(*expected)
        if not result.ok:
            self.last_failure = result.reason
        return result.ok

    def _check_only(self, screen_id: str, label: str) -> LiveActionResult:
        current = self.actions.observe_screen()
        if current != screen_id:
            return LiveActionResult(False, f"安全停止: 想定画面外 {current!r}（期待 {screen_id!r}）")
        try:
            visible = bool(self.actions.target_visible(label))
        except Exception as exc:
            return LiveActionResult(False, f"安全停止: 対象確認失敗 {label}: {type(exc).__name__}")
        return LiveActionResult(visible, "" if visible else f"安全停止: 対象非表示 {screen_id}/{label}")
