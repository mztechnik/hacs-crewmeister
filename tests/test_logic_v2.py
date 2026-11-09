"""Tests for the V2 presence logic: sources, state machine, rules, absences, breaks."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.crewmeister.api import StampType, WorkStatus
from custom_components.crewmeister.logic.absence import (
    AbsenceSource,
    CalendarItem,
    absence_today,
    calendar_covers_day,
    matching_calendar_item,
)
from custom_components.crewmeister.logic.breaks import break_choices, missing_break
from custom_components.crewmeister.logic.config import StampMode
from custom_components.crewmeister.logic.presence import (
    EventType,
    Phase,
    PresenceState,
    advance,
)
from custom_components.crewmeister.logic.rules import (
    Outcome,
    Reason,
    Rules,
    Situation,
    end_of_day_start,
    on_arrival,
    on_departure,
)
from custom_components.crewmeister.logic.sources import (
    Combine,
    Location,
    Reading,
    WorkPresence,
    activity_reading,
    combine,
    wifi_reading,
    work_presence,
    zone_reading,
)
from custom_components.crewmeister.logic.worktime import DaySummary

from .conftest import make_absence

TZ = ZoneInfo("Europe/Berlin")
DAY = date(2026, 11, 9)  # Monday
MIN = timedelta(minutes=1)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


PRESENT = WorkPresence(Reading.PRESENT, Location.OFFICE)
AWAY = WorkPresence(Reading.AWAY, None)
UNKNOWN = WorkPresence(Reading.UNKNOWN, None)
DELAYS = {"arrival_delay": timedelta(minutes=2), "departure_delay": timedelta(minutes=10)}


# ---------------------------------------------------------------------- sources


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Buero-WLAN", Reading.PRESENT),
        ("buero-wlan ", Reading.PRESENT),
        ("Gast", Reading.AWAY),
        ("<not connected>", Reading.AWAY),
        ("unavailable", Reading.UNKNOWN),
        ("unknown", Reading.UNKNOWN),
        (None, Reading.UNKNOWN),
    ],
)
def test_wifi_reading(state: str | None, expected: Reading) -> None:
    assert wifi_reading(state, ["Buero-WLAN"]) == expected


def test_zone_reading() -> None:
    assert zone_reading("Büro", True) == Reading.PRESENT
    assert zone_reading("not_home", False) == Reading.AWAY
    assert zone_reading("unavailable", False) == Reading.UNKNOWN


def test_activity_reading() -> None:
    def read(person: str | None, power: str | None, *presence: str | None) -> Reading:
        return activity_reading(person, power, 30, presence, power_configured=True)

    assert read("home", "80") == Reading.PRESENT
    assert read("home", "5") == Reading.AWAY
    assert read("home", "5", "on") == Reading.PRESENT
    assert read("not_home", "80") == Reading.AWAY
    assert read("unavailable", "80") == Reading.UNKNOWN
    assert read("home", "unavailable") == Reading.UNKNOWN
    assert read("home", "unavailable", "off") == Reading.AWAY
    assert read("home", "kaputt") == Reading.UNKNOWN


@pytest.mark.parametrize(
    ("readings", "mode", "expected"),
    [
        # One source is enough: Wi-Fi dropout does not count as leaving
        ([Reading.PRESENT, Reading.AWAY], Combine.ANY, Reading.PRESENT),
        ([Reading.AWAY, Reading.AWAY], Combine.ANY, Reading.AWAY),
        ([Reading.AWAY, Reading.UNKNOWN], Combine.ANY, Reading.UNKNOWN),
        ([Reading.PRESENT, Reading.UNKNOWN], Combine.ANY, Reading.PRESENT),
        # Both required: Wi-Fi in the parking lot alone is not enough
        ([Reading.PRESENT, Reading.AWAY], Combine.ALL, Reading.AWAY),
        ([Reading.PRESENT, Reading.PRESENT], Combine.ALL, Reading.PRESENT),
        ([Reading.PRESENT, Reading.UNKNOWN], Combine.ALL, Reading.UNKNOWN),
        ([], Combine.ANY, Reading.UNKNOWN),
    ],
)
def test_combine(readings: list[Reading], mode: Combine, expected: Reading) -> None:
    assert combine(readings, mode) == expected


def test_work_presence() -> None:
    assert work_presence(Reading.PRESENT, Reading.PRESENT).location == Location.OFFICE
    assert work_presence(Reading.AWAY, Reading.PRESENT) == WorkPresence(
        Reading.PRESENT, Location.HOME_OFFICE
    )
    assert work_presence(Reading.AWAY, Reading.AWAY).reading == Reading.AWAY
    assert work_presence(Reading.AWAY, None).reading == Reading.AWAY
    assert work_presence(Reading.AWAY, Reading.UNKNOWN).reading == Reading.UNKNOWN
    assert work_presence(None, None).reading == Reading.UNKNOWN


# ---------------------------------------------------------------- state machine


def test_first_reading_is_taken_over_without_event() -> None:
    state = PresenceState()
    result = advance(state, PRESENT, at(10), **DELAYS)

    assert result.event is None
    assert result.changed
    assert state.phase == Phase.PRESENT
    assert not state.arrival_open


def test_arrival_is_confirmed_with_original_time() -> None:
    state = PresenceState(phase=Phase.AWAY)

    first = advance(state, PRESENT, at(7, 47), **DELAYS)
    assert first.event is None
    assert first.check_at == at(7, 49)
    assert state.phase == Phase.ARRIVING

    assert advance(state, PRESENT, at(7, 48), **DELAYS).event is None
    confirmed = advance(state, PRESENT, at(7, 49), **DELAYS)
    assert confirmed.event is not None
    assert confirmed.event.type == EventType.ARRIVED
    assert confirmed.event.at == at(7, 47)
    assert confirmed.event.location == Location.OFFICE
    assert state.phase == Phase.PRESENT
    assert state.arrival_open


def test_gps_jump_is_discarded() -> None:
    state = PresenceState(phase=Phase.AWAY)
    advance(state, PRESENT, at(3), **DELAYS)
    advance(state, AWAY, at(3, 1), **DELAYS)

    assert state.phase == Phase.AWAY
    assert advance(state, AWAY, at(3, 5), **DELAYS).event is None


def test_wifi_dropout_shorter_than_delay_keeps_presence() -> None:
    state = PresenceState(phase=Phase.PRESENT, arrived_at=at(8))
    advance(state, AWAY, at(10), **DELAYS)
    assert state.phase == Phase.LEAVING

    result = advance(state, PRESENT, at(10, 5), **DELAYS)
    assert result.event is None
    assert state.phase == Phase.PRESENT
    assert state.arrived_at == at(8)


def test_departure_is_confirmed_with_original_time() -> None:
    state = PresenceState(phase=Phase.PRESENT, location=Location.OFFICE, arrived_at=at(8))
    advance(state, AWAY, at(17, 3), **DELAYS)
    result = advance(state, AWAY, at(17, 13), **DELAYS)

    assert result.event is not None
    assert result.event.type == EventType.LEFT
    assert result.event.at == at(17, 3)
    assert result.event.location == Location.OFFICE
    assert state.phase == Phase.AWAY
    assert state.departure_open


def test_unknown_reading_changes_nothing() -> None:
    state = PresenceState(phase=Phase.PRESENT, arrived_at=at(8))
    assert advance(state, UNKNOWN, at(12), **DELAYS) == advance(state, UNKNOWN, at(13), **DELAYS)
    assert state.phase == Phase.PRESENT

    # Unknown while leaving pauses the confirmation
    advance(state, AWAY, at(17), **DELAYS)
    assert advance(state, UNKNOWN, at(17, 30), **DELAYS).event is None
    assert state.phase == Phase.LEAVING
    assert advance(state, AWAY, at(17, 31), **DELAYS).event is not None


def test_change_during_restart_uses_changed_at() -> None:
    state = PresenceState(phase=Phase.AWAY)
    result = advance(state, PRESENT, at(7, 55), changed_at=at(7, 40), **DELAYS)

    assert result.event is not None
    assert result.event.at == at(7, 40)


def test_suppression_lasts_for_the_day() -> None:
    state = PresenceState(phase=Phase.PRESENT, arrived_at=at(8), suppressed_on=DAY)
    assert state.suppressed(DAY)
    advance(state, AWAY, at(12), **DELAYS)
    advance(state, AWAY, at(12, 10), **DELAYS)
    assert state.suppressed(DAY)
    assert not state.suppressed(DAY + timedelta(days=1))


def test_arrival_after_clocking_out_today_only_asks() -> None:
    decision = on_arrival(RULES, situation(at(20), WorkStatus.CLOCKED_OUT, suppressed=True), at(19))
    assert decision.outcome == Outcome.ASK
    assert decision.reason == Reason.SUPPRESSED


def test_location_change_without_departure() -> None:
    state = PresenceState(phase=Phase.PRESENT, location=Location.HOME_OFFICE, arrived_at=at(8))
    result = advance(state, PRESENT, at(10), **DELAYS)
    assert result.changed
    assert result.event is None
    assert state.location == Location.OFFICE


def test_state_roundtrip() -> None:
    state = PresenceState(
        phase=Phase.LEAVING,
        location=Location.OFFICE,
        arrived_at=at(8),
        left_at=at(12),
        arrival_open=True,
        departure_open=False,
        suppressed_on=DAY,
    )
    assert PresenceState.from_dict(state.as_dict()) == state
    assert PresenceState.from_dict(None) == PresenceState()
    assert PresenceState.from_dict({"phase": "kaputt", "left_at": "gestern"}) == PresenceState()


# ------------------------------------------------------------------------ rules

RULES = Rules(
    arrival_mode=StampMode.AUTO,
    break_mode=StampMode.AUTO,
    end_of_day_mode=StampMode.AUTO,
    arrival_offset=timedelta(minutes=5),
    departure_offset=timedelta(minutes=3),
    break_start=time(11, 30),
    break_end=time(13, 30),
    end_of_day_time=time(15, 0),
    end_of_day_on_target=True,
)


def situation(now: datetime, status: WorkStatus, **kwargs) -> Situation:
    return Situation(now=now, status=status, **kwargs)


def test_arrival_waits_for_offset_then_clocks_in() -> None:
    waiting = on_arrival(RULES, situation(at(7, 49), WorkStatus.CLOCKED_OUT), at(7, 47))
    assert waiting.outcome == Outcome.WAIT
    assert waiting.reason == Reason.WAITING_OFFSET
    assert waiting.recheck_at == at(7, 52)

    decision = on_arrival(RULES, situation(at(7, 52), WorkStatus.CLOCKED_OUT), at(7, 47))
    assert decision.outcome == Outcome.STAMP
    assert decision.stamp_type == StampType.START_WORK
    assert decision.at == at(7, 52)
    assert decision.reason == Reason.ARRIVED


def test_arrival_ask_mode() -> None:
    rules = Rules(arrival_mode=StampMode.ASK)
    decision = on_arrival(rules, situation(at(8), WorkStatus.CLOCKED_OUT), at(7, 58))
    assert decision.outcome == Outcome.ASK
    assert decision.choices == (StampType.START_WORK,)
    assert decision.at == at(7, 58)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"enabled": False}, Reason.DISABLED),
        ({"no_work_reason": "absence"}, Reason.ABSENT),
        ({"no_work_reason": "weekday"}, Reason.NOT_WORKDAY),
        ({"no_work_reason": "workday_sensor"}, Reason.NOT_WORKDAY),
    ],
)
def test_arrival_guards(kwargs: dict, reason: Reason) -> None:
    decision = on_arrival(RULES, situation(at(9), WorkStatus.CLOCKED_OUT, **kwargs), at(8))
    assert decision.outcome == Outcome.SKIP
    assert decision.reason == reason


def test_arrival_already_clocked_in() -> None:
    decision = on_arrival(RULES, situation(at(9), WorkStatus.CLOCKED_IN), at(8))
    assert decision.reason == Reason.ALREADY_CLOCKED_IN


def test_arrival_before_window_clocks_in_at_window_start() -> None:
    early = on_arrival(RULES, situation(at(4, 40), WorkStatus.CLOCKED_OUT), at(4, 30))
    assert early.outcome == Outcome.WAIT
    assert early.reason == Reason.WAITING_WINDOW
    assert early.recheck_at == at(5)

    decision = on_arrival(RULES, situation(at(5), WorkStatus.CLOCKED_OUT), at(4, 30))
    assert decision.outcome == Outcome.STAMP
    assert decision.at == at(5)


def test_arrival_after_window_is_skipped() -> None:
    decision = on_arrival(RULES, situation(at(22, 30), WorkStatus.CLOCKED_OUT), at(22, 20))
    assert decision.reason == Reason.OUTSIDE_WINDOW


def test_return_from_break_resumes_any_time() -> None:
    decision = on_arrival(
        RULES,
        situation(at(16, 10), WorkStatus.ON_BREAK, latest_stamp_at=at(16)),
        at(16, 5),
    )
    assert decision.outcome == Outcome.STAMP
    assert decision.stamp_type == StampType.START_WORK
    assert decision.at == at(16, 10)
    assert decision.reason == Reason.RETURNED


def test_return_from_break_off_when_break_mode_off() -> None:
    rules = Rules(arrival_mode=StampMode.AUTO, break_mode=StampMode.OFF)
    decision = on_arrival(rules, situation(at(13), WorkStatus.ON_BREAK), at(12, 55))
    assert decision.reason == Reason.MODE_OFF


def test_arrival_never_before_latest_stamp() -> None:
    decision = on_arrival(
        Rules(arrival_mode=StampMode.AUTO),
        situation(at(9), WorkStatus.CLOCKED_OUT, latest_stamp_at=at(8, 30)),
        at(8),
    )
    assert decision.at == at(8, 31)


def test_leaving_in_break_window_starts_break() -> None:
    decision = on_departure(
        RULES, situation(at(12, 13), WorkStatus.CLOCKED_IN, latest_stamp_at=at(7, 52)), at(12, 3)
    )
    assert decision.outcome == Outcome.STAMP
    assert decision.stamp_type == StampType.START_BREAK
    assert decision.at == at(12)
    assert decision.reason == Reason.BREAK_WINDOW
    # Not back by the end of the day: catch up
    assert decision.recheck_at == at(15)


def test_leaving_in_break_window_while_on_break() -> None:
    decision = on_departure(RULES, situation(at(12, 13), WorkStatus.ON_BREAK), at(12, 3))
    assert decision.reason == Reason.ALREADY_ON_BREAK


def test_leaving_outside_windows_never_clocks_out() -> None:
    decision = on_departure(RULES, situation(at(10, 20), WorkStatus.CLOCKED_IN), at(10, 10))
    assert decision.outcome == Outcome.SKIP
    assert decision.reason == Reason.NO_RULE
    assert decision.recheck_at == at(15)


def test_leaving_outside_windows_asks_with_expiry() -> None:
    rules = Rules(
        end_of_day_mode=StampMode.AUTO,
        end_of_day_time=time(15),
        departure_offset=timedelta(minutes=3),
        ask_on_leave=True,
        ask_timeout=timedelta(minutes=30),
    )
    decision = on_departure(rules, situation(at(10, 20), WorkStatus.CLOCKED_IN), at(10, 10))
    assert decision.outcome == Outcome.ASK
    assert decision.reason == Reason.LEFT_DURING_WORK
    assert decision.choices == (StampType.START_BREAK, StampType.CLOCK_OUT)
    assert decision.at == at(10, 7)
    assert decision.expires == at(10, 50)


def test_leaving_at_end_of_day_clocks_out() -> None:
    decision = on_departure(RULES, situation(at(17, 13), WorkStatus.CLOCKED_IN), at(17, 3))
    assert decision.outcome == Outcome.STAMP
    assert decision.stamp_type == StampType.CLOCK_OUT
    assert decision.at == at(17)
    assert decision.reason == Reason.END_OF_DAY


def test_end_of_day_when_target_reached_before_fixed_time() -> None:
    sit = situation(at(14, 20), WorkStatus.CLOCKED_IN, target_reached_at=at(14))
    assert end_of_day_start(RULES, sit) == at(14)
    decision = on_departure(RULES, sit, at(14, 10))
    assert decision.reason == Reason.END_OF_DAY


def test_end_of_day_ask_offers_break() -> None:
    rules = Rules(end_of_day_mode=StampMode.ASK, end_of_day_time=time(15))
    decision = on_departure(rules, situation(at(16), WorkStatus.CLOCKED_IN), at(15, 50))
    assert decision.outcome == Outcome.ASK
    assert decision.choices == (StampType.CLOCK_OUT, StampType.START_BREAK)


def test_departure_clamped_after_latest_stamp() -> None:
    decision = on_departure(
        RULES, situation(at(17, 13), WorkStatus.CLOCKED_IN, latest_stamp_at=at(17, 1)), at(17, 3)
    )
    assert decision.at == at(17, 2)


def test_departure_when_already_clocked_out() -> None:
    decision = on_departure(RULES, situation(at(17, 13), WorkStatus.CLOCKED_OUT), at(17, 3))
    assert decision.reason == Reason.ALREADY_CLOCKED_OUT


def test_catch_up_doctor_appointment() -> None:
    """Left at 13:45 for a doctor's appointment and did not come back."""

    sit = situation(at(14), WorkStatus.CLOCKED_IN, latest_stamp_at=at(12, 45))
    first = on_departure(RULES, sit, at(13, 48))
    assert first.outcome == Outcome.SKIP
    assert first.recheck_at == at(15)

    early = on_departure(RULES, sit, at(13, 48), catch_up=True)
    assert early.outcome == Outcome.WAIT

    later = situation(at(15), WorkStatus.CLOCKED_IN, latest_stamp_at=at(12, 45))
    decision = on_departure(RULES, later, at(13, 48), catch_up=True)
    assert decision.outcome == Outcome.STAMP
    assert decision.stamp_type == StampType.CLOCK_OUT
    assert decision.at == at(13, 45)
    assert decision.reason == Reason.CATCH_UP


