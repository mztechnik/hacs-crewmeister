"""Tests for the Crewmeister config and options flow."""

from __future__ import annotations

from datetime import time, timedelta
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
from custom_components.crewmeister.logic.migration import migrate_options_v1

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
        "office",
        "home_office",
        "rules",
        "notifications",
        "breaks",
        "advanced",
    ]


async def test_options_hint_without_notification_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "rules")
    assert result["description_placeholders"]["notify_hint"].startswith("⚠️")

    result = await _open_options_step(hass, mock_config_entry, "schedule")
    assert result["description_placeholders"]["notify_hint"] == ""

    hass.config_entries.async_update_entry(
        mock_config_entry, options={"notify_targets": ["mobile_app_pixel"]}
    )
    await hass.async_block_till_done()
    result = await _open_options_step(hass, mock_config_entry, "breaks")
    assert result["description_placeholders"]["notify_hint"] == ""


async def test_options_office(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"person": "person.max"})
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "office")
    schema = result["data_schema"].schema
    assert schema["timing"].options["collapsed"] is True
    assert schema["detection"].options["collapsed"] is False
    suggested = _suggested(result)
    assert suggested["person"] == "person.max"
    assert suggested["office_combine"] == "any"
    assert suggested["departure_delay"] == 10

    # Zones without a person are rejected
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "detection": {"work_zones": ["zone.office"], "office_combine": "any"},
            "timing": {"arrival_delay": 2.0, "departure_delay": 10.0},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "zones_need_person"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "detection": {
                "person": "person.max",
                "work_zones": ["zone.office"],
                "wifi_sensor": "sensor.phone_wifi_connection",
                "wifi_ssids": ["Firma"],
                "office_combine": "all",
            },
            "timing": {"arrival_delay": 3.0, "departure_delay": 10.0},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        "person": "person.max",
        "work_zones": ["zone.office"],
        "wifi_sensor": "sensor.phone_wifi_connection",
        "wifi_ssids": ["Firma"],
        "office_combine": "all",
        "arrival_delay": 3,
        "departure_delay": 10,
    }
    assert hass.states.get("sensor.max_muster_automation").state == "none"


async def test_options_rules(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "rules")
    suggested = _suggested(result)
    assert suggested["clock_in_mode"] == "off"
    assert suggested["end_of_day_on_target"] is True
    assert suggested["catch_up"] is True

    base = {
        "arrival": {"clock_in_mode": "auto", "arrival_offset": 5.0},
        "break_window": {
            "break_mode": "auto",
            "break_window_auto": False,
            "break_window_resume": False,
        },
        "end_of_day": {
            "end_of_day_mode": "auto",
            "end_of_day_on_target": False,
            "departure_offset": 3.0,
            "catch_up": True,
        },
        "leave": {"ask_on_leave": True, "ask_timeout": 30.0},
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], base)
    assert result["errors"] == {"base": "break_window_missing"}

    base["break_window"].update(break_window_start="11:30:00", break_window_end="13:30:00")
    result = await hass.config_entries.options.async_configure(result["flow_id"], base)
    assert result["errors"] == {"base": "end_of_day_never"}

    base["end_of_day"]["end_of_day_time"] = "15:00:00"
    result = await hass.config_entries.options.async_configure(result["flow_id"], base)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    config = mock_config_entry.runtime_data.config
    assert config.arrival_offset == timedelta(minutes=5)
    assert config.departure_offset == timedelta(minutes=3)
    assert config.break_window == (time(11, 30), time(13, 30))
    assert config.end_of_day_time == time(15)
    assert config.end_of_day_on_target is False
    assert config.ask_on_leave is True


