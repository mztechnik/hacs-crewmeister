"""Switch to pause presence based stamping."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CrewmeisterConfigEntry, CrewmeisterStatusCoordinator
from .entity import CrewmeisterEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrewmeisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch if presence or home office detection is configured."""

    config = entry.runtime_data.config
    if config.presence_configured or config.home_office_configured:
        async_add_entities(
            [CrewmeisterAutoStampSwitch(entry.runtime_data.status_coordinator, entry, "auto_stamp")]
        )


class CrewmeisterAutoStampSwitch(CrewmeisterEntity[CrewmeisterStatusCoordinator], SwitchEntity):
    """Turns presence based stamping (automatic and asking) on or off."""

    _attr_translation_key = "auto_stamp"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: CrewmeisterStatusCoordinator, entry: CrewmeisterConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._assistant = entry.runtime_data.assistant

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._assistant.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._assistant.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._assistant.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._assistant.async_set_enabled(False)