def test_catch_up_after_break_clocks_out_after_break_start() -> None:
    sit = situation(at(15), WorkStatus.ON_BREAK, latest_stamp_at=at(12))
    decision = on_departure(RULES, sit, at(12, 3), catch_up=True)
    assert decision.stamp_type == StampType.CLOCK_OUT
    assert decision.at == at(12, 1)


def test_no_catch_up_without_end_of_day_rule() -> None:
    rules = Rules(break_mode=StampMode.AUTO, break_start=time(11), break_end=time(13))
    decision = on_departure(rules, situation(at(10), WorkStatus.CLOCKED_IN), at(9, 50))
    assert decision.recheck_at is None
    assert (
        on_departure(
            rules, situation(at(16), WorkStatus.CLOCKED_IN), at(9, 50), catch_up=True
        ).reason
        == Reason.NO_RULE
    )


def test_disabled_departure() -> None:
    sit = situation(at(17), WorkStatus.CLOCKED_IN, enabled=False)
    assert on_departure(RULES, sit, at(16, 50)).reason == Reason.DISABLED


# --------------------------------------------------------------------- absences


def test_calendar_all_day_event() -> None:
    item = CalendarItem("Urlaub", date(2026, 11, 9), date(2026, 11, 14))
    assert calendar_covers_day(item, DAY, time(5), time(22))
    assert not calendar_covers_day(item, date(2026, 11, 14), time(5), time(22))


