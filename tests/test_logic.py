"""Tests for the Home Assistant independent logic."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from custom_components.crewmeister.api import Stamp, WorkStatus
from custom_components.crewmeister.logic.config import AssistantConfig, StampMode
from custom_components.crewmeister.logic.sources import Combine
from custom_components.crewmeister.logic.texts import format_duration, text
from custom_components.crewmeister.logic.workday import (
    NoWorkReason,
    covers_full_day,
    no_work_reason,
)
from custom_components.crewmeister.logic.worktime import expected_end, required_break, summarize

from .conftest import FakeBackend, make_absence

DAY = datetime(2026, 10, 19, tzinfo=UTC)


def _stamps(*entries: tuple[str, int, int]) -> FakeBackend:
    backend = FakeBackend()
    for stamp_type, hour, minute in entries:
        backend.add(stamp_type, DAY.replace(hour=hour, minute=minute))
    return backend


def test_summarize_finished_day() -> None:
    backend = _stamps(
        ("START_WORK", 8, 0), ("START_BREAK", 12, 0), ("START_WORK", 12, 30), ("CLOCK_OUT", 17, 0)
    )
    summary = summarize(backend.stamps, DAY.replace(hour=20), DAY)

    assert summary.work == timedelta(hours=8, minutes=30)
    assert summary.breaks == timedelta(minutes=30)
    assert summary.status == WorkStatus.CLOCKED_OUT
    assert summary.shift_start == DAY.replace(hour=8)
    assert summary.work_since_break == timedelta(0)


def test_summarize_running_shift() -> None:
    backend = _stamps(("START_WORK", 8, 0), ("START_BREAK", 12, 0), ("START_WORK", 12, 30))
    summary = summarize(backend.stamps, DAY.replace(hour=14), DAY)

    assert summary.work == timedelta(hours=5, minutes=30)
    assert summary.status == WorkStatus.CLOCKED_IN
    assert summary.work_since_break == timedelta(hours=1, minutes=30)
    assert summary.shift_start == DAY.replace(hour=8)


def test_summarize_running_break() -> None:
    backend = _stamps(("START_WORK", 8, 0), ("START_BREAK", 12, 0))
    summary = summarize(backend.stamps, DAY.replace(hour=12, minute=20), DAY)

    assert summary.status == WorkStatus.ON_BREAK
    assert summary.current_break == timedelta(minutes=20)
    assert summary.breaks == timedelta(minutes=20)


def test_summarize_clips_to_period() -> None:
    backend = FakeBackend()
    backend.add("START_WORK", DAY - timedelta(hours=2))
    backend.add("CLOCK_OUT", DAY + timedelta(hours=3))
    backend.add("START_WORK", DAY + timedelta(hours=8))
    summary = summarize(backend.stamps, DAY + timedelta(hours=9), DAY)

    assert summary.work == timedelta(hours=4)
    assert summary.shift_start == DAY + timedelta(hours=8)


def test_summarize_ignores_invalid_stamps() -> None:
    backend = _stamps(("START_WORK", 8, 0))
    invalid = Stamp.from_api(
        {"stampType": "CLOCK_OUT", "stampStatus": "INVALID", "timestamp": "2026-10-19T09:00:00Z"}
    )
    summary = summarize([*backend.stamps, invalid], DAY.replace(hour=10), DAY)

    assert summary.work == timedelta(hours=2)
    assert summary.status == WorkStatus.CLOCKED_IN


def test_summarize_without_stamps() -> None:
    summary = summarize([], DAY, DAY)
    assert summary.status == WorkStatus.CLOCKED_OUT
    assert summary.work == timedelta(0)
    assert summary.shift_start is None


@pytest.mark.parametrize(
    ("work", "expected"),
    [(6, 0), (6.1, 30), (9, 30), (9.1, 45)],
)
def test_required_break(work: float, expected: int) -> None:
    assert required_break(
        timedelta(hours=work), timedelta(minutes=30), timedelta(minutes=45)
    ) == timedelta(minutes=expected)


def test_covers_full_day() -> None:
    absence = make_absence("2026-10-19", "2026-10-21", fromDayPart="AFTERNOON", toDayPart="MORNING")
    assert not covers_full_day(absence, date(2026, 10, 19))
    assert covers_full_day(absence, date(2026, 10, 20))
    assert not covers_full_day(absence, date(2026, 10, 21))
    assert not covers_full_day(absence, date(2026, 10, 22))


def test_no_work_reason() -> None:
    monday, saturday = date(2026, 10, 19), date(2026, 10, 24)
    workdays = ["mon", "tue", "wed", "thu", "fri"]
    assert no_work_reason(monday, workdays, None, []) is None
    assert no_work_reason(saturday, workdays, None, []) == NoWorkReason.WEEKDAY
    assert no_work_reason(monday, workdays, False, []) == NoWorkReason.WORKDAY_SENSOR
    vacation = [make_absence("2026-10-19", "2026-10-19")]
    assert no_work_reason(monday, workdays, True, vacation) == NoWorkReason.ABSENCE


def test_config_defaults() -> None:
    config = AssistantConfig.from_options({})
    assert config == AssistantConfig()
    assert not config.presence_configured
    assert config.forgotten_check_time == time(7, 0)


def test_config_parsing() -> None:
    config = AssistantConfig.from_options(
        {
            "notify_targets": ["notify.mobile_app_a", "mobile_app_b"],
            "person": "person.max",
            "work_zones": ["zone.office"],
            "clock_in_mode": "auto",
            "end_of_day_mode": "bogus",
            "break_window_start": "11:30:00",
            "break_window_end": "13:30:00",
            "office_combine": "all",
            "absence_calendar": "calendar.urlaub",
            "absence_keywords": [" Urlaub ", ""],
            "arrival_delay": 3.0,
            "max_work_hours": 0,
            "break_reminder_after": 0,
            "forgotten_check_time": None,
            "reminder_time": "17:30:00",
            "wifi_ssids": [" Firma ", ""],
            "workdays": ["mon", "xyz"],
        }
    )
    assert config.notify_targets == ["mobile_app_a", "mobile_app_b"]
    assert config.presence_configured
    assert config.arrival_mode == StampMode.AUTO
    assert config.end_of_day_mode == StampMode.OFF
    assert config.break_window == (time(11, 30), time(13, 30))
    assert config.office_combine == Combine.ALL
    assert config.absence_calendar == "calendar.urlaub"
    assert config.absence_keywords == ["Urlaub"]
    assert config.arrival_delay == timedelta(minutes=3)
    assert config.max_work is None
    assert config.break_reminder_after is None
    assert config.forgotten_check_time is None
    assert config.reminder_time == time(17, 30)
    assert config.wifi_ssids == ["Firma"]
    assert config.workdays == ["mon"]


def test_texts() -> None:
    assert text("de", "btn_snooze", minutes=15) == "In 15 min erinnern"
    assert text("de-AT", "btn_clock_out") == "Ausstempeln"
    assert text("fr", "btn_clock_out") == "Clock out"
    assert format_duration(timedelta(hours=7, minutes=5)) == "7:05 h"


def test_expected_end() -> None:
    backend = _stamps(("START_WORK", 8, 0), ("START_BREAK", 12, 0), ("START_WORK", 12, 15))
    summary = summarize(backend.stamps, DAY.replace(hour=14), DAY)
    after_6h, after_9h = timedelta(minutes=30), timedelta(minutes=45)

    # 8 h target: 15 min of the 30 min break are still missing
    assert expected_end(summary, timedelta(hours=8), after_6h, after_9h) == DAY.replace(
        hour=16, minute=30
    )
    # 6 h target needs no break; already reached at 14:15 minus... in the past
    assert expected_end(summary, timedelta(hours=6), after_6h, after_9h) == DAY.replace(
        hour=14, minute=15
    )
    clocked_out = summarize(_stamps(("START_WORK", 8, 0), ("CLOCK_OUT", 9, 0)).stamps, DAY, DAY)
    assert expected_end(clocked_out, timedelta(hours=8), after_6h, after_9h) is None


def test_only_breaks_of_15_minutes_count_as_rest_breaks() -> None:
    backend = _stamps(
        ("START_WORK", 8, 0),
        ("START_BREAK", 10, 0),
        ("START_WORK", 10, 10),
        ("START_BREAK", 12, 0),
        ("START_WORK", 12, 20),
        ("START_BREAK", 15, 0),
    )
    summary = summarize(backend.stamps, DAY.replace(hour=15, minute=5), DAY)

    assert summary.breaks == timedelta(minutes=35)
    # The running break counts, it may still reach 15 minutes
    assert summary.rest_breaks == timedelta(minutes=25)
