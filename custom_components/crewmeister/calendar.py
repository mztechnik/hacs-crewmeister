"""Calendar entity for Crewmeister absences."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import CrewmeisterClient, CrewmeisterError
from .const import (
    ABSENCE_APPROVED_STATES,
    ABSENCE_DEFAULT_LOOKAHEAD_DAYS,
    CONF_ABSENCE_STATES,
    DOMAIN,
)
from .coordinator import CrewmeisterStatusCoordinator

ATTR_ATTRIBUTION_VALUE = "Data provided by Crewmeister"


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Crewmeister calendar entity."""

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    client: CrewmeisterClient = runtime_data["client"]
    coordinator: CrewmeisterStatusCoordinator = runtime_data["coordinator"]

    async_add_entities([CrewmeisterAbsenceCalendar(client, coordinator, entry)])


class CrewmeisterAbsenceCalendar(CoordinatorEntity[CrewmeisterStatusCoordinator], CalendarEntity):
    """Calendar entity exposing Crewmeister absences."""

    _attr_has_entity_name = True
    _attr_translation_key = "absences"

    def __init__(self, client: CrewmeisterClient, coordinator: CrewmeisterStatusCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_absences"
        self._attr_name = f"{entry.title} absences"
        self._event: CalendarEvent | None = None
        self._upcoming: list[CalendarEvent] = []

    @property
    def device_info(self) -> DeviceInfo | None:
        identity = self.coordinator.data.get("identity")
        if identity is None:
            return None
        name = identity.full_name or identity.email or self._entry.title or "Crewmeister"
        return DeviceInfo(
            identifiers={(DOMAIN, str(identity.user_id))},
            manufacturer="Crewmeister",
            name=name,
        )

    @property
    def event(self) -> CalendarEvent | None:
        return self._event

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        attributes: dict[str, object] = {ATTR_ATTRIBUTION: ATTR_ATTRIBUTION_VALUE}
        if self._event:
            attributes.update(
                {
                    "next_summary": self._event.summary,
                    "next_start": self._event.start.isoformat(),
                    "next_end": self._event.end.isoformat(),
                }
            )
        return attributes

    async def async_update(self) -> None:
        try:
            identity = await self._client.async_get_identity()
            now = dt_util.utcnow()
            end = now + timedelta(days=ABSENCE_DEFAULT_LOOKAHEAD_DAYS)
            states = set(self._entry.options.get(CONF_ABSENCE_STATES) or ABSENCE_APPROVED_STATES)
            absences = await self._client.async_get_absences(identity.user_id, now, end, states)
        except CrewmeisterError:
            self._event = None
            self._upcoming = []
            return

        events = [event for event in await self._absences_to_events(absences) if event]
        events.sort(key=lambda evt: evt.start)
        self._upcoming = events
        self._event = events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        try:
            identity = await self._client.async_get_identity()
            states = set(self._entry.options.get(CONF_ABSENCE_STATES) or ABSENCE_APPROVED_STATES)
            absences = await self._client.async_get_absences(identity.user_id, start_date, end_date, states)
        except CrewmeisterError:
            return []

        events = [event for event in await self._absences_to_events(absences) if event]
        events.sort(key=lambda evt: evt.start)
        return events

    async def _absences_to_events(self, absences: list[dict[str, object]]) -> list[CalendarEvent | None]:
        events: list[CalendarEvent | None] = []
        for absence in absences:
            absence_type = absence.get("absenceType")
            summary = "Absence"
            type_id: int | None = None
            if isinstance(absence_type, int):
                type_id = absence_type
            elif isinstance(absence_type, str) and absence_type.isdigit():
                type_id = int(absence_type)

            if type_id is not None:
                name = await self._client.async_get_absence_type_name(type_id)
                if name:
                    summary = name
                else:
                    summary = f"Absence {type_id}"

            start = _build_datetime(
                absence.get("from"),
                absence.get("fromDayPart"),
                absence.get("zoneId"),
                is_end=False,
            )
            end = _build_datetime(
                absence.get("to"),
                absence.get("toDayPart"),
                absence.get("zoneId"),
                is_end=True,
            )
            if start is None or end is None:
                continue
            state = absence.get("state") or "UNKNOWN"
            description = f"State: {state}"
            event = CalendarEvent(summary=summary, start=start, end=end, description=description)
            events.append(event)
        return events


def _build_datetime(date_str: object, day_part: object, zone_id: object, *, is_end: bool) -> datetime | None:
    if not isinstance(date_str, str):
        return None
    try:
        base_date = datetime.fromisoformat(date_str)
    except ValueError:
        return None
    if zone_id and isinstance(zone_id, str):
        try:
            tz = ZoneInfo(zone_id)
        except Exception:  # pragma: no cover - defensive
            tz = dt_util.DEFAULT_TIME_ZONE
    else:
        tz = dt_util.DEFAULT_TIME_ZONE

    if isinstance(day_part, str):
        part = day_part.upper()
    else:
        part = "AFTERNOON" if is_end else "MORNING"

    if is_end:
        selected_time = time(23, 59, 59)
        if part == "MORNING":
            selected_time = time(12, 0)
    else:
        selected_time = time(0, 0)
        if part == "AFTERNOON":
            selected_time = time(12, 0)

    localized = datetime.combine(base_date.date(), selected_time, tzinfo=tz)
    return localized