def test_calendar_timed_event() -> None:
    whole = CalendarItem("Urlaub", at(0), at(23, 59))
    part = CalendarItem("Arzt", at(9), at(11))
    assert calendar_covers_day(whole, DAY, time(5), time(22))
    assert not calendar_covers_day(part, DAY, time(5), time(22))


def test_matching_calendar_item_keyword() -> None:
    items = [
        CalendarItem("Geburtstag Oma", DAY, DAY + timedelta(days=1)),
        CalendarItem("URLAUB Italien", DAY, DAY + timedelta(days=5)),
    ]
    assert matching_calendar_item(items, DAY, ["urlaub"], time(5), time(22)) == items[1]
    assert matching_calendar_item(items, DAY, [], time(5), time(22)) == items[0]
    assert matching_calendar_item(items, DAY, ["krank"], time(5), time(22)) is None


def test_absence_today_sources() -> None:
    vacation = make_absence("2026-11-09", "2026-11-13")
    half = make_absence("2026-11-09", "2026-11-09", fromDayPart="AFTERNOON")
    item = CalendarItem("Urlaub", DAY, DAY + timedelta(days=1))

    assert absence_today(DAY, crewmeister=[(vacation, "Urlaub")]).source == (
        AbsenceSource.CREWMEISTER
    )
    assert absence_today(DAY, crewmeister=[(half, "Urlaub")]) is None
    info = absence_today(DAY, calendar_item=item)
    assert info is not None
    assert info.source == AbsenceSource.CALENDAR
    assert info.title == "Urlaub"
    assert absence_today(DAY, sensor_on=True).source == AbsenceSource.SENSOR
    assert absence_today(DAY) is None


