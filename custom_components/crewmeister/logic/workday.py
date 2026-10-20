"""Decide whether a day is a working day."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from enum import StrEnum

from ..api import Absence

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_WORKDAYS = ["mon", "tue", "wed", "thu", "fri"]


class NoWorkReason(StrEnum):
    """Why a day is not a working day."""

    WEEKDAY = "weekday"
    WORKDAY_SENSOR = "workday_sensor"
    ABSENCE = "absence"


def covers_full_day(absence: Absence, day: date) -> bool:
    """Return whether ``absence`` covers the whole ``day`` (not only half of it)."""

    if not absence.start <= day <= absence.end:
        return False
    if day == absence.start and absence.start_day_part == "AFTERNOON":
        return False
    return not (day == absence.end and absence.end_day_part == "MORNING")


def no_work_reason(
    day: date,
    workdays: Iterable[str],
    workday_sensor_on: bool | None,
    absences: Iterable[Absence],
) -> NoWorkReason | None:
    """Return why ``day`` is not a working day, ``None`` if it is one.

    ``workday_sensor_on`` is the state of an optional workday sensor (for example
    from the Workday integration, which knows public holidays); ``None`` if unused.
    """

    if WEEKDAYS[day.weekday()] not in set(workdays):
        return NoWorkReason.WEEKDAY
    if workday_sensor_on is False:
        return NoWorkReason.WORKDAY_SENSOR
    if any(covers_full_day(absence, day) for absence in absences):
        return NoWorkReason.ABSENCE
    return None
