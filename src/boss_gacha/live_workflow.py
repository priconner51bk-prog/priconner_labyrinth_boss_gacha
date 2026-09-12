"""実機ボスガチャの画面遷移を、判定器から分離して束ねる。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .runner import LiveSafetyStop


class LiveBossGachaWorkflow:
    """1試行分の定型操作を安全な画面境界へ接続する。

    ``tap`` は呼び出し側で画面ID・対象表示を検証してから1回だけADB入力を
    送る関数、``wait_screen`` は画面IDが現れるまでポーリングする関数です。
    したがって本クラス自身は座標を持たず、誤画面での入力を許しません。
    """

    def __init__(
        self,
        *,
        tap: Callable[[str, str], bool],
        wait_screen: Callable[[str], bool],
        read_boss_name: Callable[[str], str | None],
        guild_label: str = "フォレスティエ",
        verify_guild: Callable[[str], bool] | None = None,
    ) -> None:
        self.tap = tap
        self.wait_screen = wait_screen
        self.read_boss_name = read_boss_name
        self.guild_label = guild_label
        self.verify_guild = verify_guild

    def _tap_and_wait(self, screen: str, label: str, next_screen: str) -> None:
        if not self.tap(screen, label):
            raise LiveSafetyStop(f"tap_rejected:{screen}/{label}")
        if not self.wait_screen(next_screen):
            raise LiveSafetyStop(f"screen_transition_timeout:{screen}->{next_screen}")

    def _tap_and_wait_any(self, screen: str, label: str, next_screens: tuple[str, ...]) -> str:
        if not self.tap(screen, label):
            raise LiveSafetyStop(f"tap_rejected:{screen}/{label}")
        for candidate in next_screens:
            if self.wait_screen(candidate):
                return candidate
        raise LiveSafetyStop(f"screen_transition_timeout:{screen}->{','.join(next_screens)}")

    def begin_attempt(self, start_screen: str = "labyrinth_top") -> None:
        """ラビリンスTOPから出発し、初期キャラ画面まで進める。"""
        if start_screen == "quest_menu":
            self._tap_and_wait("quest_menu", "ラビリンス", "labyrinth_top")
            start_screen = "labyrinth_top"
        if start_screen == "withdraw_confirm":
            self._tap_and_wait("withdraw_confirm", "撤退確認OK", "labyrinth_top")
            start_screen = "labyrinth_top"
        if start_screen == "labyrinth_top":
            self._tap_and_wait("labyrinth_top", "出発", "guild_select")
        elif start_screen not in {"guild_select", "guild_confirm", "bonus", "initial_char", "boss_map", "boss_detail"}:
            raise LiveSafetyStop(f"resume_screen_not_supported:{start_screen}")
        if start_screen == "boss_map":
            return
        if start_screen == "boss_detail":
            return
        if start_screen in {"labyrinth_top", "guild_select"}:
            self._tap_and_wait("guild_select", self.guild_label, "guild_confirm")
            start_screen = "guild_confirm"
        if start_screen == "guild_select":
            start_screen = self._tap_and_wait_any("guild_select", "ギルド選択確認", ("bonus", "item_reward"))
        elif start_screen == "guild_confirm":
            start_screen = self._tap_and_wait_any("guild_confirm", "ギルド選択確認", ("bonus", "item_reward"))
        if start_screen in {"bonus", "item_reward"}:
            if start_screen == "bonus" and self.verify_guild is not None and not self.verify_guild(self.guild_label):
                raise LiveSafetyStop(f"guild_mismatch:{self.guild_label}")
            next_screen = self._tap_and_wait_any(start_screen, "閉じる", ("initial_char", "item_reward")) if start_screen == "bonus" else "item_reward"
            # Some versions show the item-reward dialog immediately after the
            # departure bonus. Close it before handing off to initial setup.
            if next_screen == "item_reward":
                self._tap_and_wait("item_reward", "閉じる", "initial_char")

    def read_boss_names(self, start_screen: str = "initial_char", target_left: str | None = None) -> Mapping[str, str]:
        """マップを開き、左→閉じる→右→閉じるの順でテンプレート判定する。"""
        if start_screen == "initial_char":
            self._tap_and_wait("initial_char", "マップ", "boss_map")
        elif start_screen not in {"boss_map", "boss_detail"}:
            raise LiveSafetyStop(f"boss_read_screen_not_supported:{start_screen}")
        if start_screen == "boss_detail":
            left = self.read_boss_name("left")
        else:
            self._tap_and_wait("boss_map", "左BOSS", "boss_detail")
            left = self.read_boss_name("left")
        if not left:
            raise LiveSafetyStop("boss_name_missing:left")
        self._tap_and_wait("boss_detail", "閉じる", "boss_map")
        if target_left is not None and left != target_left:
            # 左ボスだけで対象外と確定した場合は、右ボスを開かずに
            # runnerへ早期撤退を通知する。
            return {"3": left, "_early_reject": "true"}
        self._tap_and_wait("boss_map", "右BOSS", "boss_detail")
        right = self.read_boss_name("right")
        if not right:
            raise LiveSafetyStop("boss_name_missing:right")
        self._tap_and_wait("boss_detail", "閉じる", "boss_map")
        return {"3": left, "5": right}

    def withdraw(self) -> None:
        """対象外の試行を撤退し、次の試行開始地点へ戻す。"""
        self._tap_and_wait("boss_map", "撤退する", "withdraw_confirm")
        self._tap_and_wait("withdraw_confirm", "撤退確認OK", "labyrinth_top")

    def runner(self, controller, *, passport_count: Callable[[], int], safety_check: Callable[[], bool], timing_trace=None, phase_guard: Callable[[str], bool] | None = None, on_progress: Callable[[dict], None] | None = None):
        """この画面ワークフローを ``BossGachaRunner`` へ接続する。"""
        from .runner import BossGachaRunner

        return BossGachaRunner(
            controller,
            begin_attempt=self.begin_attempt,
            read_boss_names=self.read_boss_names,
            withdraw=self.withdraw,
            passport_count=passport_count,
            safety_check=safety_check,
            timing_trace=timing_trace,
            phase_guard=phase_guard,
            on_progress=on_progress,
        )
