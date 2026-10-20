"""Button entities for Crewmeister."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    CrewmeisterError,
    InvalidTransitionError,
    StampType,
    WorkStatus,
    validate_transition,
)
from .const import DOMAIN
from .coordinator import CrewmeisterConfigEntry, CrewmeisterStatusCoordinator
from .entity import CrewmeisterEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class CrewmeisterButtonEntityDescription(ButtonEntityDescription):
    """Describes a Crewmeister stamp button."""

    stamp_type: StampType


BUTTON_DESCRIPTIONS: tuple[CrewmeisterButtonEntityDescription, ...] = (
    CrewmeisterButtonEntityDescription(
        key="clock_in",
        translation_key="clock_in",
        stamp_type=StampType.START_WORK,
    ),
    CrewmeisterButtonEntityDescription(
        key="start_break",
        translation_key="start_break",
        stamp_type=StampType.START_BREAK,
    ),
    CrewmeisterButtonEntityDescription(
        key="clock_out",
        translation_key="clock_out",
        stamp_type=StampType.CLOCK_OUT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrewmeisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Crewmeister button entities."""

    runtime = entry.runtime_data
    coordinator = runtime.status_coordinator
    entities: list[ButtonEntity] = [
        CrewmeisterStampButton(coordinator, entry, description)
        for description in BUTTON_DESCRIPTIONS
    ]
    entities.append(CrewmeisterNextStepButton(coordinator, entry))
    if runtime.config.notify_live and runtime.config.notify_targets:
        entities.append(CrewmeisterShowLiveButton(coordinator, entry))
    async_add_entities(entities)


class _CrewmeisterButton(CrewmeisterEntity[CrewmeisterStatusCoordinator], ButtonEntity):
    """Button of one Crewmeister user."""

    def __init__(
        self, coordinator: CrewmeisterStatusCoordinator, entry: CrewmeisterConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._runtime = entry.runtime_data

    async def _async_stamp(self, stamp_type: StampType, *, refreshed: bool = False) -> None:
        if not refreshed:
            # The polled status may be outdated if the user stamped elsewhere
            await self.coordinator.async_refresh()
        if self.coordinator.last_update_success:
            try:
                validate_transition(stamp_type, self.coordinator.data.status)
            except InvalidTransitionError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key=err.reason
                ) from err

        defaults = self._runtime.stamp_defaults
        note, location = self._runtime.assistant.stamp_note_and_location(defaults.note)
        try:
            await self._runtime.client.async_create_stamp(
                stamp_type,
                note=note,
                location=location,
                time_account_id=defaults.time_account_id,
            )
        except CrewmeisterError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="stamp_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        await self.coordinator.async_request_refresh()


class CrewmeisterStampButton(_CrewmeisterButton):
    """Button creating a stamp of a fixed type."""

    entity_description: CrewmeisterButtonEntityDescription

    def __init__(
        self,
        coordinator: CrewmeisterStatusCoordinator,
        entry: CrewmeisterConfigEntry,
        description: CrewmeisterButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self._async_stamp(self.entity_description.stamp_type)


# Stamp of the "next step" button and the icon announcing it
NEXT_STEP: dict[WorkStatus, tuple[StampType, str]] = {
    WorkStatus.CLOCKED_OUT: (StampType.START_WORK, "mdi:login"),
    WorkStatus.CLOCKED_IN: (StampType.START_BREAK, "mdi:coffee"),
    WorkStatus.ON_BREAK: (StampType.START_WORK, "mdi:briefcase-clock"),
}


class CrewmeisterNextStepButton(_CrewmeisterButton):
    """Button clocking in, starting a break or resuming, depending on the status.

    Meant for widgets with a single button; clocking out has its own button.
    """

    _attr_translation_key = "next_step"

    def __init__(
        self, coordinator: CrewmeisterStatusCoordinator, entry: CrewmeisterConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "next_step")

    @property
    def icon(self) -> str | None:
        """Show what pressing the button does."""

        if not self.coordinator.data:
            return None
        return NEXT_STEP[self.coordinator.data.status][1]

    async def async_press(self) -> None:
        # The step depends on the status, which must therefore be current
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success or not self.coordinator.data:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="status_unavailable"
            )
        await self._async_stamp(NEXT_STEP[self.coordinator.data.status][0], refreshed=True)


class CrewmeisterShowLiveButton(_CrewmeisterButton):
    """Button showing the live display again, e.g. after it was swiped away."""

    _attr_translation_key = "show_live"

    def __init__(
        self, coordinator: CrewmeisterStatusCoordinator, entry: CrewmeisterConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "show_live")

    async def async_press(self) -> None:
        await self._runtime.assistant.async_show_live()
