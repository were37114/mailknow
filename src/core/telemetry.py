"""Telemetry and feedback flywheel integration.

V5.2 spec:
- Data telemetry: scene execution, search, approval operations
- Feedback flywheel: 👍+0.1 / 👎-0.2+7day cooldown / 🔄 demote+float
- Already implemented in SceneRecommender, this module adds persistence
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TelemetryEvent(str, Enum):
    """Telemetry event types."""
    # Scene events
    SCENE_EXECUTED = "scene_executed"
    SCENE_DISMISSED = "scene_dismissed"
    SCENE_FEEDBACK = "scene_feedback"

    # Search events
    SEARCH_QUERY = "search_query"
    SEARCH_RESULT_CLICKED = "search_result_clicked"

    # Approval events
    APPROVAL_DETECTED = "approval_detected"
    APPROVAL_ACTION = "approval_action"
    APPROVAL_BATCH = "approval_batch"

    # Report events
    REPORT_GENERATED = "report_generated"
    REPORT_EXPORTED = "report_exported"
    REPORT_EDITED = "report_edited"

    # Sync events
    SYNC_COMPLETED = "sync_completed"
    SYNC_ERROR = "sync_error"

    # LLM events
    LLM_CALL = "llm_call"
    LLM_FALLBACK = "llm_fallback"
    BUDGET_DEGRADED = "budget_degraded"

    # Knowledge events
    KNOWLEDGE_QUERY = "knowledge_query"
    ENTITY_ALIGNED = "entity_aligned"


@dataclass
class TelemetryRecord:
    """A telemetry record."""
    event: str
    timestamp: str
    properties: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


class TelemetryCollector:
    """Collect and aggregate telemetry data.

    Features:
    - Event recording
    - Aggregation by type/time
    - Statistics reporting
    - Privacy-preserving (no PII)
    """

    def __init__(self, max_records: int = 10000):
        self.max_records = max_records
        self._records: List[TelemetryRecord] = []
        self._counters: Dict[str, int] = defaultdict(int)
        self._durations: Dict[str, List[float]] = defaultdict(list)

    def record(
        self,
        event: TelemetryEvent,
        properties: Optional[Dict[str, Any]] = None,
        duration_ms: float = 0.0,
    ) -> None:
        """Record a telemetry event."""
        # Sanitize properties (remove PII)
        sanitized = self._sanitize(properties or {})

        record = TelemetryRecord(
            event=event.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            properties=sanitized,
            duration_ms=duration_ms,
        )

        self._records.append(record)
        self._counters[event.value] += 1

        if duration_ms > 0:
            self._durations[event.value].append(duration_ms)

        # Trim if over limit
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

        logger.debug(f"Telemetry: {event.value}")

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get telemetry statistics for the last N hours."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - (hours * 3600)

        recent = [
            r for r in self._records
            if datetime.fromisoformat(r.timestamp).timestamp() > cutoff
        ]

        by_event: Dict[str, int] = defaultdict(int)
        for r in recent:
            by_event[r.event] += 1

        avg_durations: Dict[str, float] = {}
        for event_key, durations in self._durations.items():
            if durations:
                avg_durations[event_key] = sum(durations) / len(durations)

        return {
            "period_hours": hours,
            "total_events": len(recent),
            "by_event": dict(by_event),
            "avg_durations_ms": avg_durations,
            "counters": dict(self._counters),
        }

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent telemetry records."""
        return [
            {
                "event": r.event,
                "timestamp": r.timestamp,
                "properties": r.properties,
                "duration_ms": r.duration_ms,
            }
            for r in self._records[-limit:]
        ]

    def _sanitize(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Remove PII from properties."""
        pii_keys = {"email", "from", "to", "cc", "subject", "body", "content", "api_key", "token"}
        sanitized = {}
        for k, v in properties.items():
            if k.lower() in pii_keys:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        return sanitized


# Global instance
_telemetry: Optional[TelemetryCollector] = None


def get_telemetry() -> TelemetryCollector:
    """Get global telemetry collector."""
    global _telemetry
    if _telemetry is None:
        _telemetry = TelemetryCollector()
    return _telemetry
