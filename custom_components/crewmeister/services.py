"""Services of the Crewmeister integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import CrewmeisterError, StampType
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_LOCATION,
    ATTR_NOTE,
    ATTR_STAMP_TYPE,
    ATTR_TIME_ACCOUNT_ID,
    ATTR_TIMESTAMP,
    DOMAIN,
    SERVICE_CREATE_STAMP,
)
from .coordinator import CrewmeisterConfigEntry
from .helpers import clean_note

SERVICE_SCHEMA_CREATE_STAMP = vol.Schema(
    {
        vol.Required(ATTR_STAMP_TYPE): vol.All(cv.string, vol.Coerce(StampType)),
        vol.Optional(ATTR_TIMESTAMP): cv.datetime,
        vol.Optional(ATTR_NOTE): vol.Any(cv.string, None),
        vol.Optional(ATTR_LOCATION): vol.Any(cv.string, None),
        # Same range as the selector in services.yaml; 0 is no valid time account
        vol.Optional(ATTR_TIME_ACCOUNT_ID): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=1))
        ),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services."""

    async def async_create_stamp(call: ServiceCall) -> None:
        await _async_create_stamp(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_STAMP, async_create_stamp, schema=SERVICE_SCHEMA_CREATE_STAMP
    )


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> CrewmeisterConfigEntry:
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"entry_id": entry_id},
            )
        return entry

    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not loaded:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entries")
    if len(loaded) > 1:
        # Stamping for every configured user at once is never intended
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="multiple_entries")
    return loaded[0]


async def _async_create_stamp(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    runtime = entry.runtime_data
    defaults = runtime.stamp_defaults

    note = call.data.get(ATTR_NOTE, defaults.note)
    time_account_id = call.data.get(ATTR_TIME_ACCOUNT_ID, defaults.time_account_id)

    timestamp = call.data.get(ATTR_TIMESTAMP)
    try:
        await runtime.client.async_create_stamp(
            call.data[ATTR_STAMP_TYPE],
            timestamp=dt_util.as_utc(timestamp) if timestamp else None,
            note=clean_note(note),
            location=clean_note(call.data.get(ATTR_LOCATION)),
            time_account_id=time_account_id or None,
        )
    except CrewmeisterError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="stamp_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    await runtime.status_coordinator.async_request_refresh()
