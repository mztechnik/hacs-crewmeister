"""Binary sensors for Crewmeister."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .api import WorkStatus
from .coordinator import (
    CrewmeisterAbsenceCoordinator,
    CrewmeisterConfigEntry,
    CrewmeisterStatusCoordinator,
)
from .entity import CrewmeisterEntity

if TYPE_CHECKING:
    from .assistant import CrewmeisterAssistant

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrewmeisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Crewmeister binary sensors."""

    status = entry.runtime_data.status_coordinator
    absences = entry.runtime_data.absence_coordinator
    async_add_entities(
        [
            CrewmeisterWorkingBinarySensor(status, entry, "working"),
            CrewmeisterBreakBinarySensor(status, entry, "on_break"),
            CrewmeisterWorkdayBinarySensor(absences, entry, "workday"),
            CrewmeisterAbsenceBinarySensor(absences, entry, "absent"),
        ]
    )


class CrewmeisterWorkingBinarySensor(
    CrewmeisterEntity[CrewmeisterStatusCoordinator], BinarySensorEntity
):
    """On while the user is clocked in and not on a break."""

    _attr_translation_key = "working"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.status == WorkStatus.CLOCKED_IN

    @property
    def extra_state_attributes(self) -> dict[str, bool] | None:
        if self.coordinator.data.status == WorkStatus.ON_BREAK:
            return {"on_break": True}
        return None


class CrewmeisterBreakBinarySensor(
    CrewmeisterEntity[CrewmeisterStatusCoordinator], BinarySensorEntity
):
    """On while the user is on a break."""

    _attr_translation_key = "on_break"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.status == WorkStatus.ON_BREAK

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        summary = self.coordinator.data.today()
        if summary.status != WorkStatus.ON_BREAK or summary.status_since is None:
            return None
        return {"since": summary.status_since.isoformat()}


class _DailyAbsenceSensor(CrewmeisterEntity[CrewmeisterAbsenceCoordinator], BinarySensorEntity):
    """Binary sensor that is re-evaluated at day and half day boundaries."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for hour in (0, 12):
            self.async_on_remove(
                async_track_time_change(self.hass, self._async_tick, hour=hour, minute=0, second=1)
            )

    @callback
    def _async_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()


class CrewmeisterWorkdayBinarySensor(_DailyAbsenceSensor):
    """On if today is a working day (weekday, workday sensor, no full day absence)."""

    _attr_translation_key = "workday"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        workday_entity = self.coordinator.config_entry.runtime_data.config.workday_entity
        if workday_entity:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, workday_entity, self._async_workday_changed
                )
            )
        self.async_on_remove(
            self.coordinator.config_entry.runtime_data.assistant.async_add_listener(
                self.async_write_ha_state
            )
        )

    @callback
    def _async_workday_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # Without (current) absence data the day is judged by weekday and workday sensor
        return True

    def _reason(self) -> str | None:
        assistant = self.coordinator.config_entry.runtime_data.assistant
        return assistant.no_work_reason(dt_util.now().date())

    @property
    def is_on(self) -> bool:
        return self._reason() is None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reason = self._reason()
        return {"reason": reason} if reason else None


class CrewmeisterAbsenceBinarySensor(_DailyAbsenceSensor):
    """On during an absence such as vacation or sickness.

    Sources: Crewmeister, and optionally a calendar and a binary sensor.
    """

    _attr_translation_key = "absent"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._assistant.async_add_listener(self.async_write_ha_state))

    @property
    def _assistant(self) -> CrewmeisterAssistant:
        return self.coordinator.config_entry.runtime_data.assistant

    @property
    def available(self) -> bool:
        # A calendar or sensor still tells about absences without Crewmeister data
        cfg = self._assistant.config
        return (
            self.coordinator.data_is_current()
            or cfg.absence_calendar is not None
            or cfg.absence_sensor is not None
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.active() is not None or self._assistant.absence.info() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        entry = self.coordinator.active()
        if entry is not None:
            return {
                "source": "crewmeister",
                "absence_type": entry.event.summary,
                "start": entry.event.start.isoformat(),
                "end": entry.event.end.isoformat(),
            }
        info = self._assistant.absence.info()
        if info is None:
            return None
        return {"source": info.source.value, "absence_type": info.title}
