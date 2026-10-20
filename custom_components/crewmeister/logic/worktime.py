"""Work and break time calculations based on a user's stamps."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
import itertools

from ..api import Stamp, StampStatus, StampType, WorkStatus, derive_status

ZERO = timedelta(0)
# ArbZG § 4: only breaks of at least 15 minutes count towards the required break
MIN_REST_BREAK = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class DaySummary:
    """Work and break time within one period (usually today) up to ``now``."""

    work: timedelta
    breaks: timedelta
    status: WorkStatus
    # Timestamp of the latest stamp, i.e. since when ``status`` applies
    status_since: datetime | None
    # First START_WORK of the current (or last) stamp chain
    shift_start: datetime | None
    # Latest stamp, used e.g. as reference for break corrections
    latest: Stamp | None
    now: datetime
    # Breaks that count as rest breaks under ArbZG § 4 (each at least 15 minutes);
    # a running break counts, it may still reach that length
    rest_breaks: timedelta = ZERO

    @property
    def work_since_break(self) -> timedelta:
        """Continuous work time since clocking in or ending the last break."""

        if self.status != WorkStatus.CLOCKED_IN or self.status_since is None:
            return ZERO
        return max(ZERO, self.now - self.status_since)

    @property
    def current_break(self) -> timedelta:
        """Duration of the running break."""

        if self.status != WorkStatus.ON_BREAK or self.status_since is None:
            return ZERO
        return max(ZERO, self.now - self.status_since)


def valid_stamps(stamps: Iterable[Stamp]) -> list[Stamp]:
    """Return usable stamps sorted ascending by timestamp."""

    types = {str(t) for t in StampType}
    return sorted(
        (
            s
            for s in stamps
            if s.timestamp is not None and s.stamp_type in types and s.status != StampStatus.INVALID
        ),
        key=lambda s: s.timestamp,  # type: ignore[arg-type,return-value]
    )


def summarize(stamps: Iterable[Stamp], now: datetime, period_start: datetime) -> DaySummary:
    """Sum up work and break time between ``period_start`` and ``now``.

    ``stamps`` may be in any order and may include stamps before ``period_start``;
    they are needed to know whether a shift was already running at the start.
    """

    ordered = valid_stamps(stamps)
    work = ZERO
    breaks = ZERO
    rest_breaks = ZERO

    def add(kind: str | None, start: datetime, end: datetime, *, running: bool = False) -> None:
        nonlocal work, breaks, rest_breaks
        full = end - start
        start = max(start, period_start)
        end = min(end, now)
        if end <= start:
            return
        if kind == StampType.START_WORK:
            work += end - start
        elif kind == StampType.START_BREAK:
            breaks += end - start
            if running or full >= MIN_REST_BREAK:
                rest_breaks += end - start

    for current, following in itertools.pairwise(ordered):
        add(current.stamp_type, current.timestamp, following.timestamp)  # type: ignore[arg-type]

    latest = ordered[-1] if ordered else None
    status = derive_status(latest)
    if latest is not None and status != WorkStatus.CLOCKED_OUT:
        add(latest.stamp_type, latest.timestamp, now, running=True)  # type: ignore[arg-type]

    shift_start = None
    for stamp in reversed(ordered):
        if stamp.stamp_type == StampType.CLOCK_OUT and stamp is not latest:
            break
        if stamp.stamp_type == StampType.START_WORK:
            shift_start = stamp.timestamp

    return DaySummary(
        work=work,
        breaks=breaks,
        status=status,
        status_since=latest.timestamp if latest else None,
        shift_start=shift_start,
        latest=latest,
        now=now,
        rest_breaks=rest_breaks,
    )


def required_break(work: timedelta, after_6h: timedelta, after_9h: timedelta) -> timedelta:
    """Return the minimum break for ``work`` time (German ArbZG § 4 by default)."""

    if work > timedelta(hours=9):
        return after_9h
    if work > timedelta(hours=6):
        return after_6h
    return ZERO


def expected_end(
    summary: DaySummary, target: timedelta, after_6h: timedelta, after_9h: timedelta
) -> datetime | None:
    """Return when ``target`` working time is reached including the required break.

    Already taken rest breaks count towards the required break; a missing part is
    added. The result may lie in the past if the target was exceeded. ``None`` if
    not working.
    """

    if summary.status == WorkStatus.CLOCKED_OUT:
        return None
    missing_break = max(ZERO, required_break(target, after_6h, after_9h) - summary.rest_breaks)
    return summary.now + (target - summary.work) + missing_break
