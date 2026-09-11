from __future__ import annotations

from contracts import Correction, EducationEvent, EducationExtraction

from .repository import SQLiteRepository


class EducationMemoryAdapter:
    """Persist a validated education event into its dedicated memory class."""

    _MEMORY_TYPES = {"teaching": "semantic", "correction": "correction", "rule_candidate": "rule"}

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def ingest(self, event: EducationEvent, metadata: dict | None = None) -> str:
        memory_id = f"education:{event.event_id}"
        if not self._exists("education_events", event.event_id):
            self.repository.save_education_event({
                "id": event.event_id,
                "turn_id": event.turn_id,
                "event_type": event.event_type,
                "content": event.content,
                "source": event.source,
                "confidence": event.confidence,
                "applicable_conditions": event.applicable_conditions,
            })
        if not self._exists("memory_items", memory_id):
            self.repository.save_memory({
                "id": memory_id,
                "memory_type": self._MEMORY_TYPES[event.event_type],
                "content": {"text": event.content, "applicable_conditions": event.applicable_conditions, "education_event_id": event.event_id, "structured": metadata or {}},
                "source": event.source,
                "confidence": event.confidence,
                "turn_id": event.turn_id,
            })
        return memory_id

    def ingest_extraction(self, extraction: EducationExtraction, turn_id: str, event_id: str) -> str:
        """Persist only validated structured extraction output."""
        if extraction.event_type == "rule_candidate" and not extraction.rule_candidate:
            raise ValueError("rule_candidate extraction must contain rule_candidate")
        if extraction.event_type == "correction" and not extraction.correction:
            raise ValueError("correction extraction must contain correction")
        validated_correction = None
        if extraction.correction:
            correction_payload = dict(extraction.correction)
            correction_payload.setdefault("correction_id", f"correction:{event_id}")
            correction_payload.setdefault("turn_id", turn_id)
            validated_correction = Correction.model_validate(correction_payload)
        event = EducationEvent(
            event_id=event_id,
            turn_id=turn_id,
            event_type=extraction.event_type,
            content=extraction.content,
            source=extraction.source,
            confidence=extraction.confidence,
            applicable_conditions=extraction.applicable_conditions,
        )
        memory_id = self.ingest(event, metadata=extraction.model_dump(mode="json"))
        if extraction.event_type == "rule_candidate" and extraction.rule_candidate:
            candidate_id = f"rule:{event_id}"
            if not self._exists("rule_candidates", candidate_id):
                self.repository.save_rule_candidate({
                    "id": candidate_id,
                    "education_event_id": event_id,
                    "rule": extraction.rule_candidate,
                    "applicable_conditions": extraction.applicable_conditions,
                    "confidence": extraction.confidence,
                    "status": "candidate",
                })
        if validated_correction and not self._exists("corrections", validated_correction.correction_id):
            correction_row = validated_correction.model_dump()
            correction_row["id"] = correction_row.pop("correction_id")
            self.repository.save_correction(correction_row)
        return memory_id

    def _exists(self, table: str, item_id: str) -> bool:
        return self.repository.connection.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone() is not None
