"""ラビリンス操作の再利用可能な監査ログ。

ログは人間が読めるMarkdownと機械処理用JSONLの両方へ保存する。座標は
観測結果と結び付けて残し、後から固定スクリプトへ移管する材料にする。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OperationEvent:
    timestamp: str
    task: str
    purpose: str
    screen_before: str
    action: str
    coordinate: tuple[int, int] | None = None
    adb_serial: str | None = None
    outcome: str = ""
    screen_after: str = ""
    confidence: float | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OperationLogger:
    """Append operation events without performing any game input."""

    def __init__(self, jsonl_path: str | Path, markdown_path: str | Path | None = None) -> None:
        self.jsonl_path = Path(jsonl_path)
        self.markdown_path = Path(markdown_path) if markdown_path is not None else None

    def record(
        self,
        *,
        task: str,
        purpose: str,
        screen_before: str,
        action: str,
        outcome: str = "",
        screen_after: str = "",
        coordinate: tuple[int, int] | None = None,
        adb_serial: str | None = None,
        confidence: float | None = None,
        duration_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> OperationEvent:
        if not task.strip() or not purpose.strip() or not screen_before.strip() or not action.strip():
            raise ValueError("task, purpose, screen_before and action are required")
        if coordinate is not None and (len(coordinate) != 2 or any(not isinstance(v, int) for v in coordinate)):
            raise ValueError("coordinate must be an integer (x, y) pair")
        if adb_serial is not None and not adb_serial.strip():
            raise ValueError("adb_serial must not be empty")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        event = OperationEvent(
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            task=task,
            purpose=purpose,
            screen_before=screen_before,
            action=action,
            coordinate=coordinate,
            adb_serial=adb_serial,
            outcome=outcome,
            screen_after=screen_after,
            confidence=confidence,
            duration_ms=duration_ms,
            metadata=dict(metadata or {}),
        )
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        if self.markdown_path is not None:
            self.markdown_path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not self.markdown_path.exists()
            with self.markdown_path.open("a", encoding="utf-8") as stream:
                if is_new:
                    stream.write("# ラビリンス操作履歴\n\n")
                    stream.write("| 時刻 | タスク | 画面(前) | 目的 | 操作 | 座標 | 結果 | 画面(後) |\n")
                    stream.write("|---|---|---|---|---|---|---|---|\n")
                coord = "-" if event.coordinate is None else f"({event.coordinate[0]}, {event.coordinate[1]})"
                values = [event.timestamp, event.task, event.screen_before, event.purpose, event.action, coord, event.outcome, event.screen_after]
                stream.write("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |\n")
        return event


