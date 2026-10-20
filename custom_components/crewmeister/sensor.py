"""Sensor entities for Crewmeister."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import WorkStatus
from .assistant import WORK_LOCATIONS
from .coordinator import CrewmeisterConfigEntry, CrewmeisterStatusCoordinator
from .entity import CrewmeisterEntity
from .logic.worktime import DaySummary, expected_end, required_break

LIVE_UPDATE_INTERVAL = timedelta(minutes=1)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrewmeisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Crewmeister sensors."""

    coordinator = entry.runtime_data.status_coordinator
    async_add_entities(
        [
            CrewmeisterStatusSensor(coordinator, entry, "status"),
            CrewmeisterLastStampSensor(coordinator, entry, "last_stamp"),
            CrewmeisterWorkTimeSensor(coordinator, entry, "work_time_today"),
            CrewmeisterBreakTimeSensor(coordinator, entry, "break_time_today"),
        ]
    )
    config = entry.runtime_data.config
    if config.presence_configured or config.home_office_configured:
        async_add_entities([CrewmeisterWorkLocationSensor(coordinator, entry, "work_location")])


class CrewmeisterStatusSensor(CrewmeisterEntity[CrewmeisterStatusCoordinator], SensorEntity):
    """Current work status of the user."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in WorkStatus]

    @property
    def native_value(self) -> str:
        return self.coordinator.data.status.value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        stamp = self.coordinator.data.latest_stamp
        if stamp is None:
            return None
        return {
            "stamp_type": stamp.stamp_type,
            "stamp_status": stamp.status,
            "timestamp": stamp.raw.get("timestamp"),
        }


class CrewmeisterLastStampSensor(CrewmeisterEntity[CrewmeisterStatusCoordinator], SensorEntity):
    """Timestamp of the last stamp."""

    _attr_translation_key = "last_stamp"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        stamp = self.coordinator.data.latest_stamp
        return stamp.timestamp if stamp else None


def _minutes(value: timedelta) -> int:
    return int(value.total_seconds() // 60)


class _DurationTodaySensor(CrewmeisterEntity[CrewmeisterStatusCoordinator], SensorEntity):
    """Duration of today that keeps counting while a shift is running."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_tick, LIVE_UPDATE_INTERVAL)
        )

    @callback
    def _async_tick(self, _now: datetime) -> None:
        # Unchanged states are not recorded; this also covers the reset at midnight
        if self.coordinator.data:
            self.async_write_ha_state()

    def _summary(self) -> DaySummary:
        return self.coordinator.data.today()


class CrewmeisterWorkTimeSensor(_DurationTodaySensor):
    """Work time of the current day."""

    _attr_translation_key = "work_time_today"

    @property
    def native_value(self) -> int:
        return _minutes(self._summary().work)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        config = self.coordinator.config_entry.runtime_data.config
        end = None
        if target := config.target_hours(
            dt_util.as_local(summary.shift_start or summary.now).date()
        ):
            end = expected_end(summary, target, config.break_after_6h, config.break_after_9h)
        return {
            "shift_start": summary.shift_start.isoformat() if summary.shift_start else None,
            "work_since_break": _minutes(summary.work_since_break),
            "target": _minutes(target) if target else None,
            "expected_end": end.isoformat() if end else None,
        }


class CrewmeisterBreakTimeSensor(_DurationTodaySensor):
    """Break time of the current day, with the legally required break."""

    _attr_translation_key = "break_time_today"

    @property
    def native_value(self) -> int:
        return _minutes(self._summary().breaks)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        config = self.coordinator.config_entry.runtime_data.config
        required = required_break(summary.work, config.break_after_6h, config.break_after_9h)
        return {
            "required_break": _minutes(required),
            "missing_break": _minutes(max(timedelta(0), required - summary.rest_breaks)),
        }


class CrewmeisterWorkLocationSensor(CrewmeisterEntity[CrewmeisterStatusCoordinator], SensorEntity):
    """Where the user works according to the presence and home office detection.

    Independent of the stamps, so it can trigger own automations.
    """

    _attr_translation_key = "work_location"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = WORK_LOCATIONS

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
    def native_value(self) -> str:
        return self._assistant.work_location

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        since = self._assistant.work_location_since
        return {"since": since.isoformat() if since else None}