# ----------------------------------------------------------------------- breaks


def summary(work: timedelta, rest: timedelta = timedelta(0)) -> DaySummary:
    return DaySummary(
        work=work,
        breaks=rest,
        status=WorkStatus.CLOCKED_OUT,
        status_since=None,
        shift_start=None,
        latest=None,
        now=at(18),
        rest_breaks=rest,
    )


B30, B45 = timedelta(minutes=30), timedelta(minutes=45)


@pytest.mark.parametrize(
    ("work", "rest", "expected"),
    [
        (timedelta(hours=5), timedelta(0), timedelta(0)),
        (timedelta(hours=8), timedelta(0), timedelta(minutes=30)),
        (timedelta(hours=8), timedelta(minutes=30), timedelta(0)),
        (timedelta(hours=8), timedelta(minutes=20), timedelta(minutes=15)),
        # Adding 10 minutes brings the work time down to 6 h
        (timedelta(hours=6, minutes=10), timedelta(0), timedelta(minutes=10)),
        (timedelta(hours=9, minutes=30), timedelta(minutes=30), timedelta(minutes=15)),
        (timedelta(hours=9, minutes=10), timedelta(minutes=30), timedelta(minutes=10)),
    ],
)
def test_missing_break(work: timedelta, rest: timedelta, expected: timedelta) -> None:
    assert missing_break(summary(work, rest), B30, B45) == expected


def test_break_choices() -> None:
    m = timedelta(minutes=1)
    assert break_choices(30 * m, 30 * m) == [30 * m, 45 * m]
    assert break_choices(15 * m, 30 * m) == [15 * m, 30 * m, 45 * m]
    assert break_choices(10 * m, 30 * m) == [10 * m, 15 * m, 30 * m]
    assert break_choices(15 * m, 60 * m) == [15 * m, 30 * m, 60 * m]
    assert break_choices(180 * m, 30 * m) == [120 * m]
