"""Config flow for the Crewmeister integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    CrewmeisterAuthError,
    CrewmeisterClient,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterIdentity,
    CrewmeisterMissingIdentity,
)
from .const import (
    CONF_BASE_URL,
    CONF_CREW_ID,
    CONF_EMAIL,
    CONF_FULL_NAME,
    CONF_TOKEN_PAYLOAD,
    CONF_USER_ID,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from .coordinator import CrewmeisterConfigEntry
from .options_flow import CrewmeisterOptionsFlow

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


async def _async_validate_login(
    flow: ConfigFlow, base_url: str, username: str, password: str
) -> tuple[CrewmeisterIdentity, dict[str, Any]]:
    """Log in and return the identity and token payload of the user."""

    client = CrewmeisterClient(
        aiohttp_client.async_get_clientsession(flow.hass), base_url, username, password
    )
    payload = await client.async_login()
    return await client.async_get_identity(), payload


def _is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _error_key(err: CrewmeisterError) -> str:
    if isinstance(err, CrewmeisterAuthError):
        return "invalid_auth"
    if isinstance(err, CrewmeisterConnectionError):
        return "cannot_connect"
    if isinstance(err, CrewmeisterMissingIdentity):
        return "no_identity"
    return "unknown"


def _entry_data(
    identity: CrewmeisterIdentity,
    payload: dict[str, Any],
    base_url: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_BASE_URL: base_url,
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_USER_ID: identity.user_id,
        CONF_CREW_ID: identity.crew_id,
        CONF_TOKEN_PAYLOAD: payload,
    }
    if identity.full_name:
        data[CONF_FULL_NAME] = identity.full_name
    if identity.email:
        data[CONF_EMAIL] = identity.email
    return data


class CrewmeisterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crewmeister."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the API URL and credentials."""

        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].strip().rstrip("/")
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            if not _is_https_url(base_url):
                # Credentials must never be sent unencrypted
                errors[CONF_BASE_URL] = "insecure_url"
            else:
                try:
                    identity, payload = await _async_validate_login(
                        self, base_url, username, password
                    )
                except CrewmeisterError as err:
                    errors["base"] = _error_key(err)
            if not errors:
                await self.async_set_unique_id(str(identity.user_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=identity.full_name or identity.email or username,
                    data=_entry_data(identity, payload, base_url, username, password),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                {k: v for k, v in (user_input or {}).items() if k != CONF_PASSWORD},
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the credentials were rejected."""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password of the existing account."""

        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = entry.data[CONF_BASE_URL]
            username = entry.data[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                identity, payload = await _async_validate_login(self, base_url, username, password)
            except CrewmeisterError as err:
                errors["base"] = _error_key(err)
            else:
                await self.async_set_unique_id(str(identity.user_id))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data=_entry_data(identity, payload, base_url, username, password)
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: CrewmeisterConfigEntry) -> OptionsFlow:
        """Return the options flow."""

        return CrewmeisterOptionsFlow()
