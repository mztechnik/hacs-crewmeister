"""Sensor entities for Crewmeister."""
from __future__ import annotations

from datetime import datetime

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import CrewmeisterStatusCoordinator

ATTR_SOURCE = "Data provided by Crewmeister"


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crewmeister sensors."""

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: CrewmeisterStatusCoordinator = runtime_data["coordinator"]

    entities: list[CrewmeisterBaseEntity] = [
        CrewmeisterStatusSensor(coordinator, entry.entry_id, entry.title),
        CrewmeisterLastStampSensor(coordinator, entry.entry_id, entry.title),
    ]
    async_add_entities(entities)


class CrewmeisterBaseEntity(CoordinatorEntity[CrewmeisterStatusCoordinator]):
    """Base entity for Crewmeister sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CrewmeisterStatusCoordinator, entry_id: str, title: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._title = title

    @property
    def device_info(self) -> DeviceInfo | None:
        identity = self.coordinator.data.get("identity")
        if identity is None:
            return None
        name = identity.full_name or identity.email or self._title or "Crewmeister"
        return DeviceInfo(
            identifiers={(DOMAIN, str(identity.user_id))},
            manufacturer="Crewmeister",
            name=name,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ATTRIBUTION: ATTR_SOURCE}


class CrewmeisterStatusSensor(CrewmeisterBaseEntity, SensorEntity):
    """Sensor providing the current Crewmeister status."""

    _attr_translation_key = "status"

    def __init__(self, coordinator: CrewmeisterStatusCoordinator, entry_id: str, title: str) -> None:
        super().__init__(coordinator, entry_id, title)
        self._attr_unique_id = f"{entry_id}_status"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        latest = self.coordinator.data.get("latest_stamp")
        if latest:
            attributes.update(
                {
                    "stamp_type": latest.get("stampType"),
                    "stamp_status": latest.get("stampStatus"),
                    "timestamp": latest.get("timestamp"),
                }
            )
        return attributes


class CrewmeisterLastStampSensor(CrewmeisterBaseEntity, SensorEntity):
    """Sensor exposing the timestamp of the last Crewmeister stamp."""

    _attr_translation_key = "last_stamp"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CrewmeisterStatusCoordinator, entry_id: str, title: str) -> None:
        super().__init__(coordinator, entry_id, title)
        self._attr_unique_id = f"{entry_id}_last_stamp"

    @property
    def native_value(self) -> datetime | None:
        latest = self.coordinator.data.get("latest_stamp")
        if not latest:
            return None
        timestamp = latest.get("timestamp")
        if not timestamp:
            return None
        dt_value = dt_util.parse_datetime(timestamp)
        if dt_value is None:
            return None
        if dt_value.tzinfo is None:
            dt_value = dt_util.as_utc(dt_value)
        return dt_value
