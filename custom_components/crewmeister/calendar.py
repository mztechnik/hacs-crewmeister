"""Calendar entity for Crewmeister absences."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .absences import async_absences_to_events
from .api import CrewmeisterError
from .const import DOMAIN
from .coordinator import CrewmeisterAbsenceCoordinator, CrewmeisterConfigEntry
from .entity import CrewmeisterEntity
from .helpers import absence_states

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrewmeisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Crewmeister calendar entity."""

    async_add_entities(
        [CrewmeisterAbsenceCalendar(entry.runtime_data.absence_coordinator, entry, "absences")]
    )


class CrewmeisterAbsenceCalendar(CrewmeisterEntity[CrewmeisterAbsenceCoordinator], CalendarEntity):
    """Calendar with the user's absences."""

    _attr_translation_key = "absences"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming absence."""

        upcoming = self.coordinator.upcoming()
        return upcoming[0].event if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        client = self.coordinator.client
        try:
            identity = await client.async_get_identity()
            absences = await client.async_get_absences(
                identity.user_id,
                start_date.date(),
                end_date.date(),
                set(absence_states(self.coordinator.config_entry.options)),
            )
        except CrewmeisterError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="absences_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return await async_absences_to_events(client, absences)
