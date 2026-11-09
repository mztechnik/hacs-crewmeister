"""Turn entity states into a presence reading: at work, away or unknown.

An unavailable or unknown source never counts as "away". It gives no
information, so the last known presence is kept. This prevents false
departures when the companion app loses its connection or Home Assistant
restarts.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

UNKNOWN_STATES = frozenset({"unknown", "unavailable", "", "none"})
STATE_HOME = "home"
STATE_ON = "on"


class Reading(StrEnum):
    """What a source says about the presence at work."""

    PRESENT = "present"
    AWAY = "away"
    UNKNOWN = "unknown"


class Combine(StrEnum):
    """How several office sources are combined."""

    # Arrive as soon as one source reports present, leave once all report away
    ANY = "any"
    # Arrive once all sources report present, leave as soon as one reports away
    ALL = "all"


class Location(StrEnum):
    """Where the user works."""

    OFFICE = "office"
    HOME_OFFICE = "home_office"


def _known(state: str | None) -> bool:
    return state is not None and state.strip().lower() not in UNKNOWN_STATES


def zone_reading(person_state: str | None, in_work_zone: bool) -> Reading:
    """Return the reading of the zone source.

    ``in_work_zone`` tells whether the person is listed in one of the work zones.
    """

    if in_work_zone:
        return Reading.PRESENT
    return Reading.AWAY if _known(person_state) else Reading.UNKNOWN


def wifi_reading(state: str | None, ssids: Iterable[str]) -> Reading:
    """Return the reading of a companion app Wi-Fi sensor (SSID as state)."""

    if not _known(state):
        return Reading.UNKNOWN
    assert state is not None
    wanted = {ssid.strip().casefold() for ssid in ssids if ssid.strip()}
    return Reading.PRESENT if state.strip().casefold() in wanted else Reading.AWAY


def activity_reading(
    person_state: str | None,
    power_state: str | None,
    power_threshold: float,
    presence_states: Iterable[str | None],
    *,
    power_configured: bool,
) -> Reading:
    """Return the reading of the home office source (PC power draw, desk presence).

    Home office only counts while the person is at home. Without any known
    activity sensor the reading is unknown.
    """

    if _known(person_state) and person_state != STATE_HOME:
        return Reading.AWAY
    if not _known(person_state):
        return Reading.UNKNOWN

    readings: list[bool] = []
    if power_configured and _known(power_state):
        with suppress(ValueError):
            readings.append(float(power_state) > power_threshold)  # type: ignore[arg-type]
    readings.extend(state == STATE_ON for state in presence_states if _known(state))
    if not readings:
        return Reading.UNKNOWN
    return Reading.PRESENT if any(readings) else Reading.AWAY


def combine(readings: Iterable[Reading], mode: Combine = Combine.ANY) -> Reading:
    """Combine the readings of the configured office sources."""

    values = list(readings)
    if not values:
        return Reading.UNKNOWN
    if mode == Combine.ALL:
        if Reading.AWAY in values:
            return Reading.AWAY
        if all(value == Reading.PRESENT for value in values):
            return Reading.PRESENT
        return Reading.UNKNOWN
    if Reading.PRESENT in values:
        return Reading.PRESENT
    if all(value == Reading.AWAY for value in values):
        return Reading.AWAY
    return Reading.UNKNOWN


@dataclass(frozen=True, slots=True)
class WorkPresence:
    """Overall presence at work, combining office and home office."""

    reading: Reading
    location: Location | None


def work_presence(office: Reading | None, home_office: Reading | None) -> WorkPresence:
    """Combine office and home office readings; ``None`` means not configured.

    The office wins: being detected at the office, the PC at home does not matter.
    """

    if office == Reading.PRESENT:
        return WorkPresence(Reading.PRESENT, Location.OFFICE)
    if home_office == Reading.PRESENT:
        return WorkPresence(Reading.PRESENT, Location.HOME_OFFICE)
    configured = [r for r in (office, home_office) if r is not None]
    if configured and all(r == Reading.AWAY for r in configured):
        return WorkPresence(Reading.AWAY, None)
    return WorkPresence(Reading.UNKNOWN, None)
