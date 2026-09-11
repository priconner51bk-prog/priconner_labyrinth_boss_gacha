"""Deterministic boundary for execute -> verify -> repair -> replay cycles.

The live game executor is intentionally injected.  This module owns retry
counting and evidence contracts, but it never invents a screen or performs
an input by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class StepResult:
    task_id: str
    run_id: str
    step_id: str
    attempt_id: str
    screen_before: str | None
    state_before: Mapping[str, Any]
    action: Mapping[str, Any]
    expected: Mapping[str, Any]
    screen_after: str | None
    state_after: Mapping[str, Any]
    status: str
    reason_code: str = ""
    evidence: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    patch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state_before"] = dict(self.state_before)
        value["state_after"] = dict(self.state_after)
        value["action"] = dict(self.action)
        value["expected"] = dict(self.expected)
        return value


@dataclass(frozen=True)
class FailurePacket:
    task_id: str
    step_id: str
    attempt: int
    before: Mapping[str, Any]
    action: Mapping[str, Any]
    expected: Mapping[str, Any]
    observed: Mapping[str, Any]
    failure: Mapping[str, Any]
    previous_attempts: tuple[Mapping[str, Any], ...] = ()
    user_constraints: tuple[Mapping[str, Any], ...] = ()
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["before"] = dict(self.before)
        value["action"] = dict(self.action)
        value["expected"] = dict(self.expected)
        value["observed"] = dict(self.observed)
        value["failure"] = dict(self.failure)
        value["previous_attempts"] = [dict(item) for item in self.previous_attempts]
        value["user_constraints"] = [dict(item) for item in self.user_constraints]
        return value


def failure_signature(packet: FailurePacket) -> str:
    """Hash only normalized failure state, never volatile timestamps/paths."""
    normalized = {
        "task_id": packet.task_id,
        "step_id": packet.step_id,
        "before_screen": packet.before.get("screen_id"),
        "action": packet.action,
        "expected": packet.expected,
        "observed": packet.observed,
        "reason_code": packet.failure.get("reason_code"),
    }
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_repair_proposal(
    proposal: Mapping[str, Any],
    user_constraints: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Reject proposals that do not explicitly satisfy locked constraints.

    The repair boundary requires an explicit boolean check for every active
    USER_LOCKED instruction.  Missing checks are violations, not permission
    to continue.
    """
    active = [
        item for item in user_constraints
        if isinstance(item, Mapping)
        and item.get("active") is True
        and item.get("type") == "USER_LOCKED"
    ]
    checks = proposal.get("constraint_checks", {})
    if not isinstance(checks, Mapping):
        checks = {}
    violations = [
        str(item.get("id") or item.get("constraint") or "unnamed_constraint")
        for item in active
        if checks.get(str(item.get("id") or item.get("constraint") or "unnamed_constraint")) is not True
    ]
    if violations:
        return {"accepted": False, "reason": "CONSTRAINT_VIOLATION", "violations": violations}
    return {"accepted": True, "reason": "constraints_satisfied", "violations": []}


@dataclass
class RepairLoop:
    """Own one bounded repair cycle; all side effects are injected callbacks."""

    execute: Callable[[Mapping[str, Any] | None], StepResult]
    repair: Callable[[FailurePacket], Mapping[str, Any]]
    replay: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    apply_patch: Callable[[Mapping[str, Any]], None] | None = None
    max_attempts: int = 3
    user_constraints: list[Mapping[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def run(self) -> dict[str, Any]:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        proposal: Mapping[str, Any] | None = None
        signatures: dict[str, int] = {}
        patches: set[str] = set()
        for attempt in range(1, self.max_attempts + 1):
            result = self.execute(proposal)
            self.history.append(result.to_dict())
            if result.status == "success":
                return {"status": "success", "attempt": attempt, "history": list(self.history)}
            packet = FailurePacket(
                task_id=result.task_id,
                step_id=result.step_id,
                attempt=attempt,
                before={"screen_id": result.screen_before, "state": dict(result.state_before)},
                action=result.action,
                expected=result.expected,
                observed={"screen_id": result.screen_after, "state": dict(result.state_after)},
                failure={"reason_code": result.reason_code, "details": result.reason_code},
                previous_attempts=tuple(self.history[:-1]),
                user_constraints=tuple(self.user_constraints),
                evidence=result.evidence,
            )
            signature = failure_signature(packet)
            signatures[signature] = signatures.get(signature, 0) + 1
            self.history[-1]["failure_signature"] = signature
            if signatures[signature] >= 3:
                return {"status": "stopped", "reason": "repeated_failure_limit", "failure_packet": packet.to_dict(), "history": list(self.history)}
            proposal = dict(self.repair(packet))
            validation = validate_repair_proposal(proposal, self.user_constraints)
            if not validation["accepted"]:
                return {"status": "stopped", "reason": validation["reason"], "violations": validation["violations"], "failure_packet": packet.to_dict(), "history": list(self.history)}
            patch_id = str(proposal.get("patch_id", ""))
            if not patch_id or patch_id in patches:
                return {"status": "stopped", "reason": "duplicate_patch", "failure_packet": packet.to_dict(), "history": list(self.history)}
            patches.add(patch_id)
            replay_result = dict(self.replay(proposal))
            self.history[-1]["patch_id"] = patch_id
            self.history[-1]["replay_result"] = replay_result
            if replay_result.get("status") != "pass":
                return {"status": "stopped", "reason": "replay_failed", "failure_packet": packet.to_dict(), "history": list(self.history)}
            if self.apply_patch is not None:
                self.apply_patch(proposal)
        return {"status": "stopped", "reason": "retry_limit", "history": list(self.history)}
