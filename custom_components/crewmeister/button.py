"""Button entities for Crewmeister."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CrewmeisterError, InvalidTransitionError, StampType, validate_transition
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

    coordinator = entry.runtime_data.status_coordinator
    async_add_entities(
        CrewmeisterStampButton(coordinator, entry, description)
        for description in BUTTON_DESCRIPTIONS
    )


class CrewmeisterStampButton(CrewmeisterEntity[CrewmeisterStatusCoordinator], ButtonEntity):
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
        self._runtime = entry.runtime_data

    async def async_press(self) -> None:
        stamp_type = self.entity_description.stamp_type

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
