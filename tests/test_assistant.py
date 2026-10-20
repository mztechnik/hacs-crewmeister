"""Tests for the assistant: presence, notifications, reminders and breaks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.crewmeister.notifications import (
    Action,
    Button,
    Kind,
    build_payload,
    decode_action,
    encode_action,
)

from .conftest import NOW, FakeBackend, make_absence

PERSON = "person.max"
ZONE = "zone.office"
PHONE = "mobile_app_phone"

PRESENCE_OPTIONS = {
    "person": PERSON,
    "work_zones": [ZONE],
    "notify_targets": [PHONE],
    "arrival_delay": 2,
    "departure_delay": 5,
}


@pytest.fixture
def notifications(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "notify", PHONE)


@pytest.fixture
def clocked_out(backend: FakeBackend) -> FakeBackend:
    backend.add("CLOCK_OUT", NOW - timedelta(hours=1))
    return backend


def set_presence(hass: HomeAssistant, at_work: bool) -> None:
    hass.states.async_set(PERSON, "Büro" if at_work else "not_home")
    hass.states.async_set(ZONE, int(at_work), {"persons": [PERSON] if at_work else []})


async def move(hass: HomeAssistant, at_work: bool) -> None:
    set_presence(hass, at_work)
    await hass.async_block_till_done()


async def setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict[str, Any], *, at_work: bool = False
) -> None:
    set_presence(hass, at_work)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def press(hass: HomeAssistant, action: str) -> None:
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()


def stamps(backend: FakeBackend) -> list[tuple[str, datetime]]:
    return [(s.stamp_type, s.timestamp) for s in backend.stamps]


def actions(call: ServiceCall) -> list[str]:
    return [a["action"] for a in call.data["data"].get("actions", [])]


def titles(calls: list[ServiceCall]) -> list[str]:
    return [c.data.get("title") for c in calls]


# --------------------------------------------------------------- notifications


def test_action_round_trip() -> None:
    encoded = encode_action("abc", Action.CLOCK_OUT, "1760900000")
    assert encoded == "crewmeister:abc:CLOCK_OUT:1760900000"
    decoded = decode_action(encoded)
    assert decoded is not None
    assert (decoded.entry_id, decoded.action, decoded.arg) == (
        "abc",
        Action.CLOCK_OUT,
        "1760900000",
    )
    assert decode_action("crewmeister:abc:SNOOZE").arg is None
    assert decode_action("other:abc:CLOCK_OUT") is None
    assert decode_action("crewmeister:abc:BOGUS") is None
    assert decode_action(None) is None


def test_payload_for_android_and_ios() -> None:
    payload = build_payload(
        "abc", Kind.REMINDER, "T", "M", [Button("Go", Action.CLOCK_OUT)], time_sensitive=True
    )
    assert payload == {
        "title": "T",
        "message": "M",
        "data": {
            "tag": "crewmeister_abc_reminder",
            "group": "crewmeister_abc",
            "channel": "Crewmeister",
            "importance": "high",
            "actions": [{"action": "crewmeister:abc:CLOCK_OUT", "title": "Go"}],
            "push": {"interruption-level": "time-sensitive"},
        },
    }


# ------------------------------------------------------------------- presence


async def test_auto_clock_in_on_arrival(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto"})
    assert hass.states.get("switch.max_muster_automatic_stamping").state == "on"

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=1))
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    await advance(hass, freezer, timedelta(minutes=1, seconds=1))
    # Backdated to the moment of arrival
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)
    assert notifications[-1].data["message"] == "Clocked in at 10:00"

    # Only once per day
    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=1))
    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=3))
    assert len(clocked_out.stamps) == 3


async def test_arrival_jitter_is_ignored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto"})

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=1))
    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=5))

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"


@pytest.mark.parametrize(
    "options",
    [
        {"workdays": ["tue"]},
        {"window_start": "11:00:00", "window_end": "18:00:00"},
    ],
)
async def test_no_auto_clock_in_outside_working_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    options: dict[str, Any],
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto", **options})

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=3))

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"


async def test_no_auto_clock_in_during_absence(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-23")]
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto"})

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=3))

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"


async def test_switch_disables_presence_stamping(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto"})
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.max_muster_automatic_stamping"}, blocking=True
    )

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=3))

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert hass.states.get("switch.max_muster_automatic_stamping").state == "off"


async def test_ask_on_arrival(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "ask"})

    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=3))

    (call,) = notifications
    assert call.data["title"] == "Arrived at work"
    entry_id = mock_config_entry.entry_id
    assert actions(call) == [
        f"crewmeister:{entry_id}:CLOCK_IN:{int(NOW.timestamp())}",
        f"crewmeister:{entry_id}:IGNORE",
    ]
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    await press(hass, actions(call)[0])
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)


async def test_actions_of_other_entries_are_ignored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    await setup(hass, mock_config_entry, PRESENCE_OPTIONS)

    await press(hass, "crewmeister:other:CLOCK_IN")
    await press(hass, "something_else")

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"


async def test_auto_clock_out_backdated(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_out_mode": "auto"}, at_work=True
    )

    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=4))
    assert stamps(backend)[-1][0] == "START_WORK"

    await advance(hass, freezer, timedelta(minutes=1, seconds=1))
    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)
    assert notifications[-1].data["message"].startswith("Clocked out at 10:00 – 2:00 h today")


async def test_auto_clock_out_without_backdating(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {**PRESENCE_OPTIONS, "clock_out_mode": "auto", "backdate": False},
        at_work=True,
    )

    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=5, seconds=1))

    assert stamps(backend)[-1][0] == "CLOCK_OUT"
    assert stamps(backend)[-1][1] > NOW + timedelta(minutes=5)


async def test_pending_departure_survives_reload(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_out_mode": "auto"}, at_work=True
    )
    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=2))

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=4))

    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)


async def test_short_absence_becomes_break(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    options = {**PRESENCE_OPTIONS, "clock_out_mode": "auto", "short_leave_break": 60}
    await setup(hass, mock_config_entry, options, at_work=True)

    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=20))
    await move(hass, True)

    assert stamps(backend)[-2:] == [
        ("START_BREAK", NOW),
        ("START_WORK", NOW + timedelta(minutes=20)),
    ]
    assert notifications[-1].data["message"] == "Stamped a break from 10:00 to 10:20."

    # A long absence is a clock out at the time of leaving
    await advance(hass, freezer, timedelta(minutes=10))
    left = dt_util.utcnow()
    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=61))
    assert stamps(backend)[-1] == ("CLOCK_OUT", left)


async def test_ask_on_departure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_out_mode": "ask"}, at_work=True
    )

    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=6))

    call = notifications[-1]
    assert call.data["title"] == "Left work"
    assert [a.split(":")[2] for a in actions(call)] == ["CLOCK_OUT", "START_BREAK", "IGNORE"]
    await press(hass, actions(call)[1])
    assert stamps(backend)[-1] == ("START_BREAK", NOW)


async def test_leave_reminder_and_snooze(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "snooze_minutes": 30}, at_work=True)

    await move(hass, False)
    await advance(hass, freezer, timedelta(minutes=6))
    reminder = notifications[-1]
    assert reminder.data["title"] == "Left work"
    assert [a.split(":")[2] for a in actions(reminder)] == ["CLOCK_OUT", "SNOOZE"]

    await press(hass, actions(reminder)[1])
    count = len(notifications)
    await advance(hass, freezer, timedelta(minutes=29))
    assert len(notifications) == count
    await advance(hass, freezer, timedelta(minutes=2))
    assert notifications[-1].data["title"] == "Still clocked in"

    await press(hass, actions(reminder)[0])
    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)


async def test_outdated_action_is_rejected(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    await setup(hass, mock_config_entry, PRESENCE_OPTIONS)
    old = int((NOW - timedelta(hours=3)).timestamp())  # before the clock in

    await press(hass, f"crewmeister:{mock_config_entry.entry_id}:CLOCK_OUT:{old}")

    assert stamps(backend)[-1][0] == "START_WORK"
    assert notifications[-1].data["title"] == "Stamping failed"
    assert "outdated" in notifications[-1].data["message"]


async def test_nfc_tag_toggles(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup(hass, mock_config_entry, {"nfc_tags": ["desk-tag"]})

    hass.bus.async_fire("tag_scanned", {"tag_id": "other"})
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "START_WORK"

    hass.bus.async_fire("tag_scanned", {"tag_id": "desk-tag"})
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "CLOCK_OUT"

    hass.bus.async_fire("tag_scanned", {"tag_id": "desk-tag"})
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "START_WORK"


async def test_wifi_presence(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set("sensor.phone_wifi", "Home")
    await setup(
        hass,
        mock_config_entry,
        {
            "wifi_sensor": "sensor.phone_wifi",
            "wifi_ssids": ["Firma-WLAN"],
            "clock_in_mode": "auto",
            "arrival_delay": 0,
        },
    )

    hass.states.async_set("sensor.phone_wifi", "Firma-WLAN")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(seconds=1))

    assert stamps(clocked_out)[-1][0] == "START_WORK"


# ------------------------------------------------------------------ reminders


async def test_daily_reminder(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "reminder_time": "10:30:00"})

    await advance(hass, freezer, timedelta(minutes=30))

    assert notifications[-1].data["title"] == "Still clocked in"
    assert notifications[-1].data["message"] == (
        "You have worked 2:30 h today. Don't forget to clock out!"
    )


async def test_max_work_time_warning_once(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "max_work_hours": 2.5, "break_reminder_after": 0},
    )

    await advance(hass, freezer, timedelta(minutes=29))
    assert "Maximum working time reached" not in titles(notifications)
    await advance(hass, freezer, timedelta(minutes=1))
    await advance(hass, freezer, timedelta(minutes=1))
    assert titles(notifications).count("Maximum working time reached") == 1


async def test_forgotten_clock_out(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    backend = FakeBackend()
    yesterday_8 = NOW - timedelta(hours=26)
    backend.add("START_WORK", yesterday_8)
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    await setup(
        hass, mock_config_entry, {"notify_targets": [PHONE], "forgotten_check_time": "10:01:00"}
    )

    await advance(hass, freezer, timedelta(minutes=1))

    call = notifications[-1]
    assert call.data["title"] == "Forgot to clock out?"
    assert call.data["message"] == "You have been clocked in since 18.10. 08:00."
    # 8 h work + 30 min break after 08:00
    assert call.data["data"]["actions"][0]["title"] == "Clock out (18.10. 16:30)"
    await press(hass, actions(call)[0])
    assert stamps(backend)[-1] == ("CLOCK_OUT", yesterday_8 + timedelta(hours=8, minutes=30))


async def test_forgotten_clock_out_uses_departure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    backend = FakeBackend()
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    freezer.move_to(NOW - timedelta(hours=26))  # yesterday 08:00
    backend.add("START_WORK", dt_util.utcnow())
    await setup(
        hass,
        mock_config_entry,
        {**PRESENCE_OPTIONS, "remind_on_leave": False, "forgotten_check_time": "07:00:00"},
        at_work=True,
    )
    await advance(hass, freezer, timedelta(hours=9))  # leaves at 17:00
    await move(hass, False)
    left = dt_util.utcnow()

    freezer.move_to(datetime(2026, 10, 19, 7, 0, tzinfo=dt_util.get_default_time_zone()))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    call = notifications[-1]
    assert "left work at 18.10. 17:00" in call.data["message"]
    await press(hass, actions(call)[0])
    assert stamps(backend)[-1] == ("CLOCK_OUT", left)


# ---------------------------------------------------------------------- breaks


async def test_break_reminder(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "break_reminder_after": 150})

    await advance(hass, freezer, timedelta(minutes=29))
    assert "Time for a break" not in titles(notifications)
    await advance(hass, freezer, timedelta(minutes=1))
    call = notifications[-1]
    assert call.data["title"] == "Time for a break"
    await advance(hass, freezer, timedelta(minutes=1))
    assert titles(notifications).count("Time for a break") == 1

    await press(hass, actions(call)[0])
    assert stamps(backend)[-1][0] == "START_BREAK"


async def test_break_over_notification(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    backend.add("START_BREAK", NOW - timedelta(minutes=29))
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "break_duration": 30})

    await advance(hass, freezer, timedelta(minutes=1))

    call = notifications[-1]
    assert call.data["title"] == "Break is over"
    await press(hass, actions(call)[0])
    assert stamps(backend)[-1][0] == "START_WORK"


async def test_auto_resume_after_break(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    backend.add("START_BREAK", NOW - timedelta(minutes=29))
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "break_duration": 30, "auto_resume": True},
    )

    await advance(hass, freezer, timedelta(minutes=1))

    assert stamps(backend)[-1][0] == "START_WORK"


async def test_lunch_break(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {"lunch_break_time": "10:10:00"})

    await advance(hass, freezer, timedelta(minutes=10))

    assert stamps(backend)[-1] == ("START_BREAK", NOW + timedelta(minutes=10))


async def test_missing_break_after_clock_out(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    backend = FakeBackend()
    backend.add("START_WORK", NOW - timedelta(hours=7))
    backend.add("START_BREAK", NOW - timedelta(hours=4))
    backend.add("START_WORK", NOW - timedelta(hours=4) + timedelta(minutes=20))
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    mock_client.async_set_break.side_effect = backend.set_break
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE]})

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )
    await hass.async_block_till_done()

    call = notifications[-1]
    assert call.data["title"] == "Break too short"
    assert call.data["message"] == (
        "6:40 h of work require a 0:30 h break, you took 0:20 h "
        "(only breaks of 15 min or more count)."
    )
    clock_out_id = backend.stamps[-1].id
    assert actions(call) == [
        f"crewmeister:{mock_config_entry.entry_id}:ADD_BREAK:10-{clock_out_id}"
    ]

    await press(hass, actions(call)[0])
    assert backend.breaks == [(clock_out_id, timedelta(minutes=10))]
    assert notifications[-1].data["message"] == "Added a 10 min break"

    # A second tap (e.g. on the watch) must not add the break again
    await press(hass, actions(call)[0])
    assert backend.breaks == [(clock_out_id, timedelta(minutes=10))]


async def test_short_breaks_do_not_count(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    backend = FakeBackend()
    backend.add("START_WORK", NOW - timedelta(hours=7))
    backend.add("START_BREAK", NOW - timedelta(hours=4))
    backend.add("START_WORK", NOW - timedelta(hours=4) + timedelta(minutes=10))
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE]})

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )
    await hass.async_block_till_done()

    clock_out_id = backend.stamps[-1].id
    assert actions(notifications[-1]) == [
        f"crewmeister:{mock_config_entry.entry_id}:ADD_BREAK:30-{clock_out_id}"
    ]


async def test_status_notification(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "notify_status": True})

    status = notifications[-1].data
    assert status["message"] == "Clocked in since 08:00"
    assert status["data"]["chronometer"] is True
    assert status["data"]["when"] == int((NOW - timedelta(hours=2)).timestamp())
    assert status["data"]["tag"] == f"crewmeister_{mock_config_entry.entry_id}_status"

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )
    await hass.async_block_till_done()
    cleared = [c for c in notifications if c.data["message"] == "clear_notification"]
    assert cleared[-1].data["data"]["tag"] == f"crewmeister_{mock_config_entry.entry_id}_status"


async def test_german_texts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.config.language = "de"
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "reminder_time": "10:30:00"})

    await advance(hass, freezer, timedelta(minutes=30))

    assert notifications[-1].data["title"] == "Noch eingestempelt"
    assert notifications[-1].data["data"]["actions"][1]["title"] == "In 30 min erinnern"


# ----------------------------------------------------- end of day and live display


async def test_end_of_day_reminder(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {
            "notify_targets": [PHONE],
            "end_of_day_reminder": True,
            "break_reminder_after": 0,
            "max_work_hours": 0,
        },
    )
    # Clocked in 08:00 + 8 h + 30 min break + 20 min grace = 16:50
    await advance(hass, freezer, timedelta(hours=6, minutes=49))
    assert "Time to go home?" not in titles(notifications)

    await advance(hass, freezer, timedelta(minutes=1))
    call = notifications[-1]
    assert call.data["title"] == "Time to go home?"
    assert call.data["message"] == (
        "Your target working time of 8:00 h was reached at 16:30. Clock out?"
    )
    assert [a.split(":")[2] for a in actions(call)] == ["CLOCK_OUT", "SNOOZE"]

    await advance(hass, freezer, timedelta(minutes=1))
    assert titles(notifications).count("Time to go home?") == 1


async def test_end_of_day_counts_taken_breaks_and_weekday_hours(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    # 45 min break taken, Monday target 7 h -> 08:00 + 7 h + 45 min = 15:45
    backend.add("START_BREAK", NOW - timedelta(minutes=60))
    backend.add("START_WORK", NOW - timedelta(minutes=15))
    await setup(
        hass,
        mock_config_entry,
        {
            "notify_targets": [PHONE],
            "end_of_day_reminder": True,
            "end_of_day_grace": 0,
            "hours_mon": 7,
            "break_reminder_after": 0,
            "max_work_hours": 0,
        },
    )
    attrs = hass.states.get("sensor.max_muster_work_time_today").attributes
    assert attrs["target"] == 420
    assert datetime.fromisoformat(attrs["expected_end"]) == NOW + timedelta(hours=5, minutes=45)

    await advance(hass, freezer, timedelta(hours=5, minutes=44))
    assert "Time to go home?" not in titles(notifications)
    await advance(hass, freezer, timedelta(minutes=1))
    assert notifications[-1].data["message"].endswith("reached at 15:45. Clock out?")


async def test_no_end_of_day_reminder_without_target(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "end_of_day_reminder": True, "hours_mon": 0},
    )

    await advance(hass, freezer, timedelta(hours=10))

    assert "Time to go home?" not in titles(notifications)


def live_calls(calls: list[ServiceCall]) -> list[ServiceCall]:
    return [c for c in calls if c.data["data"].get("live_update")]


async def test_live_display(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "notify_live": True, "notify_status": True},
    )
    tag = f"crewmeister_{mock_config_entry.entry_id}_live"

    (live,) = live_calls(notifications)
    assert live.data["title"] == "Crewmeister"
    assert live.data["message"] == ("🔵 Working since 08:00 · 🟡 Break 0:00 h · done around 16:30")
    data = live.data["data"]
    assert data["tag"] == tag
    assert data["critical_text"] == "Work"
    assert data["chronometer"] is True
    assert data["when"] == int((NOW - timedelta(hours=2)).timestamp())
    assert (data["progress"], data["progress_max"]) == (120, 480)
    assert (data["color"], data["background_color"], data["progress_bar_color"]) == (
        "#03A9F4",
        "#0B2638",
        "#03A9F4",
    )
    prefix = f"crewmeister:{mock_config_entry.entry_id}"
    assert actions(live) == [f"{prefix}:START_BREAK", f"{prefix}:CLOCK_OUT"]
    # The ongoing Android notification is replaced by the live display
    assert not [c for c in notifications if c.data["data"].get("persistent")]

    # Periodic refresh every 15 minutes
    await advance(hass, freezer, timedelta(minutes=14))
    assert len(live_calls(notifications)) == 1
    await advance(hass, freezer, timedelta(minutes=1))
    assert live_calls(notifications)[-1].data["data"]["progress"] == 135

    # A break switches the timer to the break duration immediately
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_start_break"}, blocking=True
    )
    await hass.async_block_till_done()
    live = live_calls(notifications)[-1]
    data = live.data["data"]
    assert data["critical_text"] == "Break"
    assert data["when"] == int(dt_util.utcnow().timestamp())
    assert live.data["message"].startswith("🟡 Break since 10:15 · 🔵 Worked 2:15 h today")
    assert (data["color"], data["background_color"]) == ("#F9A825", "#3A2A06")
    assert actions(live) == [f"{prefix}:RESUME", f"{prefix}:CLOCK_OUT"]

    # The buttons of the live display stamp directly
    await advance(hass, freezer, timedelta(minutes=1))
    await press(hass, f"{prefix}:RESUME")
    assert stamps(backend)[-1][0] == "START_WORK"
    assert live_calls(notifications)[-1].data["data"]["critical_text"] == "Work"

    # Clocking out ends it
    await press(hass, f"{prefix}:CLOCK_OUT")
    cleared = [c for c in notifications if c.data["message"] == "clear_notification"]
    assert cleared[-1].data["data"]["tag"] == tag


async def test_live_display_restarts_before_ios_limit(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "notify_live": True})
    count = len(notifications)

    await advance(hass, freezer, timedelta(hours=7, minutes=30))

    new = [c for c in notifications[count:] if c.data["data"].get("tag", "").endswith("_live")]
    assert new[0].data["message"] == "clear_notification"
    assert new[1].data["data"]["live_update"] is True


# -------------------------------------------------------------------- security


def add_phone_registration(hass: HomeAssistant, user_id: str, name: str = "Phone") -> None:
    MockConfigEntry(
        domain="mobile_app", data={"device_name": name, "user_id": user_id}
    ).add_to_hass(hass)


async def test_actions_from_other_users_are_ignored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    add_phone_registration(hass, "owner")
    add_phone_registration(hass, "partner", "Partner Phone")
    await setup(hass, mock_config_entry, PRESENCE_OPTIONS)
    action = f"crewmeister:{mock_config_entry.entry_id}:CLOCK_IN"

    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action}, context=Context(user_id="partner")
    )
    await hass.async_block_till_done()
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action}, context=Context(user_id="owner")
    )
    await hass.async_block_till_done()
    assert stamps(clocked_out)[-1][0] == "START_WORK"


async def test_nfc_only_for_the_configured_person(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup(hass, mock_config_entry, {"person": PERSON, "nfc_tags": ["desk-tag"]})
    hass.states.async_set(PERSON, "Büro", {"user_id": "owner"})

    hass.bus.async_fire("tag_scanned", {"tag_id": "desk-tag"}, context=Context(user_id="guest"))
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "START_WORK"

    hass.bus.async_fire("tag_scanned", {"tag_id": "desk-tag"}, context=Context(user_id="owner"))
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "CLOCK_OUT"


@pytest.mark.parametrize("offset", [timedelta(hours=1), timedelta(days=-4)])
async def test_action_times_out_of_range_are_rejected(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    offset: timedelta,
) -> None:
    await setup(hass, mock_config_entry, PRESENCE_OPTIONS)
    at = int((NOW + offset).timestamp())

    await press(hass, f"crewmeister:{mock_config_entry.entry_id}:CLOCK_OUT:{at}")

    assert stamps(backend)[-1][0] == "START_WORK"
    assert notifications[-1].data["title"] == "Stamping failed"


@pytest.mark.parametrize("arg", ["20-99999", "600-101", "0-101", "x-y"])
async def test_invalid_break_actions_are_rejected(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    arg: str,
) -> None:
    await setup(hass, mock_config_entry, PRESENCE_OPTIONS)

    await press(hass, f"crewmeister:{mock_config_entry.entry_id}:ADD_BREAK:{arg}")

    mock_client.async_set_break.assert_not_awaited()


async def test_concurrent_triggers_stamp_once(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    async def slow_create(stamp_type: str, **kwargs: Any) -> Any:
        # The request takes a moment; the other trigger may read the status meanwhile
        await asyncio.sleep(0)
        return await clocked_out.create(stamp_type, **kwargs)

    mock_client.async_create_stamp.side_effect = slow_create
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE]})

    # E.g. the same button tapped on phone and watch at the same time
    action = f"crewmeister:{mock_config_entry.entry_id}:CLOCK_IN"
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()

    assert [s[0] for s in stamps(clocked_out)] == ["START_WORK", "CLOCK_OUT", "START_WORK"]


async def test_forgotten_clock_out_offers_no_future_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    backend = FakeBackend()
    # Shift from 23:55 yesterday: 10 h + 45 min break would end at 10:40 today
    backend.add("START_WORK", NOW - timedelta(hours=10, minutes=5))
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "forgotten_check_time": "10:01:00", "daily_hours": 10},
    )

    await advance(hass, freezer, timedelta(minutes=1))

    call = notifications[-1]
    assert call.data["title"] == "Forgot to clock out?"
    assert actions(call) == [f"crewmeister:{mock_config_entry.entry_id}:CLOCK_OUT"]


async def test_nfc_without_person_or_device_allows_all_users(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup(hass, mock_config_entry, {"nfc_tags": ["desk-tag"]})

    hass.bus.async_fire("tag_scanned", {"tag_id": "desk-tag"}, context=Context(user_id="anyone"))
    await hass.async_block_till_done()
    assert stamps(backend)[-1][0] == "CLOCK_OUT"


async def test_pending_arrival_survives_reload(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**PRESENCE_OPTIONS, "clock_in_mode": "auto"})
    await move(hass, True)
    await advance(hass, freezer, timedelta(minutes=1))

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=1, seconds=1))

    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)


async def test_live_display_colors_text_on_android(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    # Android uses one accent color per notification, but renders the message as HTML
    MockConfigEntry(
        domain="mobile_app", data={"device_name": "Phone", "os_name": "Android"}
    ).add_to_hass(hass)
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "notify_live": True})

    (live,) = live_calls(notifications)
    assert live.data["message"] == (
        '<font color="#03A9F4">🔵 Working since 08:00</font> · '
        '<font color="#F9A825">🟡 Break 0:00 h</font> · done around 16:30'
    )
