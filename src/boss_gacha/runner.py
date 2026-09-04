"""ボスガチャ実行ループ。入出力はアダプターとして注入する。"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from .controller import BossGachaController


class LiveSafetyStop(RuntimeError):
    """実機画面ガード不成立時の停止。"""


class BossGachaRunner:
    def __init__(
        self,
        controller: BossGachaController,
        *,
        begin_attempt: Callable[[], None],
        read_boss_names: Callable[[], Mapping[str | int, str]],
        withdraw: Callable[[], None],
        passport_count: Callable[[], int],
        safety_check: Callable[[], bool],
        timing_trace=None,
        phase_guard: Callable[[str], bool] | None = None,
        on_progress: Callable[[dict], None] | None = None,
    ) -> None:
        self.controller = controller
        self.begin_attempt = begin_attempt
        self.read_boss_names = read_boss_names
        self.withdraw = withdraw
        self.passport_count = passport_count
        self.safety_check = safety_check
        self.timing_trace = timing_trace
        self.phase_guard = phase_guard
        self.on_progress = on_progress

    @staticmethod
    def _summary(samples: list[float]) -> dict[str, float | int]:
        if not samples:
            return {"count": 0, "total_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(samples)
        def percentile(rate: float) -> float:
            index = min(len(ordered) - 1, int((len(ordered) - 1) * rate))
            return round(ordered[index], 1)
        return {
            "count": len(samples),
            "total_ms": round(sum(samples), 1),
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
            "max_ms": round(max(samples), 1),
        }

    def run(self) -> dict:
        phase_samples: dict[str, list[float]] = {}

        def measure(phase: str, callback):
            if self.phase_guard is not None:
                try:
                    allowed = bool(self.phase_guard(phase))
                except Exception as exc:
                    raise LiveSafetyStop(f"phase_guard_error:{phase}:{type(exc).__name__}") from exc
                if not allowed:
                    raise LiveSafetyStop(f"phase_guard_rejected:{phase}")
            started = time.perf_counter()
            try:
                value = callback()
            except LiveSafetyStop:
                raise
            except Exception as exc:
                # OCR/ADBの予期せぬ例外を上位へ漏らさず、次の入力を禁止する。
                raise LiveSafetyStop(f"phase_error:{phase}:{type(exc).__name__}") from exc
            phase_samples.setdefault(phase, []).append((time.perf_counter() - started) * 1000)
            if self.timing_trace is not None:
                self.timing_trace.record(f"boss_gacha:{phase}", phase_samples[phase][-1])
            return value

        try:
            return self._run_loop(phase_samples, measure)
        except LiveSafetyStop as exc:
            return {"status": "safety_stop", "reason": str(exc), "attempt": self.controller.attempts,
                    "timing_summary": {key: self._summary(value) for key, value in phase_samples.items()}}

    def _progress(self, **extra: Any) -> None:
        if self.on_progress is None:
            return
        payload = {
            "attempt": self.controller.attempts,
            "max_attempts": self.controller.policy.max_attempts,
        }
        payload.update(extra)
        try:
            self.on_progress(payload)
        except Exception:
            pass

    def _run_loop(self, phase_samples, measure):
        while self.controller.attempts < self.controller.policy.max_attempts:
            self._progress(phase="checking")
            safe = measure("safety_check", self.safety_check)
            passports = measure("passport_count", self.passport_count)
            if not safe or passports <= 0:
                return {"status": "safety_stop", "reason": "precondition_failed", "attempt": self.controller.attempts,
                        "timing_summary": {key: self._summary(value) for key, value in phase_samples.items()}}
            measure("begin_attempt", self.begin_attempt)
            self._progress(phase="reading_boss_names")
            names = measure("read_boss_names", self.read_boss_names)
            if names.get("_early_reject") == "true":
                measure("withdraw", self.withdraw)
                self._progress(phase="retry", reason="early_reject")
                continue
            result = measure("evaluate", lambda: self.controller.evaluate(names))
            # 判定根拠を保持し、OCR誤読時に撤退理由を後から監査できるようにする。
            result["boss_names"] = dict(names)
            result["timing_summary"] = {key: self._summary(value) for key, value in phase_samples.items()}
            if result["status"] == "matched":
                self._progress(phase="matched")
                return result
            if result["status"] == "max_attempts":
                # 最終回も対象外なら、次の誤操作を防ぐため撤退して終了する。
                measure("withdraw", self.withdraw)
                result["withdrawn"] = True
                result["timing_summary"] = {key: self._summary(value) for key, value in phase_samples.items()}
                return result
            if result["status"] == "safety_stop":
                return result
            self._progress(phase="retry", boss_names=dict(names))
            measure("withdraw", self.withdraw)
        return {"status": "max_attempts", "attempt": self.controller.attempts,
                "timing_summary": {key: self._summary(value) for key, value in phase_samples.items()}}
