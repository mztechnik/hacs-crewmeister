"""Integration tests of the V2 assistant: automatic stamping, queue, absences, breaks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.crewmeister.api import CrewmeisterConnectionError, StampType

from .conftest import NOW, FakeBackend

PERSON = "person.max"
ZONE = "zone.office"
PHONE = "mobile_app_phone"
WIFI = "sensor.phone_wifi_connection"
POWER = "sensor.pc_power"
MIN = timedelta(minutes=1)

BASE = {
    "person": PERSON,
    "work_zones": [ZONE],
    "notify_targets": [PHONE],
    "arrival_delay": 2,
    "departure_delay": 5,
}
# End of day period already started (NOW is 10:00 local time)
END_OF_DAY = {"end_of_day_mode": "auto", "end_of_day_time": "09:00:00"}


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
    """Advance the time minute by minute, like the real clock."""

    step = min(delta, MIN)
    remaining = delta
    while remaining > timedelta(0):
        tick = min(step, remaining)
        freezer.tick(tick)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        remaining -= tick


async def press(hass: HomeAssistant, action: str) -> None:
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()


def stamps(backend: FakeBackend) -> list[tuple[str, datetime]]:
    return [(s.stamp_type, s.timestamp) for s in backend.stamps]


def actions(call: ServiceCall) -> list[str]:
    return [a["action"] for a in call.data["data"].get("actions", [])]


def action_types(call: ServiceCall) -> list[str]:
    return [a.split(":")[2] for a in actions(call)]


def decision(entry: MockConfigEntry) -> dict[str, Any]:
    return entry.runtime_data.assistant.state.decision


# ------------------------------------------------------------------- arrival


async def test_arrival_with_offset(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto", "arrival_offset": 5})

    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)
    # Confirmed, but the stamp time lies 5 minutes after the arrival
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert decision(mock_config_entry)["reason"] == "waiting_offset"

    await advance(hass, freezer, 3 * MIN)
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW + 5 * MIN)
    assert decision(mock_config_entry)["reason"] == "arrived"
    assert decision(mock_config_entry)["result"] == "done"
    assert notifications[-1].data["message"] == "Clocked in at 10:05"


async def test_ask_on_arrival(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "ask"})

    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)

    call = notifications[-1]
    assert call.data["title"] == "Arrived at work"
    assert action_types(call) == ["CLOCK_IN", "IGNORE"]
    await press(hass, actions(call)[0])
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)


async def test_no_clock_in_with_absence_sensor(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set("input_boolean.urlaub", "on")
    await setup(
        hass,
        mock_config_entry,
        {**BASE, "clock_in_mode": "auto", "absence_sensor": "input_boolean.urlaub"},
    )
    absent = hass.states.get("binary_sensor.max_muster_vacation_absence")
    assert absent.state == "on"
    assert absent.attributes["source"] == "sensor"
    assert hass.states.get("binary_sensor.max_muster_working_day").state == "off"

    await move(hass, True)
    await advance(hass, freezer, 3 * MIN)

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert decision(mock_config_entry)["reason"] == "absent"

    hass.states.async_set("input_boolean.urlaub", "off")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.max_muster_vacation_absence").state == "off"


async def test_no_clock_in_with_calendar_vacation(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    today = dt_util.now().date()

    async def get_events(call: ServiceCall) -> ServiceResponse:
        return {
            "calendar.privat": {
                "events": [
                    {
                        "summary": "Zahnarzt",
                        "start": f"{today}T09:00:00",
                        "end": f"{today}T10:00:00",
                    },
                    {
                        "summary": "Urlaub Italien",
                        "start": today.isoformat(),
                        "end": (today + timedelta(days=3)).isoformat(),
                    },
                ]
            }
        }

    # The calendar integration registers the real service; replace it afterwards
    assert await async_setup_component(hass, "calendar", {})
    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    await setup(
        hass,
        mock_config_entry,
        {
            **BASE,
            "clock_in_mode": "auto",
            "absence_calendar": "calendar.privat",
            "absence_keywords": ["urlaub"],
        },
    )
    absent = hass.states.get("binary_sensor.max_muster_vacation_absence")
    assert absent.state == "on"
    assert absent.attributes == {
        **absent.attributes,
        "source": "calendar",
        "absence_type": "Urlaub Italien",
    }

    await move(hass, True)
    await advance(hass, freezer, 3 * MIN)
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"


async def test_arrival_during_restart_is_detected(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto"})
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await move(hass, True)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, 2 * MIN)

    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)


async def test_first_setup_at_work_does_not_stamp(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto"}, at_work=True)
    await advance(hass, freezer, 5 * MIN)

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert hass.states.get("sensor.max_muster_work_location").state == "office"


async def test_arrival_after_clock_out_today_asks(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass, mock_config_entry, {**BASE, **END_OF_DAY, "clock_in_mode": "auto"}, at_work=True
    )
    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)
    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)

    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)

    assert stamps(backend)[-1][0] == "CLOCK_OUT"
    assert notifications[-1].data["title"] == "Back at work"
    assert action_types(notifications[-1]) == ["CLOCK_IN", "IGNORE"]


# ----------------------------------------------------------------- departure


async def test_end_of_day_clock_out_with_offset(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass, mock_config_entry, {**BASE, **END_OF_DAY, "departure_offset": 3}, at_work=True
    )

    await move(hass, False)
    await advance(hass, freezer, 4 * MIN)
    assert stamps(backend)[-1][0] == "START_WORK"

    await advance(hass, freezer, MIN)
    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW - 3 * MIN)
    assert decision(mock_config_entry)["reason"] == "end_of_day"


async def test_leaving_during_work_never_clocks_out(
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
            **BASE,
            "end_of_day_mode": "auto",
            "end_of_day_time": "15:00:00",
            "end_of_day_on_target": False,
            "ask_on_leave": True,
            "ask_timeout": 10,
            "catch_up": False,
        },
        at_work=True,
    )

    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)

    assert stamps(backend)[-1][0] == "START_WORK"
    call = notifications[-1]
    assert call.data["title"] == "Left work"
    assert action_types(call) == ["START_BREAK", "CLOCK_OUT", "IGNORE"]

    # The question expires and is removed
    await advance(hass, freezer, 10 * MIN)
    cleared = notifications[-1]
    assert cleared.data["message"] == "clear_notification"
    assert cleared.data["data"]["tag"].endswith("_presence")

    await press(hass, actions(call)[1])
    assert stamps(backend)[-1][0] == "START_WORK"
    assert notifications[-1].data["message"] == "This question has expired."


async def test_leaving_in_break_window_starts_break(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {
            **BASE,
            "break_mode": "auto",
            "break_window_start": "09:30:00",
            "break_window_end": "11:00:00",
        },
        at_work=True,
    )

    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)
    assert stamps(backend)[-1] == ("START_BREAK", NOW)

    back = dt_util.utcnow()
    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)
    assert stamps(backend)[-1] == ("START_WORK", back)


async def test_catch_up_at_end_of_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {
            **BASE,
            "end_of_day_mode": "auto",
            "end_of_day_time": "11:00:00",
            "end_of_day_on_target": False,
        },
        at_work=True,
    )

    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)
    assert stamps(backend)[-1][0] == "START_WORK"
    assert decision(mock_config_entry)["reason"] == "no_rule"

    await advance(hass, freezer, 55 * MIN)
    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)
    assert decision(mock_config_entry)["reason"] == "catch_up"


async def test_wifi_dropout_does_not_end_presence(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set(WIFI, "Firma")
    await setup(
        hass,
        mock_config_entry,
        {**BASE, **END_OF_DAY, "wifi_sensor": WIFI, "wifi_ssids": ["Firma"]},
        at_work=True,
    )

    hass.states.async_set(WIFI, "<not connected>")
    await hass.async_block_till_done()
    await advance(hass, freezer, 10 * MIN)
    assert stamps(backend)[-1][0] == "START_WORK"

    left = dt_util.utcnow()
    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)
    assert stamps(backend)[-1] == ("CLOCK_OUT", left)


async def test_both_sources_required(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set(WIFI, "<not connected>")
    await setup(
        hass,
        mock_config_entry,
        {
            **BASE,
            "clock_in_mode": "auto",
            "wifi_sensor": WIFI,
            "wifi_ssids": ["Firma"],
            "office_combine": "all",
        },
    )

    # Wi-Fi reaches the parking lot, the zone does not yet
    hass.states.async_set(WIFI, "Firma")
    await hass.async_block_till_done()
    await advance(hass, freezer, 3 * MIN)
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    arrived = dt_util.utcnow()
    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)
    assert stamps(clocked_out)[-1] == ("START_WORK", arrived)


async def test_unavailable_person_is_no_departure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, **END_OF_DAY}, at_work=True)

    hass.states.async_set(PERSON, "unavailable")
    hass.states.async_set(ZONE, 0, {"persons": []})
    await hass.async_block_till_done()
    await advance(hass, freezer, 10 * MIN)

    assert stamps(backend)[-1][0] == "START_WORK"
    assert hass.states.get("sensor.max_muster_work_location").state == "office"


async def test_departure_survives_reload(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, **END_OF_DAY}, at_work=True)
    await move(hass, False)
    await advance(hass, freezer, 2 * MIN)

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, 3 * MIN)

    assert stamps(backend)[-1] == ("CLOCK_OUT", NOW)


async def test_switch_disables_automatic_stamping(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto"})
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.max_muster_automatic_stamping"},
        blocking=True,
    )

    await move(hass, True)
    await advance(hass, freezer, 3 * MIN)

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert decision(mock_config_entry)["reason"] == "disabled"


# --------------------------------------------------------------- reliability


async def test_stamp_is_queued_while_crewmeister_is_down(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    failures = {"left": 3}

    async def create(stamp_type: str, **kwargs: Any) -> Any:
        if failures["left"]:
            failures["left"] -= 1
            raise CrewmeisterConnectionError("down")
        return await clocked_out.create(stamp_type, **kwargs)

    mock_client.async_create_stamp.side_effect = create
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto"})

    await move(hass, True)
    await advance(hass, freezer, 2 * MIN)
    assistant = mock_config_entry.runtime_data.assistant
    assert decision(mock_config_entry)["result"] == "unavailable"
    assert len(assistant.state.queue) == 1

    # Retries after 1 and 2 minutes fail, the user is told after the third attempt
    await advance(hass, freezer, 3 * MIN)
    assert notifications[-1].data["title"] == "Stamp will be retried"
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    await advance(hass, freezer, 5 * MIN)
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)
    assert assistant.state.queue == []


async def test_arrival_is_kept_while_status_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**BASE, "clock_in_mode": "auto"})
    mock_client.async_get_recent_stamps.side_effect = CrewmeisterConnectionError("down")

    await move(hass, True)
    await advance(hass, freezer, 4 * MIN)
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    mock_client.async_get_recent_stamps.side_effect = clocked_out.recent
    await advance(hass, freezer, 2 * MIN)
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)


# --------------------------------------------------------------- home office


async def test_home_office(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set(POWER, "5")
    await setup(
        hass,
        mock_config_entry,
        {
            **BASE,
            **END_OF_DAY,
            "clock_in_mode": "auto",
            "arrival_offset": 10,
            "departure_offset": 10,
            "home_office_power_sensor": POWER,
            "home_office_power_threshold": 30,
            "home_office_activity_delay": 5,
            "home_office_idle_timeout": 30,
            "stamp_location": True,
        },
    )
    hass.states.async_set(PERSON, "home")
    hass.states.async_set(POWER, "80")
    await hass.async_block_till_done()
    await advance(hass, freezer, 5 * MIN)

    # No walking time at home
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)
    assert mock_client.async_create_stamp.call_args.kwargs["location"] == "Home office"
    assert hass.states.get("sensor.max_muster_work_location").state == "home_office"

    idle = dt_util.utcnow()
    hass.states.async_set(POWER, "4")
    await hass.async_block_till_done()
    await advance(hass, freezer, 29 * MIN)
    assert stamps(clocked_out)[-1][0] == "START_WORK"
    await advance(hass, freezer, MIN)
    assert stamps(clocked_out)[-1] == ("CLOCK_OUT", idle)


# -------------------------------------------------------------------- breaks


@pytest.fixture
def short_break_day(mock_client: AsyncMock) -> FakeBackend:
    backend = FakeBackend()
    backend.add("START_WORK", NOW - timedelta(hours=7))
    backend.add("START_BREAK", NOW - timedelta(hours=4))
    backend.add("START_WORK", NOW - timedelta(hours=4) + timedelta(minutes=20))
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    mock_client.async_create_stamp.side_effect = backend.create
    mock_client.async_set_break.side_effect = backend.set_break
    return backend


async def clock_out(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )
    await hass.async_block_till_done()


async def test_break_question(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    short_break_day: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE]})
    await clock_out(hass)

    call = notifications[-1]
    assert call.data["title"] == "How long was your break?"
    assert call.data["message"] == (
        "6:40 h of work require a 0:30 h break, 0:20 h are stamped "
        "(only breaks of 15 min or more count). "
        "Without an answer, 30 min are added in 60 min."
    )
    clock_out_id = short_break_day.stamps[-1].id
    assert [a["title"] for a in call.data["data"]["actions"]] == [
        "15 min",
        "30 min",
        "45 min",
        "No break",
    ]
    assert (
        actions(call)[0] == f"crewmeister:{mock_config_entry.entry_id}:ADD_BREAK:15-{clock_out_id}"
    )

    await press(hass, actions(call)[0])
    assert short_break_day.breaks == [(clock_out_id, timedelta(minutes=15))]
    assert notifications[-1].data["message"] == "Added a 15 min break"

    # A second tap (e.g. on the watch) must not add the break again
    await press(hass, actions(call)[1])
    assert short_break_day.breaks == [(clock_out_id, timedelta(minutes=15))]


async def test_break_question_default_after_timeout(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    short_break_day: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {"notify_targets": [PHONE], "break_question_timeout": 10, "break_default": 45},
    )
    await clock_out(hass)
    clock_out_id = short_break_day.stamps[-1].id

    await advance(hass, freezer, 9 * MIN)
    assert short_break_day.breaks == []
    await advance(hass, freezer, MIN)
    assert short_break_day.breaks == [(clock_out_id, timedelta(minutes=45))]
    assert notifications[-1].data["message"] == "Added a 45 min break automatically"


async def test_no_break_answer(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    short_break_day: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {"notify_targets": [PHONE], "break_question_timeout": 5})
    await clock_out(hass)

    await press(hass, actions(notifications[-1])[-1])
    await advance(hass, freezer, 10 * MIN)
    assert short_break_day.breaks == []


async def test_break_window_auto_start_and_resume_reminder(
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
            "break_window_start": "10:30:00",
            "break_window_end": "11:00:00",
            "break_window_auto": True,
            "break_window_resume": True,
            "break_end_reminder": False,
        },
    )

    await advance(hass, freezer, 30 * MIN)
    assert stamps(backend)[-1] == ("START_BREAK", NOW + 30 * MIN)

    await advance(hass, freezer, 30 * MIN)
    assert notifications[-1].data["title"] == "Back to work?"
    assert action_types(notifications[-1]) == ["RESUME"]


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
    backend.add(StampType.START_WORK.value, dt_util.utcnow())
    await setup(hass, mock_config_entry, {**BASE, "forgotten_check_time": "07:00:00"}, at_work=True)
    freezer.tick(timedelta(hours=9))  # leaves at 17:00
    left = dt_util.utcnow()
    await move(hass, False)
    await advance(hass, freezer, 5 * MIN)

    freezer.move_to(datetime(2026, 10, 19, 7, 0, tzinfo=dt_util.get_default_time_zone()))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    call = notifications[-1]
    assert "left work at 18.10. 17:00" in call.data["message"]
    await press(hass, actions(call)[0])
    assert stamps(backend)[-1] == ("CLOCK_OUT", left)
