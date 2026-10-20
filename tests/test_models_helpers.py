"""Tests for models and option helpers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.crewmeister.api import (
    InvalidTransitionError,
    StampType,
    WorkStatus,
    derive_status,
    validate_transition,
)
from custom_components.crewmeister.helpers import (
    StampDefaults,
    absence_states,
    positive_int,
    stamp_defaults,
    update_interval_seconds,
)

from .conftest import make_stamp


@pytest.mark.parametrize(
    ("stamp_type", "status", "expected"),
    [
        ("START_WORK", "OPEN", WorkStatus.CLOCKED_IN),
        ("START_BREAK", "OPEN", WorkStatus.ON_BREAK),
        ("CLOCK_OUT", "OPEN", WorkStatus.CLOCKED_OUT),
        ("START_WORK", "CLOSED", WorkStatus.CLOCKED_OUT),
        ("START_BREAK", "INVALID", WorkStatus.CLOCKED_OUT),
    ],
)
def test_derive_status(stamp_type, status, expected) -> None:
    assert derive_status(make_stamp(stamp_type, status)) == expected


def test_derive_status_without_stamp() -> None:
    assert derive_status(None) == WorkStatus.CLOCKED_OUT


@pytest.mark.parametrize(
    ("stamp_type", "status", "reason"),
    [
        (StampType.START_WORK, WorkStatus.CLOCKED_IN, "already_clocked_in"),
        (StampType.START_BREAK, WorkStatus.ON_BREAK, "no_shift_to_pause"),
        (StampType.START_BREAK, WorkStatus.CLOCKED_OUT, "no_shift_to_pause"),
        (StampType.CLOCK_OUT, WorkStatus.CLOCKED_OUT, "no_shift_to_clock_out"),
    ],
)
def test_invalid_transitions(stamp_type, status, reason) -> None:
    with pytest.raises(InvalidTransitionError) as err:
        validate_transition(stamp_type, status)
    assert err.value.reason == reason


@pytest.mark.parametrize(
    ("stamp_type", "status"),
    [
        (StampType.START_WORK, WorkStatus.CLOCKED_OUT),
        (StampType.START_WORK, WorkStatus.ON_BREAK),
        (StampType.START_BREAK, WorkStatus.CLOCKED_IN),
        (StampType.CLOCK_OUT, WorkStatus.CLOCKED_IN),
        (StampType.CLOCK_OUT, WorkStatus.ON_BREAK),
    ],
)
def test_valid_transitions(stamp_type, status) -> None:
    validate_transition(stamp_type, status)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 1800),
        (600, 600),
        (600.0, 600),
        ("900", 900),
        ("00:30:00", 1800),
        ("20:00", 1200),
        (timedelta(minutes=15), 900),
        (10, 300),
        (99999, 3600),
        ("garbage", 1800),
    ],
)
def test_update_interval_seconds(value, expected) -> None:
    assert update_interval_seconds({"update_interval": value}) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["APPROVED", "PRE_APPROVED"]),
        ([], ["APPROVED", "PRE_APPROVED"]),
        ("REQUESTED", ["REQUESTED"]),
        (["REQUESTED", "APPROVED", "BOGUS"], ["APPROVED", "REQUESTED"]),
    ],
)
def test_absence_states(value, expected) -> None:
    assert absence_states({"absence_states": value}) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3), (3.0, 3), (" 4 ", 4), (0, None), (-1, None), (2.5, None), ("x", None), (True, None)],
)
def test_positive_int(value, expected) -> None:
    assert positive_int(value) == expected


def test_stamp_defaults() -> None:
    assert stamp_defaults({"stamp_note": "  Büro ", "stamp_time_account_id": "5"}) == StampDefaults(
        note="Büro", time_account_id=5
    )
    assert stamp_defaults({"stamp_note": "  "}) == StampDefaults()
