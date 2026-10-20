"""Tests for setup, entities and services of the Crewmeister integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.crewmeister.api import (
    CrewmeisterAuthError,
    CrewmeisterConnectionError,
    CrewmeisterError,
    StampType,
)
from custom_components.crewmeister.const import DOMAIN

from .conftest import ENTRY_DATA, NOW, FakeBackend, make_absence

STATUS = "sensor.max_muster_status"
LAST_STAMP = "sensor.max_muster_last_stamp"
WORKING = "binary_sensor.max_muster_clocked_in"
CALENDAR = "calendar.max_muster_absences"
CLOCK_IN = "button.max_muster_clock_in"
START_BREAK = "button.max_muster_start_break"
CLOCK_OUT = "button.max_muster_clock_out"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(STATUS).state == "clocked_in"
    assert hass.states.get(STATUS).attributes["stamp_type"] == "START_WORK"
    assert hass.states.get(LAST_STAMP).state == "2026-10-19T15:00:00+00:00"
    assert hass.states.get(WORKING).state == STATE_ON
    assert hass.states.get(CALENDAR).state == STATE_OFF
    for button in (CLOCK_IN, START_BREAK, CLOCK_OUT):
        assert hass.states.get(button) is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_on_break(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    backend.add("START_BREAK", NOW - timedelta(minutes=10))
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(STATUS).state == "on_break"
    assert hass.states.get(WORKING).state == STATE_OFF
    assert hass.states.get(WORKING).attributes["on_break"] is True


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_recent_stamps.side_effect = CrewmeisterAuthError
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_setup_connection_failure_retries(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_recent_stamps.side_effect = CrewmeisterConnectionError
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_status_update_failure_marks_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, mock_config_entry)

    mock_client.async_get_recent_stamps.side_effect = CrewmeisterConnectionError
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(STATUS).state == STATE_UNAVAILABLE


async def test_calendar_shows_next_absence(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    today = dt_util.now().date()
    mock_client.async_get_absences.return_value = [
        make_absence(
            (today + timedelta(days=3)).isoformat(),
            (today + timedelta(days=5)).isoformat(),
            toDayPart="MORNING",
        ),
        make_absence(today.isoformat(), today.isoformat(), fromDayPart="AFTERNOON"),
    ]
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(CALENDAR)
    assert state.attributes["message"] == "Urlaub"
    start = datetime.fromisoformat(state.attributes["start_time"])
    assert (start.date(), start.hour) == (today, 12)
    states_filter = mock_client.async_get_absences.call_args.args[3]
    assert states_filter == {"APPROVED", "PRE_APPROVED"}


async def test_calendar_get_events(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_absences.return_value = [
        make_absence("2027-01-04", "2027-01-08", toDayPart="MORNING")
    ]

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR, "start_date_time": "2027-01-01", "end_date_time": "2027-02-01"},
        blocking=True,
        return_response=True,
    )

    (event,) = result[CALENDAR]["events"]
    assert event["summary"] == "Urlaub"
    end = datetime.fromisoformat(event["end"])
    assert (end.date().isoformat(), end.hour) == ("2027-01-08", 12)


async def test_button_creates_stamp_with_defaults(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"stamp_note": "HA", "stamp_time_account_id": 4}
    )
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call("button", "press", {"entity_id": CLOCK_OUT}, blocking=True)

    mock_client.async_create_stamp.assert_awaited_once_with(
        StampType.CLOCK_OUT, note="HA", location=None, time_account_id=4
    )
    assert hass.states.get(STATUS).state == "clocked_out"


async def test_button_refreshes_before_validation(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    backend.add("CLOCK_OUT", NOW - timedelta(hours=1))
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(STATUS).state == "clocked_out"

    # Clocked in elsewhere in the meantime: starting a break must work
    backend.add("START_WORK", NOW - timedelta(minutes=5))
    await hass.services.async_call("button", "press", {"entity_id": START_BREAK}, blocking=True)

    mock_client.async_create_stamp.assert_awaited_once()


async def test_button_rejects_invalid_transition(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("button", "press", {"entity_id": CLOCK_IN}, blocking=True)

    assert err.value.translation_key == "already_clocked_in"
    mock_client.async_create_stamp.assert_not_awaited()


async def test_button_api_error(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_create_stamp.side_effect = CrewmeisterError("boom")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("button", "press", {"entity_id": CLOCK_OUT}, blocking=True)

    assert err.value.translation_key == "stamp_failed"


async def test_service_create_stamp(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"stamp_note": "Default", "stamp_time_account_id": 4}
    )
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        "create_stamp",
        {"stamp_type": "START_WORK", "timestamp": "2026-10-19 08:00:00", "note": "Geofence"},
        blocking=True,
    )

    call = mock_client.async_create_stamp.await_args
    assert call.args == (StampType.START_WORK,)
    assert call.kwargs["note"] == "Geofence"
    assert call.kwargs["time_account_id"] == 4
    assert call.kwargs["location"] is None
    assert call.kwargs["timestamp"] == dt_util.as_utc(
        datetime(2026, 10, 19, 8, tzinfo=dt_util.get_default_time_zone())
    )


async def test_service_explicit_none_overrides_defaults(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"stamp_note": "Default", "stamp_time_account_id": 4}
    )
    await setup_entry(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        "create_stamp",
        {"stamp_type": "CLOCK_OUT", "note": None, "time_account_id": None},
        blocking=True,
    )

    call = mock_client.async_create_stamp.await_args
    assert call.kwargs["note"] is None
    assert call.kwargs["time_account_id"] is None


async def test_service_requires_entry_with_multiple_accounts(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    other = MockConfigEntry(
        domain=DOMAIN, title="Erika", unique_id="999", data={**ENTRY_DATA, "user_id": 999}
    )
    await setup_entry(hass, other)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "create_stamp", {"stamp_type": "START_WORK"}, blocking=True
        )
    assert err.value.translation_key == "multiple_entries"

    await hass.services.async_call(
        DOMAIN,
        "create_stamp",
        {"stamp_type": "START_WORK", "config_entry_id": other.entry_id},
        blocking=True,
    )
    assert mock_client.async_create_stamp.await_count == 1


async def test_service_unknown_entry(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "create_stamp",
            {"stamp_type": "START_WORK", "config_entry_id": "nope"},
            blocking=True,
        )
    assert err.value.translation_key == "entry_not_found"


async def test_service_api_error(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_create_stamp.side_effect = CrewmeisterError("boom")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "create_stamp", {"stamp_type": "START_WORK"}, blocking=True
        )
    assert err.value.translation_key == "stamp_failed"


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)

    data = diagnostics["entry"]["data"]
    assert data["password"] == "**REDACTED**"
    assert data["username"] == "**REDACTED**"
    assert data["token_payload"] == "**REDACTED**"
    assert diagnostics["status"]["status"] == "clocked_in"


WORK_TIME = "sensor.max_muster_work_time_today"
BREAK_TIME = "sensor.max_muster_break_time_today"
ON_BREAK = "binary_sensor.max_muster_on_break"
WORKDAY = "binary_sensor.max_muster_working_day"
ABSENT = "binary_sensor.max_muster_vacation_absence"


async def test_work_and_break_time_today(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    # Clocked in 08:00, break 09:30-09:45, back to work
    backend.add("START_BREAK", NOW - timedelta(minutes=30))
    backend.add("START_WORK", NOW - timedelta(minutes=15))
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WORK_TIME).state == "105"
    assert hass.states.get(BREAK_TIME).state == "15"
    assert hass.states.get(BREAK_TIME).attributes["required_break"] == 0
    assert hass.states.get(ON_BREAK).state == STATE_OFF

    # The sensors keep counting without polling Crewmeister
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(WORK_TIME).state == "110"
    assert mock_client.async_get_recent_stamps.await_count == 1


async def test_work_time_counts_from_midnight(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    backend = FakeBackend()
    backend.add("START_WORK", NOW - timedelta(hours=12))  # 22:00 yesterday
    mock_client.async_get_recent_stamps.side_effect = backend.recent
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WORK_TIME).state == "600"
    attrs = hass.states.get(BREAK_TIME).attributes
    assert attrs["required_break"] == 45
    assert attrs["missing_break"] == 45


async def test_break_binary_sensor(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    backend: FakeBackend,
    mock_config_entry: MockConfigEntry,
) -> None:
    backend.add("START_BREAK", NOW - timedelta(minutes=10))
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(ON_BREAK)
    assert state.state == STATE_ON
    assert state.attributes["since"] == "2026-10-19T16:50:00+00:00"


async def test_workday_and_absence(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-20")]
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WORKDAY).state == STATE_OFF
    assert hass.states.get(WORKDAY).attributes["reason"] == "absence"
    absent = hass.states.get(ABSENT)
    assert absent.state == STATE_ON
    assert absent.attributes["absence_type"] == "Urlaub"


async def test_half_day_absence_is_workday(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_absences.return_value = [
        make_absence("2026-10-19", "2026-10-19", fromDayPart="AFTERNOON")
    ]
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WORKDAY).state == STATE_ON
    assert hass.states.get(ABSENT).state == STATE_OFF  # starts at noon


async def test_workday_respects_weekdays_and_sensor(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    hass.states.async_set("binary_sensor.workday", "off")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"workday_entity": "binary_sensor.workday"}
    )
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(WORKDAY).attributes["reason"] == "workday_sensor"

    hass.states.async_set("binary_sensor.workday", "on")
    await hass.async_block_till_done()
    assert hass.states.get(WORKDAY).state == STATE_ON

    hass.config_entries.async_update_entry(mock_config_entry, options={"workdays": ["sat"]})
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(WORKDAY).attributes["reason"] == "weekday"


async def test_setup_refuses_insecure_url(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="1", data={**ENTRY_DATA, "base_url": "http://example.com"}
    )
    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_client.async_get_recent_stamps.assert_not_awaited()


async def test_absences_survive_failed_refresh(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-20")]
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(ABSENT).state == STATE_ON

    # Crewmeister fails: data is kept and retried every 10 minutes
    mock_client.async_get_absences.side_effect = CrewmeisterConnectionError("maintenance")
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ABSENT).state == STATE_ON
    assert hass.states.get(CALENDAR).state != STATE_UNAVAILABLE
    calls = mock_client.async_get_absences.await_count
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_client.async_get_absences.await_count == calls + 1

    # Recovered: normal interval again
    mock_client.async_get_absences.side_effect = None
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data.absence_coordinator
    assert coordinator.update_interval == timedelta(hours=1)


async def test_absences_unavailable_when_data_too_old(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-30")]
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_absences.side_effect = CrewmeisterConnectionError("down")

    for _ in range(25):
        freezer.tick(timedelta(hours=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get(ABSENT).state == STATE_UNAVAILABLE
    assert hass.states.get(CALENDAR).state == STATE_UNAVAILABLE


async def test_no_absence_request_at_midnight(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, mock_config_entry)
    calls = mock_client.async_get_absences.await_count

    # 00:00:05 next day, less than an hour after the last refresh at 23:40
    freezer.move_to(dt_util.start_of_local_day(dt_util.now()) + timedelta(hours=23, minutes=40))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    calls = mock_client.async_get_absences.await_count
    freezer.move_to(dt_util.start_of_local_day(dt_util.now()) + timedelta(days=1, seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_client.async_get_absences.await_count == calls


async def test_workday_ignores_absences_older_than_a_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-30")]
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(WORKDAY).state == STATE_OFF
    mock_client.async_get_absences.side_effect = CrewmeisterConnectionError("down")

    # A day later the vacation may have been cancelled meanwhile
    for _ in range(25):
        freezer.tick(timedelta(hours=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get(WORKDAY).state == STATE_ON


async def test_absences_retry_soon_when_first_refresh_fails(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_get_absences.side_effect = CrewmeisterConnectionError("down")
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(CALENDAR).state == STATE_UNAVAILABLE

    mock_client.async_get_absences.side_effect = None
    mock_client.async_get_absences.return_value = [make_absence("2026-10-19", "2026-10-20")]
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(CALENDAR).state != STATE_UNAVAILABLE


async def test_service_location_as_note(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"location_as_note": True})
    await setup_entry(hass, mock_config_entry)

    # Lowercase values come from the selector in the UI
    await hass.services.async_call(
        DOMAIN, "create_stamp", {"stamp_type": "start_work", "location": "Kunde"}, blocking=True
    )

    call = mock_client.async_create_stamp.await_args
    assert call.args == (StampType.START_WORK,)
    assert (call.kwargs["note"], call.kwargs["location"]) == ("Kunde", None)
