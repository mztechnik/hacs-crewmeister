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
    DOMAIN,
    MAX_UPDATE_INTERVAL_SECONDS,
    MIN_UPDATE_INTERVAL_SECONDS,
)
from .helpers import coerce_update_interval_seconds


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
            sanitized: dict[str, Any] = dict(user_input)
            sanitized[CONF_UPDATE_INTERVAL] = coerce_update_interval_seconds(
                user_input.get(CONF_UPDATE_INTERVAL)
            )

            absence_states_input = sanitized.get(CONF_ABSENCE_STATES) or []
            if isinstance(absence_states_input, str):
                absence_states = [absence_states_input]
            elif isinstance(absence_states_input, (list, tuple, set)):
                absence_states = [str(state) for state in absence_states_input]
            else:
                absence_states = []

            if absence_states:
                sanitized[CONF_ABSENCE_STATES] = sorted(absence_states)
            else:
                sanitized.pop(CONF_ABSENCE_STATES, None)

            stamp_note_value = sanitized.get(CONF_STAMP_NOTE)
            if isinstance(stamp_note_value, str):
                stamp_note_clean = stamp_note_value.strip()
                if stamp_note_clean:
                    sanitized[CONF_STAMP_NOTE] = stamp_note_clean
                else:
                    sanitized.pop(CONF_STAMP_NOTE, None)
            else:
                sanitized.pop(CONF_STAMP_NOTE, None)

            stamp_time_account_value = sanitized.get(CONF_STAMP_TIME_ACCOUNT_ID)
            if isinstance(stamp_time_account_value, str):
                stamp_time_account_clean = stamp_time_account_value.strip()
                if stamp_time_account_clean:
                    try:
                        stamp_time_account_id = int(stamp_time_account_clean)
                    except ValueError:
                        stamp_time_account_id = None
                    else:
                        if stamp_time_account_id <= 0:
                            stamp_time_account_id = None
                    if stamp_time_account_id is not None:
                        sanitized[CONF_STAMP_TIME_ACCOUNT_ID] = stamp_time_account_id
                    else:
                        sanitized.pop(CONF_STAMP_TIME_ACCOUNT_ID, None)
                else:
                    sanitized.pop(CONF_STAMP_TIME_ACCOUNT_ID, None)
            elif isinstance(stamp_time_account_value, int) and stamp_time_account_value > 0:
                sanitized[CONF_STAMP_TIME_ACCOUNT_ID] = stamp_time_account_value
            else:
                sanitized.pop(CONF_STAMP_TIME_ACCOUNT_ID, None)

            return self.async_create_entry(title="", data=sanitized)

        absence_state_options = {
            "APPROVED": "Approved",
            "PRE_APPROVED": "Pre-approved",
            "REQUESTED": "Requested",
            "REJECTED": "Rejected",
            "DRAFT": "Draft",
            "REVOKED": "Revoked",
        }

        update_interval = coerce_update_interval_seconds(
            self.entry.options.get(CONF_UPDATE_INTERVAL)
        )

        raw_absence_states = self.entry.options.get(CONF_ABSENCE_STATES)
        if isinstance(raw_absence_states, str):
            absence_states_iterable = [raw_absence_states]
        elif isinstance(raw_absence_states, (list, tuple, set)):
            absence_states_iterable = list(raw_absence_states)
        else:
            absence_states_iterable = []

        absence_states = [
            state
            for state in absence_states_iterable
            if state in absence_state_options
        ]
        absence_states.sort()
        if not absence_states:
            absence_states = ["APPROVED", "PRE_APPROVED"]

        stamp_note_option = self.entry.options.get(CONF_STAMP_NOTE)
        if isinstance(stamp_note_option, str):
            stamp_note = stamp_note_option
        else:
            stamp_note = ""

        stamp_time_account_option = self.entry.options.get(CONF_STAMP_TIME_ACCOUNT_ID)
        if isinstance(stamp_time_account_option, int) and stamp_time_account_option > 0:
            stamp_time_account_id = str(stamp_time_account_option)
        elif isinstance(stamp_time_account_option, str):
            stamp_time_account_id = stamp_time_account_option
        else:
            stamp_time_account_id = ""

        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=update_interval): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_UPDATE_INTERVAL_SECONDS, max=MAX_UPDATE_INTERVAL_SECONDS
                    ),
                ),
                vol.Optional(CONF_ABSENCE_STATES, default=absence_states or ["APPROVED", "PRE_APPROVED"]): cv.multi_select(
                    absence_state_options
                ),
                vol.Optional(CONF_STAMP_NOTE, default=stamp_note): cv.string,
                vol.Optional(
                    CONF_STAMP_TIME_ACCOUNT_ID, default=stamp_time_account_id
                ): vol.All(
                    cv.string,
                    vol.Strip,
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
