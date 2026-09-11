from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts import DecisionRecord


class SQLiteRepository:
    """Small local persistence boundary for validated session records."""

    def __init__(self, path: str | Path, migration_path: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        migration = Path(migration_path) if migration_path is not None else Path(__file__).parents[2] / "migrations" / "001_memory.sql"
        self.connection.executescript(migration.read_text(encoding="utf-8"))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save_session(self, session_id: str, app_version: str, model_profile: str, started_at: str | None = None) -> None:
        self.connection.execute(
            "INSERT INTO sessions(id, started_at, app_version, model_profile) VALUES (?, ?, ?, ?)",
            (session_id, started_at or self._now(), app_version, model_profile),
        )
        self.connection.commit()

    def save_turn(self, turn: dict[str, Any]) -> None:
        required = ("id", "session_id", "turn_index", "source", "status", "started_at")
        missing = [key for key in required if key not in turn]
        if missing:
            raise ValueError(f"turn is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO turns(id, session_id, episode_id, turn_index, source, status, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(turn.get(key) for key in ("id", "session_id", "episode_id", "turn_index", "source", "status", "started_at", "ended_at")),
        )
        self.connection.commit()

    def save_transcript(self, transcript: dict[str, Any]) -> None:
        required = ("id", "turn_id", "role", "raw_text", "normalized_text", "confidence", "is_final", "model")
        missing = [key for key in required if key not in transcript]
        if missing:
            raise ValueError(f"transcript is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO transcripts(id, turn_id, role, raw_text, normalized_text, confidence, is_final, model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(transcript.get(key) for key in required) + (transcript.get("created_at") or self._now(),),
        )
        self.connection.commit()

    def get_transcript(self, transcript_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT id, turn_id, role, raw_text, normalized_text, confidence, is_final, model, created_at FROM transcripts WHERE id = ?",
            (transcript_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(zip(("id", "turn_id", "role", "raw_text", "normalized_text", "confidence", "is_final", "model", "created_at"), row))

    def save_education_event(self, event: dict[str, Any]) -> None:
        required = ("id", "turn_id", "event_type", "content", "source", "confidence")
        missing = [key for key in required if key not in event]
        if missing:
            raise ValueError(f"education event is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO education_events(id, turn_id, event_type, content, source, confidence, applicable_conditions_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event["id"], event["turn_id"], event["event_type"], event["content"], event["source"], event["confidence"], json.dumps(event.get("applicable_conditions", {}), ensure_ascii=False), event.get("created_at") or self._now()),
        )
        self.connection.commit()

    def save_rule_candidate(self, candidate: dict[str, Any]) -> None:
        required = ("id", "education_event_id", "rule", "confidence")
        missing = [key for key in required if key not in candidate]
        if missing:
            raise ValueError(f"rule candidate is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO rule_candidates(id, education_event_id, rule_json, applicable_conditions_json, confidence, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (candidate["id"], candidate["education_event_id"], json.dumps(candidate["rule"], ensure_ascii=False), json.dumps(candidate.get("applicable_conditions", {}), ensure_ascii=False), candidate["confidence"], candidate.get("status", "candidate"), candidate.get("created_at") or self._now()),
        )
        self.connection.commit()

    def review_rule_candidate(self, candidate_id: str, status: str, reviewer: str) -> None:
        """Apply an explicit human review and retain an immutable review row."""
        if status not in {"approved", "rejected"}:
            raise ValueError("rule review status must be approved or rejected")
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        row = self.connection.execute("SELECT status FROM rule_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise ValueError("rule candidate does not exist")
        if row[0] != "candidate":
            raise ValueError("rule candidate has already been reviewed")
        review_id = f"review:{candidate_id}:{status}:{self._now()}"
        self.connection.execute("UPDATE rule_candidates SET status = ? WHERE id = ?", (status, candidate_id))
        self.connection.execute(
            "INSERT INTO rule_candidate_reviews(id, rule_candidate_id, status, reviewer, created_at) VALUES (?, ?, ?, ?, ?)",
            (review_id, candidate_id, status, reviewer, self._now()),
        )
        self.connection.commit()

    def save_correction(self, correction: dict[str, Any]) -> None:
        required = ("id", "turn_id", "target_type", "before", "after", "reason")
        missing = [key for key in required if key not in correction]
        if missing:
            raise ValueError(f"correction is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO corrections(id, turn_id, target_type, before_json, after_json, reason, approved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (correction["id"], correction["turn_id"], correction["target_type"], json.dumps(correction["before"], ensure_ascii=False), json.dumps(correction["after"], ensure_ascii=False), correction["reason"], int(correction.get("approved", False)), correction.get("created_at") or self._now()),
        )
        self.connection.commit()

    def save_decision(self, decision: dict[str, Any]) -> None:
        contract_fields = ("decision_id", "state_id", "intent_id", "decision", "reason", "policy", "source", "confidence")
        validated = DecisionRecord.model_validate({key: decision[key] for key in contract_fields if key in decision})
        turn_id = decision.get("turn_id")
        self.connection.execute(
            "INSERT INTO decisions(id, turn_id, state_id, intent_id, decision, reason_json, policy, source, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (validated.decision_id, turn_id, validated.state_id, validated.intent_id, validated.decision, json.dumps(validated.reason, ensure_ascii=False), validated.policy, validated.source, validated.confidence, decision.get("created_at") or self._now()),
        )
        for index, statement in enumerate(validated.reason):
            self.connection.execute(
                "INSERT INTO decision_reasons(id, decision_id, reason_index, statement) VALUES (?, ?, ?, ?)",
                (f"{validated.decision_id}:{index}", validated.decision_id, index, statement),
            )
        self.connection.commit()

    def list_decisions(self, limit: int = 10000) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        fields = ("id", "turn_id", "state_id", "intent_id", "decision", "reason_json", "policy", "source", "confidence", "created_at")
        rows = self.connection.execute("SELECT " + ", ".join(fields) + " FROM decisions ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(zip(fields, row))
            item["reason"] = json.loads(item.pop("reason_json"))
            result.append(item)
        return result

    def save_memory(self, item: dict[str, Any]) -> None:
        required = ("id", "memory_type", "content", "source", "confidence")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(f"memory item is missing fields: {', '.join(missing)}")
        self.connection.execute(
            "INSERT INTO memory_items(id, memory_type, content_json, source, confidence, session_id, turn_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], item["memory_type"], json.dumps(item["content"], ensure_ascii=False), item["source"], item["confidence"], item.get("session_id"), item.get("turn_id"), item.get("created_at") or self._now()),
        )
        self.connection.commit()

    def search_memory(self, memory_type: str, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        allowed = {"short_term", "episodic", "semantic", "rule", "correction"}
        if memory_type not in allowed or limit < 1:
            return []
        rows = self.connection.execute(
            "SELECT id, memory_type, content_json, source, confidence, session_id, turn_id, created_at FROM memory_items WHERE memory_type = ? AND content_json LIKE ? ORDER BY created_at DESC LIMIT ?",
            (memory_type, f"%{query}%", limit),
        ).fetchall()
        fields = ("id", "memory_type", "content_json", "source", "confidence", "session_id", "turn_id", "created_at")
        result = []
        for row in rows:
            item = dict(zip(fields, row))
            item["content"] = json.loads(item.pop("content_json"))
            result.append(item)
        return result

    def search_transcripts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not query or limit < 1:
            return []
        rows = self.connection.execute(
            "SELECT id, turn_id, role, raw_text, normalized_text, confidence, is_final, model, created_at FROM transcripts WHERE raw_text LIKE ? OR normalized_text LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        fields = ("id", "turn_id", "role", "raw_text", "normalized_text", "confidence", "is_final", "model", "created_at")
        return [dict(zip(fields, row)) for row in rows]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
