"""State of the assistant that survives a restart of Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from homeassistant.util import dt as dt_util

from ..api import StampType
from ..logic.presence import PresenceState

STORAGE_VERSION = 1


@dataclass(slots=True)
class PendingStamp:
    """An automatic stamp that failed temporarily and is retried."""

    stamp_type: StampType
    at: datetime
    created: datetime
    location: str | None = None
    attempts: int = 0
    next_try: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable representation."""

        return {
            "stamp_type": self.stamp_type.value,
            "at": self.at.isoformat(),
            "created": self.created.isoformat(),
            "location": self.location,
            "attempts": self.attempts,
            "next_try": _iso(self.next_try),
        }

    @classmethod
    def from_dict(cls, data: Any) -> PendingStamp | None:
        """Restore an item saved by ``as_dict``, ``None`` if invalid."""

        if not isinstance(data, dict):
            return None
        try:
            stamp_type = StampType(data.get("stamp_type"))
        except ValueError:
            return None
        at = _parse(data.get("at"))
        created = _parse(data.get("created"))
        if at is None or created is None:
            return None
        return cls(
            stamp_type=stamp_type,
            at=at,
            created=created,
            location=data.get("location") if isinstance(data.get("location"), str) else None,
            attempts=int(data.get("attempts") or 0),
            next_try=_parse(data.get("next_try")),
        )


@dataclass(slots=True)
class BreakQuestion:
    """Open question how long the break of a finished shift was."""

    stamp_id: int
    default_minutes: int
    expires: datetime

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable representation."""

        return {
            "stamp_id": self.stamp_id,
            "default_minutes": self.default_minutes,
            "expires": self.expires.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> BreakQuestion | None:
        """Restore a question saved by ``as_dict``, ``None`` if invalid."""

        if not isinstance(data, dict):
            return None
        expires = _parse(data.get("expires"))
        try:
            stamp_id = int(data["stamp_id"])
            minutes = int(data["default_minutes"])
        except (KeyError, TypeError, ValueError):
            return None
        return cls(stamp_id, minutes, expires) if expires else None


@dataclass(slots=True)
class AssistantState:
    """Persisted state of the assistant of one Crewmeister account."""

    enabled: bool = True
    presence: PresenceState = field(default_factory=PresenceState)
    # Evaluate the last departure again at this time (catch up at end of day)
    departure_recheck_at: datetime | None = None
    # The recheck repeats a departure that could not be decided (Crewmeister
    # unreachable) instead of catching up at the end of the day
    departure_retry: bool = False
    # Time of the last departure, offered when clocking out was forgotten
    left_at: datetime | None = None
    # Where the user worked last ("office" / "home_office"), sent with stamps
    last_location: str | None = None
    queue: list[PendingStamp] = field(default_factory=list)
    # Presence question that expires (leaving during work)
    question_expires: datetime | None = None
    break_question: BreakQuestion | None = None
    snooze_until: datetime | None = None
    live_started_at: datetime | None = None
    # Status at which the user swiped the live display away
    live_dismissed: str | None = None
    # Last decision of the automatic stamping, shown in the automation sensor
    decision: dict[str, Any] = field(default_factory=dict)
    # Markers preventing duplicate notifications, e.g. {"max_work": "2026-10-19"}
    sent: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable representation."""

        return {
            "enabled": self.enabled,
            "presence": self.presence.as_dict(),
            "departure_recheck_at": _iso(self.departure_recheck_at),
            "departure_retry": self.departure_retry,
            "left_at": _iso(self.left_at),
            "last_location": self.last_location,
            "queue": [item.as_dict() for item in self.queue],
            "question_expires": _iso(self.question_expires),
            "break_question": self.break_question.as_dict() if self.break_question else None,
            "snooze_until": _iso(self.snooze_until),
            "live_started_at": _iso(self.live_started_at),
            "live_dismissed": self.live_dismissed,
            "decision": self.decision,
            "sent": self.sent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AssistantState:
        """Restore the state saved by ``as_dict`` (also by version 0.4/0.5)."""

        if not data:
            return cls()
        queue = [PendingStamp.from_dict(item) for item in data.get("queue") or []]
        return cls(
            enabled=bool(data.get("enabled", True)),
            presence=PresenceState.from_dict(data.get("presence")),
            departure_recheck_at=_parse(data.get("departure_recheck_at")),
            departure_retry=bool(data.get("departure_retry")),
            left_at=_parse(data.get("left_at")),
            last_location=data.get("last_location"),
            queue=[item for item in queue if item is not None],
            question_expires=_parse(data.get("question_expires")),
            break_question=BreakQuestion.from_dict(data.get("break_question")),
            snooze_until=_parse(data.get("snooze_until")),
            live_started_at=_parse(data.get("live_started_at")),
            live_dismissed=data.get("live_dismissed"),
            decision=dict(data.get("decision") or {}),
            sent=dict(data.get("sent") or {}),
        )


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return dt_util.parse_datetime(value)
