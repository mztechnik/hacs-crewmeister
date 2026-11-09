"""State machine turning presence readings into confirmed arrivals and departures.

::

    AWAY ──present──▶ ARRIVING ──confirmed──▶ PRESENT   (event ARRIVED at T)
     ▲                  │ away: discard          │ away
     │                  ▼                        ▼
     └──confirmed── LEAVING ◀────────────────────┘      (event LEFT at T)
                        │ present: discard

T is the time the change was first seen, so the confirmation delay filters
GPS jumps and Wi-Fi dropouts without shifting the stamp. An unknown reading
pauses the machine: nothing is confirmed or discarded until the sources report
again. The state is persisted, so a restart of Home Assistant continues where it
stopped, and a change that happened while it was down is detected on start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from .sources import Location, Reading, WorkPresence


class Phase(StrEnum):
    """Phase of the presence state machine."""

    AWAY = "away"
    ARRIVING = "arriving"
    PRESENT = "present"
    LEAVING = "leaving"


class EventType(StrEnum):
    """A confirmed change of the presence."""

    ARRIVED = "arrived"
    LEFT = "left"


@dataclass(frozen=True, slots=True)
class PresenceEvent:
    """A confirmed arrival or departure that happened at ``at``."""

    type: EventType
    at: datetime
    location: Location | None


@dataclass(slots=True)
class PresenceState:
    """Persisted state of the presence state machine."""

    # None until the first known reading; that one is taken over without an event,
    # so setting up the integration in the office does not stamp
    phase: Phase | None = None
    location: Location | None = None
    # Begin of the presence (also while ARRIVING)
    arrived_at: datetime | None = None
    # Begin of the absence (also while LEAVING)
    left_at: datetime | None = None
    # The automatic arrival has not been handled yet (e.g. waiting for the time window)
    arrival_open: bool = False
    # The departure may still be turned into clocking out (catch up at end of day)
    departure_open: bool = False
    # Day on which the user clocked out (manually or automatically); a later
    # arrival on the same day asks instead of clocking in automatically
    suppressed_on: date | None = field(default=None)

    @property
    def present(self) -> bool:
        """Return whether the user counts as present (confirmed or still leaving)."""

        return self.phase in (Phase.PRESENT, Phase.LEAVING)

    def suppressed(self, today: date) -> bool:
        """Return whether the user already clocked out today."""

        return self.suppressed_on == today

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable representation."""

        return {
            "phase": self.phase.value if self.phase else None,
            "location": self.location.value if self.location else None,
            "arrived_at": self.arrived_at.isoformat() if self.arrived_at else None,
            "left_at": self.left_at.isoformat() if self.left_at else None,
            "arrival_open": self.arrival_open,
            "departure_open": self.departure_open,
            "suppressed_on": self.suppressed_on.isoformat() if self.suppressed_on else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PresenceState:
        """Restore the state saved by ``as_dict``; invalid values are dropped."""

        if not data:
            return cls()
        return cls(
            phase=_enum(Phase, data.get("phase")),
            location=_enum(Location, data.get("location")),
            arrived_at=_datetime(data.get("arrived_at")),
            left_at=_datetime(data.get("left_at")),
            arrival_open=bool(data.get("arrival_open")),
            departure_open=bool(data.get("departure_open")),
            suppressed_on=_date(data.get("suppressed_on")),
        )


@dataclass(frozen=True, slots=True)
class Update:
    """Result of feeding a reading into the state machine."""

    event: PresenceEvent | None = None
    # When the pending change can be confirmed; check again at that time
    check_at: datetime | None = None
    # Whether the state changed and should be saved
    changed: bool = False


def advance(
    state: PresenceState,
    presence: WorkPresence,
    now: datetime,
    *,
    arrival_delay: timedelta,
    departure_delay: timedelta,
    changed_at: datetime | None = None,
) -> Update:
    """Feed the current ``presence`` into ``state`` and return what happened.

    ``changed_at`` is when the sources changed, if known and earlier than ``now``
    (e.g. ``last_changed`` after a restart); it becomes the time T of a new
    arrival or departure.
    """

    reading = presence.reading
    since = min(changed_at, now) if changed_at else now

    if reading == Reading.UNKNOWN:
        # No information: keep everything, confirm nothing
        return Update()

    if state.phase is None:
        state.phase = Phase.PRESENT if reading == Reading.PRESENT else Phase.AWAY
        state.location = presence.location
        if reading == Reading.PRESENT:
            state.arrived_at = since
        else:
            state.left_at = since
        return Update(changed=True)

    if reading == Reading.PRESENT:
        return _present(state, presence, now, since, arrival_delay)
    return _away(state, now, since, departure_delay)


def _present(
    state: PresenceState,
    presence: WorkPresence,
    now: datetime,
    since: datetime,
    delay: timedelta,
) -> Update:
    changed = False
    if presence.location != state.location:
        # E.g. from home office to the office without a confirmed departure
        state.location = presence.location
        changed = True

    if state.phase == Phase.AWAY:
        state.phase = Phase.ARRIVING
        state.arrived_at = since
        changed = True
    elif state.phase == Phase.LEAVING:
        # Back before the departure was confirmed
        state.phase = Phase.PRESENT
        return Update(changed=True)
    elif state.phase == Phase.PRESENT:
        return Update(changed=changed)

    assert state.arrived_at is not None
    confirm_at = state.arrived_at + delay
    if now < confirm_at:
        return Update(check_at=confirm_at, changed=changed)
    state.phase = Phase.PRESENT
    state.arrival_open = True
    state.departure_open = False
    return Update(
        event=PresenceEvent(EventType.ARRIVED, state.arrived_at, state.location), changed=True
    )


def _away(state: PresenceState, now: datetime, since: datetime, delay: timedelta) -> Update:
    if state.phase == Phase.PRESENT:
        state.phase = Phase.LEAVING
        state.left_at = since
    elif state.phase == Phase.ARRIVING:
        # Gone again before the arrival was confirmed
        state.phase = Phase.AWAY
        return Update(changed=True)
    elif state.phase == Phase.AWAY:
        return Update()

    assert state.left_at is not None
    confirm_at = state.left_at + delay
    if now < confirm_at:
        return Update(check_at=confirm_at, changed=True)
    location = state.location
    state.phase = Phase.AWAY
    state.location = None
    state.arrival_open = False
    state.departure_open = True
    return Update(event=PresenceEvent(EventType.LEFT, state.left_at, location), changed=True)


def _enum[E: StrEnum](kind: type[E], value: Any) -> E | None:
    try:
        return kind(value)
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
