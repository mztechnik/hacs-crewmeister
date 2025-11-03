"""Binary sensors for Crewmeister."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensor import CrewmeisterBaseEntity
from .coordinator import CrewmeisterStatusCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crewmeister binary sensors."""

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: CrewmeisterStatusCoordinator = runtime_data["coordinator"]

    async_add_entities([CrewmeisterWorkingBinarySensor(coordinator, entry.entry_id, entry.title)])


class CrewmeisterWorkingBinarySensor(CrewmeisterBaseEntity, BinarySensorEntity):
    """Binary sensor to indicate if the user is clocked in."""

    _attr_translation_key = "working"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: CrewmeisterStatusCoordinator, entry_id: str, title: str) -> None:
        super().__init__(coordinator, entry_id, title)
        self._attr_unique_id = f"{entry_id}_working"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        if data.get("is_on_break"):
            return False
        return data.get("is_clocked_in")

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        attributes = super().extra_state_attributes
        data = self.coordinator.data
        if data.get("is_on_break"):
            attributes["on_break"] = True
        return attributes
