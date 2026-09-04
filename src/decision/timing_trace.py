"""画面遷移の遅延を段階別に記録する軽量トレーサー。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterator


@dataclass(frozen=True)
class TimingEvent:
    timestamp: str
    stage: str
    duration_ms: float
    outcome: str = ""
    task: str = ""
    metadata: dict[str, Any] | None = None


class TimingTrace:
    """JSONLへ段階別の経過時間を書き出す。無効時の呼び出しコストも小さい。"""

    def __init__(self, path: str | Path | None = None, *, task: str = "") -> None:
        self.path = Path(path) if path is not None else None
        self.task = task

    def record(self, stage: str, duration_ms: float, *, outcome: str = "", **metadata: Any) -> TimingEvent:
        event = TimingEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            duration_ms=round(max(0.0, float(duration_ms)), 1),
            outcome=outcome,
            task=self.task,
            metadata=metadata or None,
        )
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    @contextmanager
    def measure(self, stage: str, **metadata: Any) -> Iterator[None]:
        started = time.perf_counter()
        outcome = "完了"
        try:
            yield
        except Exception:
            outcome = "例外"
            raise
        finally:
            self.record(stage, (time.perf_counter() - started) * 1000, outcome=outcome, **metadata)


NULL_TIMING_TRACE = TimingTrace()


