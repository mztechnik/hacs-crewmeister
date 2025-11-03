"""Config flow for the Crewmeister integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client, config_validation as cv

from .api import (
    CrewmeisterAuthError,
    CrewmeisterClient,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterMissingIdentity,
)
from .const import (
    CONF_ABSENCE_STATES,
    CONF_BASE_URL,
    CONF_CREW_ID,
    CONF_STAMP_NOTE,
    CONF_STAMP_TIME_ACCOUNT_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USER_ID,
    DEFAULT_BASE_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


class CrewmeisterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crewmeister."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            session = aiohttp_client.async_get_clientsession(self.hass)
            client = CrewmeisterClient(
                session,
                user_input[CONF_BASE_URL],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                _, payload = await client.async_login()
                identity = await client.async_get_identity()
            except CrewmeisterAuthError:
                errors["base"] = "invalid_auth"
            except CrewmeisterConnectionError:
                errors["base"] = "cannot_connect"
            except CrewmeisterMissingIdentity:
                errors["base"] = "no_identity"
            except CrewmeisterError:
                errors["base"] = "unknown"
            else:
                return await self._handle_success(identity, payload, user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=user_input.get(CONF_BASE_URL) if user_input else DEFAULT_BASE_URL): str,
                vol.Required(CONF_USERNAME, default=user_input.get(CONF_USERNAME) if user_input else ""): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def _handle_success(self, identity, payload: dict[str, Any], user_input: dict[str, Any]):
        await self.async_set_unique_id(str(identity.user_id))
        self._abort_if_unique_id_configured()

        data = {
            CONF_BASE_URL: user_input[CONF_BASE_URL],
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_USER_ID: identity.user_id,
            CONF_CREW_ID: identity.crew_id,
            "token_payload": payload,
        }
        if identity.full_name:
            data["full_name"] = identity.full_name
        if identity.email:
            data["email"] = identity.email

        title = identity.full_name or identity.email or user_input[CONF_USERNAME]
        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> config_entries.FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_user({
            CONF_BASE_URL: self._reauth_entry.data[CONF_BASE_URL],
            CONF_USERNAME: self._reauth_entry.data[CONF_USERNAME],
        })

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CrewmeisterOptionsFlowHandler(config_entry)


class CrewmeisterOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Crewmeister options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        interval_option = self.entry.options.get(CONF_UPDATE_INTERVAL)
        if isinstance(interval_option, (int, float)):
            update_interval = int(interval_option)
        else:
            update_interval = int(DEFAULT_UPDATE_INTERVAL.total_seconds())
        absence_states = self.entry.options.get(CONF_ABSENCE_STATES, [])
        stamp_note = self.entry.options.get(CONF_STAMP_NOTE, "")
        stamp_time_account_id = self.entry.options.get(CONF_STAMP_TIME_ACCOUNT_ID)

        absence_state_options = {
            "APPROVED": "Approved",
            "PRE_APPROVED": "Pre-approved",
            "REQUESTED": "Requested",
            "REJECTED": "Rejected",
            "DRAFT": "Draft",
            "REVOKED": "Revoked",
        }

        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=update_interval): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(CONF_ABSENCE_STATES, default=absence_states or ["APPROVED", "PRE_APPROVED"]): cv.multi_select(
                    absence_state_options
                ),
                vol.Optional(CONF_STAMP_NOTE, default=stamp_note): vol.Any(str, None),
                vol.Optional(CONF_STAMP_TIME_ACCOUNT_ID, default=stamp_time_account_id): vol.Any(None, cv.positive_int),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
