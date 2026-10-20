"""Conversion of Crewmeister absences into calendar events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_util

from .api import Absence, CrewmeisterClient

MIDDAY = time(12, 0)
DAY_START = time(0, 0)
DAY_END = time(23, 59, 59)


@dataclass(frozen=True, slots=True)
class AbsenceEntry:
    """An absence together with its calendar representation."""

    absence: Absence
    event: CalendarEvent


async def async_absences_to_events(
    client: CrewmeisterClient, absences: list[Absence]
) -> list[CalendarEvent]:
    """Return calendar events for ``absences``, sorted by start."""

    return [entry.event for entry in await async_absence_entries(client, absences)]


async def async_absence_entries(
    client: CrewmeisterClient, absences: list[Absence]
) -> list[AbsenceEntry]:
    """Return ``absences`` with their calendar events, sorted by start."""

    entries = []
    for absence in absences:
        summary = "Absence"
        if absence.type_id is not None:
            name = await client.async_get_absence_type_name(absence.type_id)
            summary = name or f"Absence {absence.type_id}"

        tz = _timezone(absence.zone_id)
        # A half day absence starts at noon or ends at noon
        start_time = MIDDAY if absence.start_day_part == "AFTERNOON" else DAY_START
        end_time = MIDDAY if absence.end_day_part == "MORNING" else DAY_END
        event = CalendarEvent(
            summary=summary,
            start=_combine(absence.start, start_time, tz),
            end=_combine(absence.end, end_time, tz),
            description=f"State: {absence.state or 'UNKNOWN'}",
        )
        entries.append(AbsenceEntry(absence, event))
    entries.sort(key=lambda entry: entry.event.start_datetime_local)
    return entries


def _timezone(zone_id: str | None) -> tzinfo:
    if zone_id:
        try:
            return ZoneInfo(zone_id)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt_util.get_default_time_zone()


def _combine(day: date, at: time, tz: tzinfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)
