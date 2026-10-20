"""Crewmeister integration for Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import CrewmeisterClient, CrewmeisterIdentity
from .assistant import CrewmeisterAssistant, async_remove_assistant_store
from .const import (
    CONF_BASE_URL,
    CONF_CREW_ID,
    CONF_EMAIL,
    CONF_FULL_NAME,
    CONF_TOKEN_PAYLOAD,
    CONF_USER_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import (
    CrewmeisterAbsenceCoordinator,
    CrewmeisterConfigEntry,
    CrewmeisterRuntimeData,
    CrewmeisterStatusCoordinator,
)
from .helpers import stamp_defaults
from .logic.config import AssistantConfig
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Crewmeister integration."""

    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CrewmeisterConfigEntry) -> bool:
    """Set up Crewmeister from a config entry."""

    if not entry.data[CONF_BASE_URL].lower().startswith("https://"):
        # Never send the password over an unencrypted connection
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="insecure_url")

    client = CrewmeisterClient(
        aiohttp_client.async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        identity=CrewmeisterIdentity(
            user_id=entry.data[CONF_USER_ID],
            crew_id=entry.data[CONF_CREW_ID],
            email=entry.data.get(CONF_EMAIL),
            full_name=entry.data.get(CONF_FULL_NAME),
        ),
        token_payload=entry.data.get(CONF_TOKEN_PAYLOAD),
        language=hass.config.language,
    )

    status_coordinator = CrewmeisterStatusCoordinator(hass, entry, client)
    absence_coordinator = CrewmeisterAbsenceCoordinator(hass, entry, client)

    # Raises ConfigEntryAuthFailed / ConfigEntryNotReady as appropriate
    await status_coordinator.async_config_entry_first_refresh()
    # Absences are not essential: a failure only leaves the calendar unavailable
    await absence_coordinator.async_refresh()

    config = AssistantConfig.from_options(entry.options)
    defaults = stamp_defaults(entry.options)
    assistant = CrewmeisterAssistant(
        hass, entry, client, status_coordinator, absence_coordinator, config, defaults
    )
    entry.runtime_data = CrewmeisterRuntimeData(
        client=client,
        status_coordinator=status_coordinator,
        absence_coordinator=absence_coordinator,
        stamp_defaults=defaults,
        config=config,
        assistant=assistant,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await assistant.async_start()
    entry.async_on_unload(assistant.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CrewmeisterConfigEntry) -> bool:
    """Unload a Crewmeister config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: CrewmeisterConfigEntry) -> None:
    """Delete the stored assistant state of a removed entry."""

    await async_remove_assistant_store(hass, entry.entry_id)
