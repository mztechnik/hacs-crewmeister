"""Helpers to read the (possibly legacy-formatted) options of a config entry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .const import (
    ABSENCE_STATES,
    CONF_ABSENCE_STATES,
    CONF_STAMP_NOTE,
    CONF_STAMP_TIME_ACCOUNT_ID,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ABSENCE_STATES,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    MAX_UPDATE_INTERVAL_SECONDS,
    MIN_UPDATE_INTERVAL_SECONDS,
)


@dataclass(frozen=True, slots=True)
class StampDefaults:
    """Values applied to stamps that do not specify them explicitly."""

    note: str | None = None
    time_account_id: int | None = None


def update_interval_seconds(options: dict[str, Any]) -> int:
    """Return the clamped status polling interval in seconds."""

    value = options.get(CONF_UPDATE_INTERVAL)
    seconds: int | None = None
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = int(value)
    elif isinstance(value, str) and value.strip():
        # Older versions stored strings like "1800" or "00:30:00"
        try:
            seconds = int(float(value))
        except ValueError:
            seconds = _parse_colon_time(value.strip())

    if seconds is None:
        seconds = DEFAULT_UPDATE_INTERVAL_SECONDS
    return max(MIN_UPDATE_INTERVAL_SECONDS, min(MAX_UPDATE_INTERVAL_SECONDS, seconds))


def absence_states(options: dict[str, Any]) -> list[str]:
    """Return the absence states shown in the calendar."""

    value = options.get(CONF_ABSENCE_STATES)
    if isinstance(value, str):
        value = [value]
    states = sorted({s for s in value or () if s in ABSENCE_STATES})
    return states or list(DEFAULT_ABSENCE_STATES)


def stamp_defaults(options: dict[str, Any]) -> StampDefaults:
    """Return the stamp defaults configured in the options."""

    return StampDefaults(
        note=clean_note(options.get(CONF_STAMP_NOTE)),
        time_account_id=positive_int(options.get(CONF_STAMP_TIME_ACCOUNT_ID)),
    )


def clean_note(value: Any) -> str | None:
    """Return a stripped note or ``None`` if empty."""

    if isinstance(value, str):
        return value.strip() or None
    return None


def positive_int(value: Any) -> int | None:
    """Return ``value`` as a positive integer or ``None``."""

    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int) and value > 0:
        return value
    return None


def _parse_colon_time(value: str) -> int | None:
    """Parse ``MM:SS`` or ``HH:MM:SS`` strings into seconds."""

    try:
        numbers = [int(float(part)) for part in value.split(":")]
    except ValueError:
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None
