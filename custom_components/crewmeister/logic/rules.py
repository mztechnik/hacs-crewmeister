"""Decide what to stamp after a confirmed arrival or departure.

Arrival (T = time the arrival was detected):

- clocked out → clock in at T + arrival offset (working day, no absence, time window)
- on break → resume at T + arrival offset
- clocked in → nothing

Departure (stamp time = T - departure offset, never before the latest stamp):

- in the end of day period → clock out
- in the break window → start a break
- otherwise → never clock out; optionally ask, the question expires

All datetimes must be timezone aware and in local time; times of day (windows)
are interpreted in the time zone of the given datetimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from ..api import StampType, WorkStatus
from .config import StampMode

# Minimum distance to the latest stamp; Crewmeister needs ascending timestamps
STAMP_GAP = timedelta(minutes=1)
ZERO = timedelta(0)


class Outcome(StrEnum):
    """What the caller should do."""

    STAMP = "stamp"  # stamp ``stamp_type`` at ``at`` automatically
    ASK = "ask"  # ask with buttons for ``choices`` at ``at``
    WAIT = "wait"  # nothing yet, evaluate again at ``recheck_at``
    SKIP = "skip"  # nothing to do


class Reason(StrEnum):
    """Why a decision was made; shown in the automation sensor."""

    ARRIVED = "arrived"
    RETURNED = "returned"
    BREAK_WINDOW = "break_window"
    END_OF_DAY = "end_of_day"
    CATCH_UP = "catch_up"
    LEFT_DURING_WORK = "left_during_work"
    WAITING_OFFSET = "waiting_offset"
    WAITING_WINDOW = "waiting_window"
    WAITING_END_OF_DAY = "waiting_end_of_day"
    WAITING_CALENDAR = "waiting_calendar"
    DISABLED = "disabled"
    MODE_OFF = "mode_off"
    NOT_WORKDAY = "not_workday"
    ABSENT = "absent"
    OUTSIDE_WINDOW = "outside_window"
    SUPPRESSED = "suppressed"
    CARRIED_OVER = "carried_over"
    ALREADY_CLOCKED_IN = "already_clocked_in"
    ALREADY_CLOCKED_OUT = "already_clocked_out"
    ALREADY_ON_BREAK = "already_on_break"
    NO_RULE = "no_rule"


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of a rule evaluation."""

    outcome: Outcome
    reason: Reason
    stamp_type: StampType | None = None
    at: datetime | None = None
    # Buttons offered by ASK, the first is the suggestion
    choices: tuple[StampType, ...] = ()
    # ASK: when the question becomes invalid and is removed
    expires: datetime | None = None
    # Evaluate the departure (WAIT, or after ASK/SKIP: catch up) again at this time
    recheck_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Rules:
    """Stamping rules of one user."""

    arrival_mode: StampMode = StampMode.OFF
    break_mode: StampMode = StampMode.OFF
    end_of_day_mode: StampMode = StampMode.OFF
    arrival_offset: timedelta = ZERO
    departure_offset: timedelta = ZERO
    # Automatic clocking in only within this window
    window_start: time = time(5, 0)
    window_end: time = time(22, 0)
    # Leaving within this window starts a break; None disables it
    break_start: time | None = None
    break_end: time | None = None
    # End of day period starts at this time and/or when the target time is reached
    end_of_day_time: time | None = None
    end_of_day_on_target: bool = True
    # Ask when leaving outside the break window and end of day period
    ask_on_leave: bool = False
    ask_timeout: timedelta = timedelta(minutes=30)
    # Still away when the end of day period starts: clock out at the departure time
    catch_up: bool = True

    @property
    def break_window(self) -> tuple[time, time] | None:
        """Return the break window, ``None`` if not configured."""

        if self.break_start is None or self.break_end is None:
            return None
        return self.break_start, self.break_end