async def test_options_schedule_with_absences(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options_step(hass, mock_config_entry, "schedule")
    suggested = _suggested(result)
    assert suggested["daily_hours"] == 8.0
    assert suggested["absence_states"] == ["approved", "pre_approved"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "workdays": ["mon", "tue", "wed", "thu"],
            "daily_hours": 7.5,
            "absence": {
                "absence_sensor": "input_boolean.urlaub",
                "absence_keywords": ["Urlaub"],
                "absence_states": ["requested", "approved"],
            },
            "window": {"window_start": "06:00:00", "window_end": "20:00:00"},
        },
    )
    await hass.async_block_till_done()

    assert mock_config_entry.options == {
        "workdays": ["mon", "tue", "wed", "thu"],
        "daily_hours": 7.5,
        "absence_sensor": "input_boolean.urlaub",
        "absence_keywords": ["Urlaub"],
        "absence_states": ["APPROVED", "REQUESTED"],
        "window_start": "06:00:00",
        "window_end": "20:00:00",
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
            "stamp_note": "  Büro  ",
            "stamp_time_account_id": 5.0,
            "location": {
                "stamp_location": True,
                "location_home_office": " Mobil ",
                "location_as_note": True,
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        "update_interval": 900,
        "stamp_note": "Büro",
        "stamp_time_account_id": 5,
        "stamp_location": True,
        "location_home_office": "Mobil",
        "location_as_note": True,
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

    result = await _open_options_step(hass, mock_config_entry, "breaks")
    suggested = _suggested(result)
    assert suggested["reminder_time"] == "17:00:00"
    assert suggested["forgotten_check_time"] == "07:00:00"
    assert suggested["max_work_hours"] == 10.0
    assert suggested["break_default"] == 30

    # Clearing the optional times disables them
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "during_work": {
                "break_reminder_after": 0.0,
                "break_duration": 30.0,
                "break_end_reminder": True,
                "auto_resume": False,
            },
            "break_check": {
                "break_check": True,
                "break_default": 45.0,
                "break_question_timeout": 60.0,
            },
            "end_of_day": {"end_of_day_reminder": True, "max_work_hours": 9.5},
            "fine_tuning": {
                "end_of_day_grace": 20.0,
                "snooze_minutes": 15.0,
                "break_after_6h": 30.0,
                "break_after_9h": 45.0,
            },
        },
    )
    await hass.async_block_till_done()

    assert mock_config_entry.options["forgotten_check_time"] is None
    assert "reminder_time" not in mock_config_entry.options
    config = mock_config_entry.runtime_data.config
    assert config.reminder_time is None
    assert config.forgotten_check_time is None
    assert config.break_default == timedelta(minutes=45)
    assert config.break_reminder_after is None


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
            "live_icons": {"live_icon_work": "mdi:account-hard-hat"},
        },
    )
    await hass.async_block_till_done()
    config = mock_config_entry.runtime_data.config
    assert config.notify_targets == ["mobile_app_pixel"]
    assert config.live_icon_work == "mdi:account-hard-hat"


async def test_migration_from_version_1(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Max Muster",
        unique_id="4711",
        data=dict(ENTRY_DATA),
        version=1,
        options={
            "person": "person.max",
            "work_zones": ["zone.office"],
            "clock_in_mode": "auto",
            "clock_out_mode": "auto",
            "remind_on_leave": True,
            "nfc_tags": ["desk"],
            "hours_fri": 5.5,
            "lunch_break_time": "12:00:00",
            "break_duration": 45,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.options == {
        "person": "person.max",
        "work_zones": ["zone.office"],
        "clock_in_mode": "auto",
        "end_of_day_mode": "auto",
        "ask_on_leave": True,
        "break_duration": 45,
        "break_window_start": "12:00:00",
        "break_window_end": "12:45:00",
        "break_window_auto": True,
        "break_window_resume": False,
    }


@pytest.mark.parametrize(
    ("office", "home", "expected"),
    [
        ("auto", "auto", "auto"),
        ("auto", "ask", "ask"),
        ("off", "auto", "ask"),
    ],
)
def test_migration_merges_home_office_modes(office: str, home: str, expected: str) -> None:
    options = migrate_options_v1(
        {
            "person": "person.max",
            "work_zones": ["zone.office"],
            "home_office_power_sensor": "sensor.pc",
            "clock_in_mode": office,
            "home_office_clock_in_mode": home,
            "home_office_window_start": "06:00:00",
        }
    )
    assert options["clock_in_mode"] == expected
    assert "home_office_clock_in_mode" not in options
    assert "home_office_window_start" not in options


def test_migration_home_office_only() -> None:
    options = migrate_options_v1(
        {
            "person": "person.max",
            "home_office_power_sensor": "sensor.pc",
            "home_office_clock_in_mode": "ask",
        }
    )
    assert options["clock_in_mode"] == "ask"
    # Home office clocked out automatically by default
    assert options["end_of_day_mode"] == "auto"
    assert options["ask_on_leave"] is False


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
