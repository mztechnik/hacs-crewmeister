"""Tests for the Crewmeister config and options flow."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.crewmeister.api import (
    CrewmeisterAuthError,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterIdentity,
    CrewmeisterMissingIdentity,
)
from custom_components.crewmeister.const import DEFAULT_BASE_URL, DOMAIN

from .conftest import ENTRY_DATA, TOKEN_PAYLOAD, USER_ID

USER_INPUT = {
    "base_url": DEFAULT_BASE_URL,
    "username": " max@example.com ",
    "password": "secret",
}


async def test_user_flow(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Max Muster"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == str(USER_ID)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (CrewmeisterAuthError, "invalid_auth"),
        (CrewmeisterConnectionError, "cannot_connect"),
        (CrewmeisterMissingIdentity, "no_identity"),
        (CrewmeisterError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_client: AsyncMock, error: type[Exception], key: str
) -> None:
    mock_client.async_login.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    # The form recovers once the problem is gone
    mock_client.async_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    mock_client.async_login.side_effect = CrewmeisterAuthError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.async_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "new"
    assert mock_config_entry.data["token_payload"] == TOKEN_PAYLOAD


async def test_reauth_flow_wrong_account(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_client.async_get_identity.return_value = CrewmeisterIdentity(user_id=1, crew_id=2)
    result = await mock_config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data["password"] == "secret"


async def _open_options_step(hass: HomeAssistant, entry: MockConfigEntry, step: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


def _suggested(result) -> dict:
    """Return the suggested values of all fields, including those in sections."""

    def collect(schema) -> dict:
        values = {}
        for key, value in schema.schema.items():
            if isinstance(value, section):
                values.update(collect(value.schema))
            elif key.description and "suggested_value" in key.description:
                values[str(key)] = key.description["suggested_value"]
        return values

    return collect(result["data_schema"])


async def test_options_menu(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["menu_options"] == [
        "schedule",
        "notifications",
        "auto_stamp",
        "home_office",
        "reminders",
        "breaks",
        "advanced",
    ]


async def test_options_hint_without_notification_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "breaks")
    assert result["description_placeholders"]["notify_hint"].startswith("⚠️")

    result = await _open_options_step(hass, mock_config_entry, "schedule")
    assert result["description_placeholders"]["notify_hint"] == ""

    hass.config_entries.async_update_entry(
        mock_config_entry, options={"notify_targets": ["mobile_app_pixel"]}
    )
    await hass.async_block_till_done()
    result = await _open_options_step(hass, mock_config_entry, "breaks")
    assert result["description_placeholders"]["notify_hint"] == ""


async def test_options_auto_stamp_sections(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"person": "person.max", "clock_in_mode": "ask"}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "auto_stamp")
    schema = result["data_schema"].schema
    assert schema["timing"].options["collapsed"] is True
    assert schema["detection"].options["collapsed"] is False
    suggested = _suggested(result)
    assert suggested["person"] == "person.max"
    assert suggested["clock_in_mode"] == "ask"
    assert suggested["arrival_delay"] == 2

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "detection": {"person": "person.max", "work_zones": ["zone.office"]},
            "behaviour": {
                "clock_in_mode": "auto",
                "clock_out_mode": "ask",
                "backdate": True,
                "short_leave_break": 30.0,
            },
            "timing": {
                "arrival_delay": 3.0,
                "departure_delay": 5.0,
                "window_start": "06:00:00",
                "window_end": "20:00:00",
                "once_per_day": True,
            },
            "nfc": {"nfc_tags": ["desk"]},
        },
    )
    await hass.async_block_till_done()

    assert mock_config_entry.options == {
        "person": "person.max",
        "work_zones": ["zone.office"],
        "clock_in_mode": "auto",
        "clock_out_mode": "ask",
        "backdate": True,
        "short_leave_break": 30,
        "arrival_delay": 3,
        "departure_delay": 5,
        "window_start": "06:00:00",
        "window_end": "20:00:00",
        "once_per_day": True,
        "nfc_tags": ["desk"],
    }


async def test_options_advanced(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    # Legacy string formats must not break the form
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            "update_interval": "00:10:00",
            "stamp_time_account_id": "3",
            "person": "person.max",
        },
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "advanced")
    assert result["type"] is FlowResultType.FORM
    suggested = _suggested(result)
    assert suggested["update_interval"] == 600
    assert suggested["stamp_time_account_id"] == 3

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval": 900.0,
            "absence_states": ["REQUESTED", "APPROVED"],
            "stamp_note": "  Büro  ",
            "stamp_time_account_id": 5.0,
            "location": {"stamp_location": True, "location_home_office": " Mobil "},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        "update_interval": 900,
        "absence_states": ["APPROVED", "REQUESTED"],
        "stamp_note": "Büro",
        "stamp_time_account_id": 5,
        "stamp_location": True,
        "location_home_office": "Mobil",
        # Options of other sections are kept
        "person": "person.max",
    }
    # The entry was reloaded with the new defaults
    assert mock_config_entry.runtime_data.stamp_defaults.note == "Büro"


async def test_options_sections_keep_and_clear_values(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"update_interval": 600, "reminder_time": "17:00:00"}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "reminders")
    suggested = _suggested(result)
    assert suggested["reminder_time"] == "17:00:00"
    assert suggested["forgotten_check_time"] == "07:00:00"
    assert suggested["max_work_hours"] == 10.0

    # Clearing the optional times disables them
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "end_of_day": {
                "end_of_day_reminder": True,
                "end_of_day_grace": 20.0,
                "max_work_hours": 9.5,
            },
            "still_clocked_in": {"remind_on_leave": False, "snooze_minutes": 15.0},
        },
    )
    await hass.async_block_till_done()

    assert mock_config_entry.options == {
        "update_interval": 600,
        "remind_on_leave": False,
        "end_of_day_reminder": True,
        "end_of_day_grace": 20,
        "max_work_hours": 9.5,
        "snooze_minutes": 15,
        "forgotten_check_time": None,
    }
    config = mock_config_entry.runtime_data.config
    assert config.reminder_time is None
    assert config.forgotten_check_time is None


async def test_options_notifications_lists_mobile_apps(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    hass.services.async_register("notify", "mobile_app_pixel", AsyncMock())
    hass.services.async_register("notify", "persistent_notification", AsyncMock())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "notifications")
    selector = result["data_schema"].schema["notify_targets"]
    assert selector.config["options"] == ["mobile_app_pixel"]

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "notify_targets": ["mobile_app_pixel"],
            "notify_confirmations": True,
            "notify_live": True,
            "notify_status": False,
        },
    )
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.config.notify_targets == ["mobile_app_pixel"]


async def test_options_weekday_hours(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "schedule")
    assert _suggested(result)["daily_hours"] == 8.0

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "workdays": ["mon", "tue", "wed", "thu", "fri"],
            "daily_hours": 8.0,
            "weekday_hours": {"hours_fri": 5.5, "hours_wed": 0.0},
        },
    )
    await hass.async_block_till_done()

    config = mock_config_entry.runtime_data.config
    assert config.target_hours(date(2026, 10, 19)) == timedelta(hours=8)  # Monday
    assert config.target_hours(date(2026, 10, 21)) is None  # Wednesday, 0 h
    assert config.target_hours(date(2026, 10, 23)) == timedelta(hours=5, minutes=30)
    assert config.target_hours(date(2026, 10, 24)) is None  # Saturday


@pytest.mark.parametrize("url", ["http://api.crewmeister.com", "ftp://x", "api.crewmeister.com"])
async def test_user_flow_requires_https(
    hass: HomeAssistant, mock_client: AsyncMock, url: str
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "base_url": url}
    )

    assert result["errors"] == {"base_url": "insecure_url"}
    mock_client.async_login.assert_not_awaited()
