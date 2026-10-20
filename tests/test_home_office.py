"""Tests for home office detection, the work location sensor and stamp locations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from .conftest import NOW, FakeBackend
from .test_assistant import PHONE, ZONE, actions, advance, press, set_presence, stamps

PERSON = "person.max"
POWER = "sensor.pc_power"
DESK = "binary_sensor.desk_presence"
LOCATION = "sensor.max_muster_work_location"

OPTIONS = {
    "person": PERSON,
    "home_office_power_sensor": POWER,
    "home_office_presence_sensors": [DESK],
    "notify_targets": [PHONE],
    "home_office_clock_in_mode": "auto",
    "break_reminder_after": 0,
}


@pytest.fixture
def notifications(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "notify", PHONE)


@pytest.fixture
def clocked_out(backend: FakeBackend) -> FakeBackend:
    backend.add("CLOCK_OUT", NOW - timedelta(hours=1))
    return backend


async def setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict[str, Any], *, home: bool = True
) -> None:
    hass.states.async_set(PERSON, "home" if home else "not_home")
    hass.states.async_set(POWER, "4.2")
    hass.states.async_set(DESK, "off")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def set_state(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def test_auto_clock_in_break_and_clock_out(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, OPTIONS)
    assert hass.states.get(LOCATION).state == "none"

    # PC draws power: after 5 minutes a session starts, backdated to 10:00
    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=4))
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    await advance(hass, freezer, timedelta(minutes=1))
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)
    assert hass.states.get(LOCATION).state == "home_office"

    # 40 minutes away from the desk: stamped as break
    left = dt_util.utcnow()
    await set_state(hass, POWER, "3")
    await advance(hass, freezer, timedelta(minutes=40))
    await set_state(hass, POWER, "90")
    assert stamps(clocked_out)[-2:] == [
        ("START_BREAK", left),
        ("START_WORK", left + timedelta(minutes=40)),
    ]

    # Longer inactivity ends the day at its beginning
    await advance(hass, freezer, timedelta(hours=3))
    idle = dt_util.utcnow()
    await set_state(hass, POWER, "3")
    await advance(hass, freezer, timedelta(minutes=59))
    assert stamps(clocked_out)[-1][0] == "START_WORK"
    await advance(hass, freezer, timedelta(minutes=1))
    assert stamps(clocked_out)[-1] == ("CLOCK_OUT", idle)
    assert hass.states.get(LOCATION).state == "none"


async def test_presence_sensor_and_ask_modes(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(
        hass,
        mock_config_entry,
        {**OPTIONS, "home_office_clock_in_mode": "ask", "home_office_clock_out_mode": "ask"},
    )

    await set_state(hass, DESK, "on")
    await advance(hass, freezer, timedelta(minutes=5))
    call = notifications[-1]
    assert call.data["title"] == "Working from home detected"
    assert call.data["message"] == "You have been working from home since 10:00. Clock in now?"
    await press(hass, actions(call)[0])
    assert stamps(clocked_out)[-1] == ("START_WORK", NOW)

    # In ask mode there is no break window: asked after 30 minutes
    gone = dt_util.utcnow()
    await set_state(hass, DESK, "off")
    await advance(hass, freezer, timedelta(minutes=30))
    call = notifications[-1]
    assert call.data["title"] == "No more activity"
    assert [a.split(":")[2] for a in actions(call)] == ["CLOCK_OUT", "START_BREAK", "IGNORE"]
    await press(hass, actions(call)[0])
    assert stamps(clocked_out)[-1] == ("CLOCK_OUT", gone)


@pytest.mark.parametrize(
    ("options", "home"),
    [
        ({"workdays": ["tue"]}, True),
        ({"home_office_window_start": "11:00:00"}, True),
        ({}, False),
    ],
)
async def test_no_session_outside_working_time_or_away(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    options: dict[str, Any],
    home: bool,
) -> None:
    await setup(hass, mock_config_entry, {**OPTIONS, **options}, home=home)

    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=10))

    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert hass.states.get(LOCATION).state == "none"


async def test_start_is_clamped_to_time_window(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**OPTIONS, "home_office_window_start": "10:30:00"})

    await set_state(hass, POWER, "85")  # 10:00, before the window
    await advance(hass, freezer, timedelta(minutes=30))

    assert stamps(clocked_out)[-1] == ("START_WORK", NOW + timedelta(minutes=30))


async def test_location_sent_with_stamps(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**OPTIONS, "stamp_location": True})

    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=5))
    assert mock_client.async_create_stamp.await_args.kwargs["location"] == "Home office"

    # Buttons use the detected location as well
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )
    assert mock_client.async_create_stamp.await_args.kwargs["location"] == "Home office"


async def test_custom_location_text_and_office(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    set_presence(hass, False)
    await setup(
        hass,
        mock_config_entry,
        {
            **OPTIONS,
            "work_zones": [ZONE],
            "clock_in_mode": "auto",
            "arrival_delay": 0,
            "stamp_location": True,
            "location_office": "Werk 2",
        },
        home=False,
    )

    set_presence(hass, True)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(seconds=1))

    assert hass.states.get(LOCATION).state == "office"
    assert mock_client.async_create_stamp.await_args.kwargs["location"] == "Werk 2"


async def test_session_of_pc_left_on_resets_at_midnight(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, OPTIONS)
    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=5))
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.max_muster_clock_out"}, blocking=True
    )

    # The PC stays on overnight; the next morning starts a new session at 06:00
    midnight = dt_util.start_of_local_day(dt_util.now()) + timedelta(days=1, seconds=5)
    freezer.move_to(midnight)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(LOCATION).state == "none"

    six = midnight.replace(hour=6, minute=0, second=0)
    freezer.move_to(six)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert stamps(clocked_out)[-1] == ("START_WORK", dt_util.as_utc(six))


async def test_once_per_day_asks_instead(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    notifications: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup(hass, mock_config_entry, {**OPTIONS, "home_office_short_break": 0})
    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=5))
    await set_state(hass, POWER, "3")
    await advance(hass, freezer, timedelta(minutes=30))
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"

    # Back at the desk the same day: asked instead of clocked in automatically
    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=5))
    assert stamps(clocked_out)[-1][0] == "CLOCK_OUT"
    assert notifications[-1].data["title"] == "Working from home detected"


async def test_idle_pc_at_home_does_not_end_office_shift(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    clocked_out: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set(ZONE, 0, {"persons": []})
    await setup(hass, mock_config_entry, {**OPTIONS, "work_zones": [ZONE]})
    await set_state(hass, POWER, "85")
    await advance(hass, freezer, timedelta(minutes=5))
    assert stamps(clocked_out)[-1][0] == "START_WORK"

    # Off to the office: the PC is switched off, the shift goes on there
    await set_state(hass, POWER, "3")
    await set_state(hass, PERSON, "not_home")
    await advance(hass, freezer, timedelta(minutes=20))
    hass.states.async_set(PERSON, "Büro")
    hass.states.async_set(ZONE, 1, {"persons": [PERSON]})
    await hass.async_block_till_done()
    assert hass.states.get(LOCATION).state == "office"

    await advance(hass, freezer, timedelta(hours=2))
    assert stamps(clocked_out)[-1][0] == "START_WORK"
