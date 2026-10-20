"""Diagnostics support for Crewmeister."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_FULL_NAME, CONF_STAMP_NOTE, CONF_TOKEN_PAYLOAD
from .coordinator import CrewmeisterConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_EMAIL,
    CONF_FULL_NAME,
    CONF_TOKEN_PAYLOAD,
    CONF_STAMP_NOTE,
    "note",
    "location",
    "nfc_tags",
    "wifi_ssids",
    "left_at",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CrewmeisterConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    status = entry.runtime_data.status_coordinator
    absences = entry.runtime_data.absence_coordinator
    status_data = status.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "status": {
            "last_update_success": status.last_update_success,
            "status": status_data.status if status_data else None,
            "stamp_count": len(status_data.stamps) if status_data else 0,
            "latest_stamp": async_redact_data(status_data.latest_stamp.raw, TO_REDACT)
            if status_data and status_data.latest_stamp
            else None,
        },
        "assistant": {
            "config": async_redact_data(
                {k: str(v) for k, v in asdict(entry.runtime_data.config).items()}, TO_REDACT
            ),
            "state": async_redact_data(entry.runtime_data.assistant.state.as_dict(), TO_REDACT),
        },
        "absences": {
            "last_update_success": absences.last_update_success,
            "last_success": absences.last_success.isoformat() if absences.last_success else None,
            "upcoming": [
                async_redact_data(asdict(entry.event), {"summary", "description"})
                for entry in absences.upcoming()
            ],
        },
    }