@dataclass(frozen=True, slots=True)
class Situation:
    """Facts at the time of the decision."""

    now: datetime
    status: WorkStatus
    latest_stamp_at: datetime | None = None
    enabled: bool = True
    # Why today is no working day ("weekday", "workday_sensor", "absence"), None if it is
    no_work_reason: str | None = None
    # When the target working time (incl. required break) is reached, if known
    target_reached_at: datetime | None = None
    # The user already clocked out today
    suppressed: bool = False
    # Present since before midnight without a new arrival (e.g. PC left running)
    carried_over: bool = False


def _at(day: date, at: time, like: datetime) -> datetime:
    return datetime.combine(day, at, tzinfo=like.tzinfo)


def _in_window(moment: datetime, start: time, end: time) -> bool:
    value = moment.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= value < end
    # Window across midnight
    return value >= start or value < end


def _after_latest(at: datetime, latest: datetime | None) -> datetime:
    if latest is not None and at < latest + STAMP_GAP:
        return latest + STAMP_GAP
    return at


def end_of_day_start(
    rules: Rules, situation: Situation, *, catch_up: bool = False
) -> datetime | None:
    """Return when today's end of day period starts, ``None`` if never.

    The earlier of the fixed time and the time the target is reached counts.
    During a break the target moves on with every minute. For ``catch_up`` it
    is therefore taken as it was when the break began; otherwise a user who
    left into a break and did not come back would never be clocked out.
    """

    candidates = []
    if rules.end_of_day_time is not None:
        candidates.append(_at(situation.now.date(), rules.end_of_day_time, situation.now))
    if rules.end_of_day_on_target and situation.target_reached_at is not None:
        target = situation.target_reached_at
        if (
            catch_up
            and situation.status == WorkStatus.ON_BREAK
            and situation.latest_stamp_at is not None
        ):
            target -= max(ZERO, situation.now - situation.latest_stamp_at)
        candidates.append(target)
    return min(candidates) if candidates else None


def _with_mode(
    mode: StampMode,
    stamp_type: StampType,
    at: datetime,
    reason: Reason,
    choices: tuple[StampType, ...],
    *,
    recheck_at: datetime | None = None,
) -> Decision:
    if mode == StampMode.AUTO:
        return Decision(Outcome.STAMP, reason, stamp_type, at, recheck_at=recheck_at)
    return Decision(Outcome.ASK, reason, stamp_type, at, choices=choices, recheck_at=recheck_at)


def on_arrival(rules: Rules, situation: Situation, arrived_at: datetime) -> Decision:
    """Decide what to do after arriving at work at ``arrived_at``."""

    now = situation.now
    if not situation.enabled:
        return Decision(Outcome.SKIP, Reason.DISABLED)
    if situation.status == WorkStatus.CLOCKED_IN:
        return Decision(Outcome.SKIP, Reason.ALREADY_CLOCKED_IN)

    at = _after_latest(arrived_at + rules.arrival_offset, situation.latest_stamp_at)

    if situation.status == WorkStatus.ON_BREAK:
        if rules.break_mode == StampMode.OFF:
            return Decision(Outcome.SKIP, Reason.MODE_OFF)
        if at > now:
            return Decision(
                Outcome.WAIT, Reason.WAITING_OFFSET, StampType.START_WORK, at, recheck_at=at
            )
        return _with_mode(
            rules.break_mode, StampType.START_WORK, at, Reason.RETURNED, (StampType.START_WORK,)
        )

    if rules.arrival_mode == StampMode.OFF:
        return Decision(Outcome.SKIP, Reason.MODE_OFF)
    if situation.no_work_reason == "absence":
        return Decision(Outcome.SKIP, Reason.ABSENT)
    if situation.no_work_reason is not None:
        return Decision(Outcome.SKIP, Reason.NOT_WORKDAY)

    window_start = _at(at.date(), rules.window_start, at)
    if not _in_window(at, rules.window_start, rules.window_end):
        if rules.window_start <= rules.window_end and at < window_start:
            # Too early: clock in when the window opens
            at = window_start
        else:
            return Decision(Outcome.SKIP, Reason.OUTSIDE_WINDOW)
    if at > now:
        reason = Reason.WAITING_WINDOW if at == window_start else Reason.WAITING_OFFSET
        return Decision(Outcome.WAIT, reason, StampType.START_WORK, at, recheck_at=at)
    if situation.suppressed:
        # Already clocked out today (e.g. back at the PC in the evening): only ask
        return Decision(
            Outcome.ASK,
            Reason.SUPPRESSED,
            StampType.START_WORK,
            at,
            choices=(StampType.START_WORK,),
        )
    if situation.carried_over:
        # No new arrival today, the sources just never reported "away": only ask
        return Decision(
            Outcome.ASK,
            Reason.CARRIED_OVER,
            StampType.START_WORK,
            at,
            choices=(StampType.START_WORK,),
        )
    return _with_mode(
        rules.arrival_mode, StampType.START_WORK, at, Reason.ARRIVED, (StampType.START_WORK,)
    )


