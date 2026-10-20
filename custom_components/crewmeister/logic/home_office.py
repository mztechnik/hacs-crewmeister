"""Detection of working from home based on activity signals.

A home office *session* starts once activity (PC power draw, desk presence) has
lasted ``activity_delay`` while the person is at home on a working day. It ends
after ``idle_after`` without activity. If activity resumes within the short break
window, the inactivity is reported as a break instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class HomeOfficeEventType(StrEnum):
    """What the detector observed."""

    START = "start"
    END = "end"
    BREAK = "break"


@dataclass(frozen=True, slots=True)
class HomeOfficeEvent:
    """A change of the home office session."""

    type: HomeOfficeEventType
    # START: begin of activity, END: begin of inactivity, BREAK: begin of the break
    at: datetime
    # BREAK only: when activity resumed
    until: datetime | None = None


@dataclass(slots=True)
class HomeOfficeState:
    """Session state; ``session_since`` and ``idle_since`` are persisted."""

    session_since: datetime | None = None
    idle_since: datetime | None = None
    activity_since: datetime | None = None

    @property
    def active(self) -> bool:
        """Return whether a home office session is running."""

        return self.session_since is not None


def advance(
    state: HomeOfficeState,
    active: bool,
    now: datetime,
    *,
    activity_delay: timedelta,
    idle_after: timedelta,
    short_break: timedelta,
    may_start: bool,
    earliest_start: datetime | None = None,
) -> HomeOfficeEvent | None:
    """Update ``state`` with the current activity and return what happened.

    ``may_start`` tells whether a session may start now (working day, time
    window). ``earliest_start`` clamps the backdated start, e.g. to the start of
    the time window. ``short_break`` > ``idle_after`` turns inactivity between
    the two into a break; the session then only ends after ``short_break``.
    """

    if active:
        if state.activity_since is None:
            state.activity_since = now
        if state.idle_since is not None:
            idle_start, state.idle_since = state.idle_since, None
            if idle_after <= now - idle_start <= short_break:
                return HomeOfficeEvent(HomeOfficeEventType.BREAK, idle_start, now)
            return None
        if (
            state.session_since is None
            and may_start
            and now - state.activity_since >= activity_delay
        ):
            start = state.activity_since
            if earliest_start is not None and earliest_start > start:
                start = earliest_start
            state.session_since = start
            return HomeOfficeEvent(HomeOfficeEventType.START, start)
        return None

    state.activity_since = None
    if state.session_since is None:
        return None
    if state.idle_since is None:
        state.idle_since = now
    if now - state.idle_since >= max(idle_after, short_break):
        idle_start = state.idle_since
        state.session_since = state.idle_since = None
        return HomeOfficeEvent(HomeOfficeEventType.END, idle_start)
    return None
