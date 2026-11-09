"""Combine the sources telling that the user is absent (vacation, sickness) today.

Sources: absences from Crewmeister, an optional calendar (e.g. a private
vacation calendar) and an optional binary sensor or input boolean.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from ..api import Absence
from .workday import covers_full_day


class AbsenceSource(StrEnum):
    """Where an absence comes from."""

    CREWMEISTER = "crewmeister"
    CALENDAR = "calendar"
    SENSOR = "sensor"


@dataclass(frozen=True, slots=True)
class CalendarItem:
    """An event of a Home Assistant calendar.

    All day events have ``date`` values with an exclusive end, like Home Assistant
    calendars deliver them; other events have timezone aware datetimes.
    """

    summary: str
    start: date | datetime
    end: date | datetime


@dataclass(frozen=True, slots=True)
class AbsenceInfo:
    """Why the user is absent today."""

    source: AbsenceSource
    title: str | None = None


def calendar_covers_day(item: CalendarItem, day: date, work_start: time, work_end: time) -> bool:
    """Return whether ``item`` covers ``day``.

    An all day event must include the day. A timed event must cover the working
    time from ``work_start`` to ``work_end`` (e.g. a vacation entered as
    "Mon 00:00 - Fri 23:59").
    """

    if not isinstance(item.start, datetime) and not isinstance(item.end, datetime):
        return item.start <= day < item.end
    if not isinstance(item.start, datetime) or not isinstance(item.end, datetime):
        return False
    tz = item.start.tzinfo
    begin = datetime.combine(day, work_start, tzinfo=tz)
    end = datetime.combine(day, work_end, tzinfo=tz)
    if end <= begin:
        end += timedelta(days=1)
    return item.start <= begin and item.end >= end


def matching_calendar_item(
    items: Iterable[CalendarItem],
    day: date,
    keywords: Iterable[str],
    work_start: time,
    work_end: time,
) -> CalendarItem | None:
    """Return the first event covering ``day`` whose title contains a keyword.

    Without keywords every event covering the day counts.
    """

    wanted = [k.strip().casefold() for k in keywords if k.strip()]
    for item in items:
        if wanted and not any(k in item.summary.casefold() for k in wanted):
            continue
        if calendar_covers_day(item, day, work_start, work_end):
            return item
    return None


def absence_today(
    day: date,
    *,
    crewmeister: Iterable[tuple[Absence, str | None]] = (),
    calendar_item: CalendarItem | None = None,
    sensor_on: bool = False,
    sensor_name: str | None = None,
) -> AbsenceInfo | None:
    """Return why the user is absent on ``day``, ``None`` if not.

    ``crewmeister`` holds absences with their type name. Only full day
    absences count; half a day off still allows clocking in.
    """

    for absence, name in crewmeister:
        if covers_full_day(absence, day):
            return AbsenceInfo(AbsenceSource.CREWMEISTER, name)
    if calendar_item is not None:
        return AbsenceInfo(AbsenceSource.CALENDAR, calendar_item.summary or None)
    if sensor_on:
        return AbsenceInfo(AbsenceSource.SENSOR, sensor_name)
    return None
