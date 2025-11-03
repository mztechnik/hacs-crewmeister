"""Crewmeister integration for Home Assistant."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import (
    CrewmeisterAuthError,
    CrewmeisterClient,
    CrewmeisterError,
    CrewmeisterIdentity,
    CrewmeisterMissingIdentity,
)
from .const import (
    CONF_BASE_URL,
    CONF_CREW_ID,
    CONF_STAMP_NOTE,
    CONF_STAMP_TIME_ACCOUNT_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USER_ID,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SERVICE_CREATE_STAMP,
    SERVICE_FIELD_CONFIG_ENTRY_ID,
    SERVICE_FIELD_LOCATION,
    SERVICE_FIELD_NOTE,
    SERVICE_FIELD_STAMP_TYPE,
    SERVICE_FIELD_TIME_ACCOUNT_ID,
    SERVICE_FIELD_TIMESTAMP,
    STAMP_TYPES,
)
from .coordinator import CrewmeisterStatusCoordinator

_LOGGER = logging.getLogger(__name__)

# Typing helpers
ConfigEntryData = dict[str, Any]
IntegrationRuntimeData = dict[str, Any]

SERVICE_SCHEMA_CREATE_STAMP = vol.Schema(
    {
        vol.Required(SERVICE_FIELD_STAMP_TYPE): vol.In(STAMP_TYPES),
        vol.Optional(SERVICE_FIELD_TIMESTAMP): cv.datetime,
        vol.Optional(SERVICE_FIELD_NOTE): vol.Any(str, None),
        vol.Optional(SERVICE_FIELD_LOCATION): vol.Any(str, None),
        vol.Optional(SERVICE_FIELD_TIME_ACCOUNT_ID): vol.Any(None, cv.positive_int),
        vol.Optional(SERVICE_FIELD_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Crewmeister integration."""

    hass.data.setdefault(DOMAIN, {})

    async def async_handle_create_stamp(call: ServiceCall) -> None:
        stamp_type: str = call.data[SERVICE_FIELD_STAMP_TYPE]
        timestamp = call.data.get(SERVICE_FIELD_TIMESTAMP)
        note_provided = SERVICE_FIELD_NOTE in call.data
        note = call.data.get(SERVICE_FIELD_NOTE)
        location = call.data.get(SERVICE_FIELD_LOCATION)
        time_account_provided = SERVICE_FIELD_TIME_ACCOUNT_ID in call.data
        time_account_id = call.data.get(SERVICE_FIELD_TIME_ACCOUNT_ID)
        entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)

        if entry_id:
            entry_data = hass.data[DOMAIN].get(entry_id)
            if not entry_data:
                raise HomeAssistantError(f"Crewmeister config entry '{entry_id}' not found")
            targets = [entry_data]
        else:
            targets = list(hass.data[DOMAIN].values())

        if not targets:
            raise HomeAssistantError("No Crewmeister configuration entries available")

        utc_dt = dt_util.as_utc(timestamp) if timestamp else None

        for data in targets:
            client: CrewmeisterClient = data["client"]
            coordinator: CrewmeisterStatusCoordinator = data["coordinator"]
            defaults: dict[str, Any] = data.get("stamp_defaults", {})
            resolved_note = note if note_provided else defaults.get("note")
            resolved_note = _sanitize_note(resolved_note)
            resolved_time_account_id = (
                time_account_id if time_account_provided else defaults.get("time_account_id")
            )
            resolved_time_account_id = _sanitize_time_account_id(resolved_time_account_id)

            await client.async_create_stamp(
                stamp_type,
                timestamp=utc_dt,
                note=resolved_note,
                location=location,
                time_account_id=resolved_time_account_id,
            )
            await coordinator.async_request_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_CREATE_STAMP):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_STAMP,
            async_handle_create_stamp,
            schema=SERVICE_SCHEMA_CREATE_STAMP,
        )

    return True


def _resolve_update_interval(entry: ConfigEntry) -> timedelta:
    option_value = entry.options.get(CONF_UPDATE_INTERVAL)
    if isinstance(option_value, timedelta):
        return option_value
    if isinstance(option_value, (int, float)):
        return timedelta(seconds=float(option_value))
    return DEFAULT_UPDATE_INTERVAL


def _create_identity(entry: ConfigEntry) -> CrewmeisterIdentity:
    return CrewmeisterIdentity(
        user_id=entry.data[CONF_USER_ID],
        crew_id=entry.data[CONF_CREW_ID],
        email=entry.data.get("email"),
        full_name=entry.data.get("full_name"),
    )


def _sanitize_note(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
        return None
    return None


def _sanitize_time_account_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            int_value = int(value)
        except ValueError:
            return None
        return int_value if int_value > 0 else None
    return None


def _extract_stamp_defaults(entry: ConfigEntry) -> dict[str, Any]:
    options = entry.options
    defaults: dict[str, Any] = {}

    note = _sanitize_note(options.get(CONF_STAMP_NOTE))
    if note is not None:
        defaults["note"] = note

    time_account_id = _sanitize_time_account_id(options.get(CONF_STAMP_TIME_ACCOUNT_ID))
    if time_account_id is not None:
        defaults["time_account_id"] = time_account_id

    return defaults


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crewmeister from a config entry."""

    session = aiohttp_client.async_get_clientsession(hass)
    identity = _create_identity(entry)
    token_payload = entry.data.get("token_payload") or {}

    client = CrewmeisterClient(
        session,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        identity=identity,
        token_payload=token_payload,
        language=hass.config.language,
    )

    coordinator = CrewmeisterStatusCoordinator(hass, client, update_interval=_resolve_update_interval(entry))

    try:
        await coordinator.async_config_entry_first_refresh()
    except CrewmeisterAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CrewmeisterMissingIdentity as err:
        raise ConfigEntryNotReady(str(err)) from err
    except CrewmeisterError as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "stamp_defaults": _extract_stamp_defaults(entry),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Crewmeister config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle reloading of a config entry."""

    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the entry."""

    await hass.config_entries.async_reload(entry.entry_id)
