"""Break check when clocking out (German ArbZG § 4 by default).

If the required break is missing, the user is asked how long the break was.
Without an answer the configured default is added.
"""

from __future__ import annotations

from datetime import timedelta

from .worktime import MIN_REST_BREAK, ZERO, DaySummary, required_break

# Durations offered as buttons
BREAK_CHOICES = (timedelta(minutes=15), timedelta(minutes=30), timedelta(minutes=45))
# Upper limit for a break added afterwards
MAX_ADDED_BREAK = timedelta(hours=2)


def missing_break(summary: DaySummary, after_6h: timedelta, after_9h: timedelta) -> timedelta:
    """Return how much of the required break is missing.

    Only rest breaks (at least 15 minutes each) count. Adding a break reduces
    the work time, so the requirement is checked against the reduced time too:
    e.g. 6 h 10 min without a break only needs 10 minutes to fall to 6 h.
    """

    required = required_break(summary.work, after_6h, after_9h)
    missing = max(ZERO, required - summary.rest_breaks)
    if missing <= ZERO:
        return ZERO
    # Smallest addition after which the remaining work time no longer needs more
    limit = max(missing, MIN_REST_BREAK)
    for step in range(int(limit.total_seconds() // 60) + 1):
        added = timedelta(minutes=step)
        need = required_break(summary.work - added, after_6h, after_9h)
        # An added break shorter than 15 minutes is no rest break
        counted = added if added >= MIN_REST_BREAK else ZERO
        if need <= ZERO or summary.rest_breaks + counted >= need:
            return added
    return missing


def break_choices(missing: timedelta, default: timedelta) -> list[timedelta]:
    """Return the durations offered as buttons, at least ``missing``.

    The default is always included; choices are sorted and unique.
    """

    suggested = clamp_break(max(default, missing))
    others = sorted({c for c in BREAK_CHOICES if c >= missing} - {suggested})
    if missing not in BREAK_CHOICES and clamp_break(missing) != suggested:
        others = sorted({clamp_break(missing), *others})
    return sorted({suggested, *others[:2]})


def clamp_break(duration: timedelta) -> timedelta:
    """Limit a break added afterwards to a sane range."""

    return max(ZERO, min(duration, MAX_ADDED_BREAK))
