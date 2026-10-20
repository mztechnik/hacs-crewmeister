"""Typed models for Crewmeister API resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class StampType(StrEnum):
    """Stamp types supported by the Crewmeister API."""

    START_WORK = "START_WORK"
    START_BREAK = "START_BREAK"
    CLOCK_OUT = "CLOCK_OUT"


class StampStatus(StrEnum):
    """Status of a stamp as reported by the API."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVALID = "INVALID"


class WorkStatus(StrEnum):
    """Work status of a user derived from the latest stamp."""

    CLOCKED_IN = "clocked_in"
    ON_BREAK = "on_break"
    CLOCKED_OUT = "clocked_out"


class InvalidTransitionError(ValueError):
    """Raised when a stamp type is not allowed for the current work status."""

    def __init__(self, stamp_type: StampType, status: WorkStatus, reason: str) -> None:
        super().__init__(f"{stamp_type} not allowed while {status}: {reason}")
        self.stamp_type = stamp_type
        self.status = status
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CrewmeisterIdentity:
    """The authenticated user's identity."""

    user_id: int
    crew_id: int
    email: str | None = None
    full_name: str | None = None


@dataclass(frozen=True, slots=True)
class Stamp:
    """A time tracking stamp."""

    stamp_type: str | None
    status: str | None
    timestamp: datetime | None
    id: int | None = None
    user_id: int | None = None
    crew_id: int | None = None
    chain_start_stamp_id: int | None = None
    note: str | None = None
    location: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Stamp:
        """Create a stamp from an API payload."""

        return cls(
            stamp_type=data.get("stampType"),
            status=data.get("stampStatus"),
            timestamp=parse_datetime(data.get("timestamp")),
            id=_as_int(data.get("id")),
            user_id=_as_int(data.get("userId")),
            crew_id=_as_int(data.get("crewId")),
            chain_start_stamp_id=_as_int(data.get("chainStartStampId")),
            note=data.get("note"),
            location=data.get("location"),
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class Absence:
    """An absence (vacation, sickness, ...) of a user."""

    start: date
    end: date
    type_id: int | None
    state: str | None
    start_day_part: str | None = None
    end_day_part: str | None = None
    zone_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Absence | None:
        """Create an absence from an API payload, ``None`` if it is incomplete."""

        start = _parse_date(data.get("from"))
        end = _parse_date(data.get("to"))
        if start is None or end is None:
            return None
        zone_id = data.get("zoneId")
        return cls(
            start=start,
            end=end,
            type_id=_as_int(data.get("absenceType")),
            state=data.get("state"),
            start_day_part=_upper(data.get("fromDayPart")),
            end_day_part=_upper(data.get("toDayPart")),
            zone_id=zone_id if isinstance(zone_id, str) and zone_id else None,
            raw=data,
        )


def derive_status(stamp: Stamp | None) -> WorkStatus:
    """Derive the work status from the latest stamp."""

    if stamp is None or stamp.status != StampStatus.OPEN:
        return WorkStatus.CLOCKED_OUT
    if stamp.stamp_type == StampType.START_BREAK:
        return WorkStatus.ON_BREAK
    if stamp.stamp_type == StampType.START_WORK:
        return WorkStatus.CLOCKED_IN
    return WorkStatus.CLOCKED_OUT


def validate_transition(stamp_type: StampType, status: WorkStatus) -> None:
    """Raise ``InvalidTransitionError`` if ``stamp_type`` is not allowed in ``status``."""

    if stamp_type == StampType.START_WORK and status == WorkStatus.CLOCKED_IN:
        raise InvalidTransitionError(stamp_type, status, "already_clocked_in")
    if stamp_type == StampType.START_BREAK and status != WorkStatus.CLOCKED_IN:
        raise InvalidTransitionError(stamp_type, status, "no_shift_to_pause")
    if stamp_type == StampType.CLOCK_OUT and status == WorkStatus.CLOCKED_OUT:
        raise InvalidTransitionError(stamp_type, status, "no_shift_to_clock_out")


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp as returned by the API."""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _LOGGER.debug("Unable to parse timestamp: %s", value)
        return None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _upper(value: Any) -> str | None:
    return value.upper() if isinstance(value, str) and value else None
