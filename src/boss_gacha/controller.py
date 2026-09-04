"""対象ボス組み合わせの抽選・撤退判断を独立して扱う。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


HARD_MAX_ATTEMPTS = 10


@dataclass(frozen=True)
class BossGachaPolicy:
    target_bosses: Mapping[str, str]
    max_attempts: int = 10
    allowed_bosses: Mapping[str, Sequence[str]] | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.max_attempts > HARD_MAX_ATTEMPTS:
            raise ValueError(f"max_attempts must be <= {HARD_MAX_ATTEMPTS}")
        if not self.target_bosses:
            raise ValueError("target_bosses must not be empty")
        if self.allowed_bosses is not None and not self.allowed_bosses:
            raise ValueError("allowed_bosses must not be empty")

    @classmethod
    def from_json(cls, path: str | Path) -> "BossGachaPolicy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = data.get("allowed_bosses")
        return cls(
            target_bosses={str(k): str(v) for k, v in data["target_bosses"].items()},
            max_attempts=int(data.get("max_attempts", 10)),
            allowed_bosses={str(k): tuple(str(name) for name in names)
                           for k, names in allowed.items()}
            if isinstance(allowed, Mapping) else None,
        )


class BossGachaController:
    """画面操作を持たない純粋なボス組み合わせ判定器。"""

    def __init__(self, policy: BossGachaPolicy, attempts: int = 0) -> None:
        if attempts < 0:
            raise ValueError("attempts must be non-negative")
        self.policy = policy
        self.attempts = attempts

    def evaluate(self, boss_names: Mapping[str | int, str]) -> dict[str, Any]:
        self.attempts += 1
        observed = {str(k): str(v) for k, v in boss_names.items()}
        missing = sorted(set(self.policy.target_bosses) - set(observed))
        if missing:
            return {"status": "safety_stop", "reason": "boss_names_missing", "attempt": self.attempts}
        allowed = self.policy.allowed_bosses or {
            area: (expected,) for area, expected in self.policy.target_bosses.items()
        }
        mismatches = {
            area: {"expected": list(names), "observed": observed[area]}
            for area, names in allowed.items()
            if observed.get(area) not in names
        }
        if not mismatches:
            return {"status": "matched", "attempt": self.attempts}
        if self.attempts >= self.policy.max_attempts:
            return {"status": "max_attempts", "attempt": self.attempts, "mismatches": mismatches}
        return {"status": "withdraw_and_retry", "attempt": self.attempts, "mismatches": mismatches}