def on_departure(
    rules: Rules, situation: Situation, left_at: datetime, *, catch_up: bool = False
) -> Decision:
    """Decide what to do after leaving work at ``left_at``.

    ``catch_up`` is set when the departure is evaluated again at ``recheck_at``
    while the user is still away; it is then treated as the end of the day.
    """

    now = situation.now
    if not situation.enabled:
        return Decision(Outcome.SKIP, Reason.DISABLED)
    if situation.status == WorkStatus.CLOCKED_OUT:
        return Decision(Outcome.SKIP, Reason.ALREADY_CLOCKED_OUT)

    at = min(_after_latest(left_at - rules.departure_offset, situation.latest_stamp_at), now)
    end_of_day = end_of_day_start(rules, situation, catch_up=catch_up)
    clocked_in = situation.status == WorkStatus.CLOCKED_IN
    clock_out_choices = (
        (StampType.CLOCK_OUT, StampType.START_BREAK) if clocked_in else (StampType.CLOCK_OUT,)
    )

    if catch_up:
        if rules.end_of_day_mode == StampMode.OFF or end_of_day is None:
            return Decision(Outcome.SKIP, Reason.NO_RULE)
        if now < end_of_day:
            return Decision(Outcome.WAIT, Reason.WAITING_END_OF_DAY, recheck_at=end_of_day)
        return _with_mode(
            rules.end_of_day_mode, StampType.CLOCK_OUT, at, Reason.CATCH_UP, clock_out_choices
        )

    if rules.end_of_day_mode != StampMode.OFF and end_of_day is not None:
        # The departure offset must not move a departure out of the period
        if at >= end_of_day or left_at >= end_of_day:
            return _with_mode(
                rules.end_of_day_mode, StampType.CLOCK_OUT, at, Reason.END_OF_DAY, clock_out_choices
            )
        if rules.catch_up and now >= end_of_day:
            # Left shortly before the period began and it began while the
            # departure was being confirmed: catch up right away
            return _with_mode(
                rules.end_of_day_mode, StampType.CLOCK_OUT, at, Reason.CATCH_UP, clock_out_choices
            )

    # Catch up at the end of the day if the user does not come back
    recheck_at = None
    if (
        rules.catch_up
        and rules.end_of_day_mode != StampMode.OFF
        and end_of_day is not None
        and end_of_day > now
    ):
        recheck_at = end_of_day

    window = rules.break_window
    if window is not None and rules.break_mode != StampMode.OFF and _in_window(at, *window):
        if not clocked_in:
            return Decision(Outcome.SKIP, Reason.ALREADY_ON_BREAK, recheck_at=recheck_at)
        return _with_mode(
            rules.break_mode,
            StampType.START_BREAK,
            at,
            Reason.BREAK_WINDOW,
            (StampType.START_BREAK, StampType.CLOCK_OUT),
            recheck_at=recheck_at,
        )

    if rules.ask_on_leave:
        choices = (
            (StampType.START_BREAK, StampType.CLOCK_OUT) if clocked_in else (StampType.CLOCK_OUT,)
        )
        return Decision(
            Outcome.ASK,
            Reason.LEFT_DURING_WORK,
            choices[0],
            at,
            choices=choices,
            expires=now + rules.ask_timeout,
            recheck_at=recheck_at,
        )
    return Decision(Outcome.SKIP, Reason.NO_RULE, recheck_at=recheck_at)
