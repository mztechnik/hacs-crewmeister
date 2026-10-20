"""Base entity for the Crewmeister integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import ATTRIBUTION, CONF_EMAIL, CONF_FULL_NAME, CONF_USER_ID, DOMAIN
from .coordinator import CrewmeisterConfigEntry


class CrewmeisterEntity[CoordinatorT: DataUpdateCoordinator](CoordinatorEntity[CoordinatorT]):
    """Entity belonging to the device of one Crewmeister user."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: CoordinatorT, entry: CrewmeisterConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.data[CONF_USER_ID]))},
            manufacturer="Crewmeister",
            name=entry.data.get(CONF_FULL_NAME) or entry.data.get(CONF_EMAIL) or entry.title,
        )
