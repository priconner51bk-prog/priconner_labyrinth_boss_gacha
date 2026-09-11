from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class GameState(Contract):
    state_id: str
    screen_id: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["opencv", "ocr", "fixture", "human"]
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict[str, Any] = Field(default_factory=dict)
    raw_observation: dict[str, Any] = Field(default_factory=dict)


class UserIntent(Contract):
    transcript_id: str
    command_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    intent_type: Literal["conversation", "education", "command", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["text", "fixture", "human"]


class DecisionRecord(Contract):
    decision_id: str
    state_id: str
    intent_id: str
    decision: str = Field(min_length=1)
    reason: list[str] = Field(min_length=1)
    policy: Literal["hard_rule", "score_rule", "observation_gate", "human"]
    source: Literal["rule_engine", "observation", "human", "fixture"]
    confidence: float = Field(ge=0.0, le=1.0)


class EducationEvent(Contract):
    event_id: str
    turn_id: str
    event_type: Literal["teaching", "correction", "rule_candidate"]
    content: str = Field(min_length=1)
    source: Literal["text", "human", "fixture"]
    confidence: float = Field(ge=0.0, le=1.0)
    applicable_conditions: dict[str, Any] = Field(default_factory=dict)


class EducationExtraction(Contract):
    """Structured user-provided learning data before persistent memory."""

    event_type: Literal["teaching", "correction", "rule_candidate"]
    content: str = Field(min_length=1)
    decision: str = ""
    reason: list[str] = Field(default_factory=list)
    rule_candidate: dict[str, Any] = Field(default_factory=dict)
    correction: dict[str, Any] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["text", "human", "fixture"] = "text"
    applicable_conditions: dict[str, Any] = Field(default_factory=dict)


class RuleCandidate(Contract):
    rule_id: str
    education_event_id: str
    rule: dict[str, Any] = Field(min_length=1)
    applicable_conditions: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["candidate", "approved", "rejected"] = "candidate"


class Correction(Contract):
    correction_id: str
    turn_id: str
    target_type: Literal["transcript", "intent", "decision", "rule"]
    before: dict[str, Any] = Field(min_length=1)
    after: dict[str, Any] = Field(min_length=1)
    reason: str = Field(min_length=1)
    approved: bool = False


class MemoryItem(Contract):
    memory_id: str
    memory_type: Literal["short_term", "episodic", "semantic", "rule", "correction"]
    content: dict[str, Any] = Field(min_length=1)
    source: Literal["text", "screen", "rule_engine", "human", "fixture"]
    confidence: float = Field(ge=0.0, le=1.0)
    session_id: str | None = None
    turn_id: str | None = None
