"""Provenance events, parent-child artifact relationships, and transformations.

A provenance event records what happened to which inputs and produced which
outputs. Every transformation produces a new artifact and a new event; nothing
in the system rewrites an artifact in place, so the lineage of any result can
be reconstructed from the event graph alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trendsmapp.clock import utc_now
from trendsmapp.domain.identifiers import new_provenance_id

__all__ = ["ProvenanceCollector", "ProvenanceEvent", "TransformationRecord"]


@dataclass(frozen=True, slots=True)
class TransformationRecord:
    """One named transformation applied to an input artifact."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    software: str | None = None
    software_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-serializable mapping."""
        return {
            "name": self.name,
            "parameters": dict(self.parameters),
            "software": self.software,
            "software_version": self.software_version,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceEvent:
    """One immutable record of a transformation or ingestion step."""

    provenance_id: str
    event_type: str
    occurred_at: datetime
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    transformations: tuple[TransformationRecord, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the event as a JSON-serializable mapping."""
        return {
            "provenance_id": self.provenance_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "transformations": [item.as_dict() for item in self.transformations],
            "details": dict(self.details),
        }


class ProvenanceCollector:
    """Accumulates provenance events during a workflow execution."""

    def __init__(self) -> None:
        self._events: list[ProvenanceEvent] = []

    def record(
        self,
        event_type: str,
        *,
        input_artifact_ids: tuple[str, ...] = (),
        output_artifact_ids: tuple[str, ...] = (),
        transformations: tuple[TransformationRecord, ...] = (),
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> ProvenanceEvent:
        """Record one provenance event and return it."""
        event = ProvenanceEvent(
            provenance_id=new_provenance_id(),
            event_type=event_type,
            occurred_at=occurred_at or utc_now(),
            input_artifact_ids=input_artifact_ids,
            output_artifact_ids=output_artifact_ids,
            transformations=transformations,
            details=dict(details or {}),
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[ProvenanceEvent, ...]:
        """Return the recorded events in chronological recording order."""
        return tuple(self._events)

    def as_documents(self) -> list[dict[str, Any]]:
        """Return the recorded events as JSON-serializable mappings."""
        return [event.as_dict() for event in self._events]
