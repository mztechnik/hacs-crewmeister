"""Vacation and other absences from Crewmeister, a calendar or a binary sensor."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..logic.absence import AbsenceInfo, CalendarItem, absence_today, matching_calendar_item
from ..logic.workday import NoWorkReason, no_work_reason

if TYPE_CHECKING:
    from .core import CrewmeisterAssistant

_LOGGER = logging.getLogger(__name__)

CALENDAR_REFRESH = timedelta(minutes=30)


class AbsenceTracker:
    """Tell whether the user is absent today and whether a day is a working day."""

    def __init__(self, assistant: CrewmeisterAssistant) -> None:
        self._a = assistant
        self._unsubs: list[CALLBACK_TYPE] = []
        self._calendar_item: CalendarItem | None = None
        self._calendar_day: date | None = None
        self._calendar_loaded_at: datetime | None = None
        self._calendar_failed = False

    async def async_start(self) -> None:
        """Load the calendar and watch the configured entities."""

        cfg = self._a.config
        entities = [e for e in (cfg.absence_calendar, cfg.absence_sensor, cfg.workday_entity) if e]
        if entities:
            self._unsubs.append(
                async_track_state_change_event(self._a.hass, entities, self._async_changed)
            )
        if cfg.absence_calendar:
            await self._async_refresh_and_notify()

    def async_stop(self) -> None:
        """Stop watching."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @property
    def ready(self) -> bool:
        """Return whether today's absences are known.

        False while the configured calendar could not be read for today; then
        nobody knows whether today is a vacation day.
        """

        if not self._a.config.absence_calendar:
            return True
        return self._calendar_day == dt_util.now().date()

    @callback
    def _async_changed(self, event: Event[EventStateChangedData]) -> None:
        if event.data["entity_id"] == self._a.config.absence_calendar:
            # An event started or ended, the calendar may have been edited
            self._a.entry.async_create_task(self._a.hass, self._async_refresh_and_notify())
        else:
            self._a.notify_listeners()

    async def _async_refresh_and_notify(self) -> None:
        await self.async_refresh_calendar()
        self._a.notify_listeners()

    async def async_tick(self) -> None:
        """Reload the calendar now and then."""

        loaded = self._calendar_loaded_at
        if self._a.config.absence_calendar and (
            loaded is None or dt_util.utcnow() - loaded >= CALENDAR_REFRESH
        ):
            await self._async_refresh_and_notify()

    async def async_midnight(self) -> None:
        """A new day: look at today's calendar events."""

        await self._async_refresh_and_notify()

    async def async_refresh_calendar(self) -> None:
        """Load today's events of the absence calendar."""

        cfg = self._a.config
        if not cfg.absence_calendar:
            return
        today = dt_util.now().date()
        start = dt_util.start_of_local_day(today)
        try:
            response = await self._a.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": cfg.absence_calendar,
                    "start_date_time": start.isoformat(),
                    "end_date_time": (start + timedelta(days=1)).isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            # Retried every minute: warn once, not with every attempt
            if not self._calendar_failed:
                _LOGGER.warning("Could not read calendar %s: %s", cfg.absence_calendar, err)
            self._calendar_failed = True
            # Keep today's result; retry with the next refresh
            if self._calendar_day != today:
                self._calendar_item = None
            return
        events = ((response or {}).get(cfg.absence_calendar) or {}).get("events") or []
        items = [item for event in events if (item := _calendar_item(event)) is not None]
        self._calendar_item = matching_calendar_item(
            items, today, cfg.absence_keywords, cfg.window_start, cfg.window_end
        )
        self._calendar_day = today
        self._calendar_loaded_at = dt_util.utcnow()
        self._calendar_failed = False

    def info(self) -> AbsenceInfo | None:
        """Return why the user is absent today, ``None`` if not."""

        cfg = self._a.config
        today = dt_util.now().date()
        sensor = self._a.hass.states.get(cfg.absence_sensor) if cfg.absence_sensor else None
        crewmeister = [(e.absence, e.event.summary) for e in self._a.absences.current()]
        return absence_today(
            today,
            crewmeister=crewmeister,
            calendar_item=self._calendar_item if self._calendar_day == today else None,
            sensor_on=sensor is not None and sensor.state == STATE_ON,
            sensor_name=sensor.name if sensor is not None else None,
        )

    def no_work_reason(self, day: date) -> str | None:
        """Return why ``day`` is no working day ("weekday", "workday_sensor", "absence")."""

        cfg = self._a.config
        sensor_on: bool | None = None
        state = self._a.hass.states.get(cfg.workday_entity) if cfg.workday_entity else None
        if state and state.state in (STATE_ON, STATE_OFF):
            sensor_on = state.state == STATE_ON
        absences = [entry.absence for entry in self._a.absences.current()]
        reason = no_work_reason(day, cfg.workdays, sensor_on, absences)
        if reason is not None:
            return reason.value
        if day == dt_util.now().date() and self.info() is not None:
            return NoWorkReason.ABSENCE.value
        return None


def _calendar_item(event: Any) -> CalendarItem | None:
    """Convert an event of the ``calendar.get_events`` response."""

    if not isinstance(event, dict):
        return None
    start, end = _when(event.get("start")), _when(event.get("end"))
    if start is None or end is None:
        return None
    return CalendarItem(str(event.get("summary") or ""), start, end)


def _when(value: Any) -> date | datetime | None:
    if not isinstance(value, str):
        return None
    if "T" not in value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    parsed = dt_util.parse_datetime(value)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed
