"""Small helpers shared by the assistant components."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from homeassistant.util import dt as dt_util

from ..api import WorkStatus
from ..logic.worktime import DaySummary

LOCATION_OFFICE = "office"
LOCATION_HOME_OFFICE = "home_office"
LOCATION_NONE = "none"
WORK_LOCATIONS = [LOCATION_OFFICE, LOCATION_HOME_OFFICE, LOCATION_NONE]


class StampResult(StrEnum):
    """Outcome of a stamp attempt."""

    DONE = "done"
    # Not needed or no longer valid, e.g. stamped elsewhere in the meantime
    SKIPPED = "skipped"
    # Crewmeister unreachable; queued (automatic) or reported (manual)
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


def status_key(summary: DaySummary) -> tuple[WorkStatus, str]:
    """Return a key that changes with every status change, also between equal states."""

    latest = summary.latest
    return (summary.status, iso(latest.timestamp) if latest else "")


def status_token(summary: DaySummary) -> str:
    """Return ``status_key`` as a string."""

    status, latest = status_key(summary)
    return f"{status.value}|{latest}"


def action_arg(at: datetime | None, expires: datetime | None = None) -> str | None:
    """Encode the stamp time and expiry of a notification button."""

    if at is None:
        return None
    arg = str(int(at.timestamp()))
    if expires is not None:
        arg += f"/{int(expires.timestamp())}"
    return arg


def parse_action_arg(value: str | None) -> tuple[datetime | None, datetime | None]:
    """Decode ``action_arg``; invalid parts become ``None``."""

    if not value:
        return None, None
    at_str, _, expires_str = value.partition("/")
    return _parse_epoch(at_str), _parse_epoch(expires_str)


def _parse_epoch(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dt_util.utc_from_timestamp(int(value))
    except (ValueError, OverflowError, OSError):
        return None


def iso(value: datetime | None) -> str | None:
    """Return ``value`` in ISO format, ``None`` if unset."""

    return value.isoformat() if value else None


def hm(value: datetime) -> str:
    """Return the local time of ``value`` as HH:MM."""

    return dt_util.as_local(value).strftime("%H:%M")


def day_hm(value: datetime | None) -> str:
    """Return HH:MM for today, otherwise DD.MM. HH:MM."""

    if value is None:
        return ""
    local = dt_util.as_local(value)
    if local.date() == dt_util.now().date():
        return local.strftime("%H:%M")
    return local.strftime("%d.%m. %H:%M")
