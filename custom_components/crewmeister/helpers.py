"""Shared helper utilities for the Crewmeister integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from .const import (
    DEFAULT_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL_SECONDS,
    MIN_UPDATE_INTERVAL_SECONDS,
)


DEFAULT_UPDATE_INTERVAL_SECONDS = int(DEFAULT_UPDATE_INTERVAL.total_seconds())


def _parse_colon_time(value: str) -> int | None:
    """Parse HH:MM or HH:MM:SS strings into seconds."""

    parts = value.split(":")
    if len(parts) not in {2, 3}:
        return None

    try:
        numbers = [int(float(part)) for part in parts]
    except ValueError:
        return None

    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds

    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def coerce_update_interval_seconds(value: Any) -> int:
    """Return a clamped polling interval in seconds."""

    seconds: int | None = None

    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
    elif isinstance(value, (int, float)):
        seconds = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                seconds = int(float(stripped))
            except ValueError:
                parsed = _parse_colon_time(stripped)
                if parsed is not None:
                    seconds = parsed

    if seconds is None:
        seconds = DEFAULT_UPDATE_INTERVAL_SECONDS

    return max(MIN_UPDATE_INTERVAL_SECONDS, min(MAX_UPDATE_INTERVAL_SECONDS, seconds))


def resolve_update_interval(value: Any) -> timedelta:
    """Return a sanitized ``timedelta`` for the polling interval."""

    return timedelta(seconds=coerce_update_interval_seconds(value))
