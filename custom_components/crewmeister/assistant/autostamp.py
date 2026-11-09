"""Automatic stamping based on presence at the office or at home."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from ..api import StampType, WorkStatus
from ..logic.config import StampMode
from ..logic.presence import EventType, Phase, PresenceEvent, advance
from ..logic.rules import Decision, Outcome, Reason, Rules, Situation, on_arrival, on_departure
from ..logic.sources import (
    Location,
    Reading,
    WorkPresence,
    activity_reading,
    combine,
    wifi_reading,
    work_presence,
    zone_reading,
)
from ..logic.worktime import DaySummary
from ..notifications import Action, Button, Kind
from .util import action_arg, hm, iso

if TYPE_CHECKING:
    from .core import CrewmeisterAssistant

_LOGGER = logging.getLogger(__name__)

# Try again after this time if Crewmeister was not reachable for a decision
RETRY_DECISION = timedelta(minutes=1)

# Notification texts per reason: (title, message)
ASK_TEXTS: dict[Reason, tuple[str, str]] = {
    Reason.ARRIVED: ("arrived_title", "arrived_message"),
    Reason.SUPPRESSED: ("arrived_again_title", "arrived_again_message"),
    Reason.RETURNED: ("returned_title", "returned_message"),
    Reason.BREAK_WINDOW: ("break_window_title", "break_window_message"),
    Reason.END_OF_DAY: ("end_of_day_left_title", "end_of_day_left_message"),
    Reason.CATCH_UP: ("end_of_day_left_title", "catch_up_message"),
    Reason.LEFT_DURING_WORK: ("left_title", "left_message"),
}


class AutoStamper:
    """Turn presence changes into stamps according to the stamping rules."""

    def __init__(self, assistant: CrewmeisterAssistant) -> None:
        self._a = assistant
        self._unsubs: list[CALLBACK_TYPE] = []
        self._ready = False
        self._lock = asyncio.Lock()
        self._arrival_recheck: datetime | None = None

    # ------------------------------------------------------------------ lifecycle

    def async_start(self) -> None:
        """Watch the configured sources once Home Assistant has started."""

        cfg = self._a.config
        if not cfg.presence_configured:
            return
        self._unsubs.append(
            async_track_state_change_event(self._a.hass, self._entities(), self._async_changed)
        )
        # Device trackers may still be loading; judge presence once HA has started
        self._unsubs.append(async_at_started(self._a.hass, self._async_started))

    def async_stop(self) -> None:
        """Stop watching."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._ready = False

    def _entities(self) -> list[str]:
        cfg = self._a.config
        entities = [*cfg.work_zones, *cfg.presence_entities, *cfg.home_office_presence_sensors]
        entities += [e for e in (cfg.person, cfg.wifi_sensor, cfg.home_office_power_sensor) if e]
        return list(dict.fromkeys(entities))

    @callback
    def _async_started(self, _hass: HomeAssistant) -> None:
        self._ready = True
        self._a.entry.async_create_task(self._a.hass, self.async_evaluate(startup=True))

    @callback
    def _async_changed(self, _event: Event[EventStateChangedData]) -> None:
        if self._ready:
            self._a.entry.async_create_task(self._a.hass, self.async_evaluate())

    # ------------------------------------------------------------------- reading

    def readings(self) -> dict[str, Reading]:
        """Return the reading of every configured source (for diagnostics)."""

        cfg = self._a.config
        states = self._a.hass.states
        result: dict[str, Reading] = {}
        person = states.get(cfg.person) if cfg.person else None
        person_state = person.state if person else None
        if cfg.person and cfg.work_zones:
            in_zone = any(
                (zone := states.get(zone_id)) is not None
                and cfg.person in zone.attributes.get("persons", [])
                for zone_id in cfg.work_zones
            )
            result["zone"] = zone_reading(person_state, in_zone)
        if cfg.wifi_sensor and cfg.wifi_ssids:
            wifi = states.get(cfg.wifi_sensor)
            result["wifi"] = wifi_reading(wifi.state if wifi else None, cfg.wifi_ssids)
        for entity_id in cfg.presence_entities:
            state = states.get(entity_id)
            value = state.state if state else None
            result[entity_id] = (
                Reading.PRESENT
                if value in (STATE_ON, STATE_HOME)
                else Reading.AWAY
                if value in (STATE_OFF, STATE_NOT_HOME)
                else Reading.UNKNOWN
            )
        if cfg.home_office_configured:
            power = (
                states.get(cfg.home_office_power_sensor) if cfg.home_office_power_sensor else None
            )
            result["home_office"] = activity_reading(
                person_state,
                power.state if power else None,
                cfg.home_office_power_threshold,
                [
                    s.state if (s := states.get(e)) else None
                    for e in cfg.home_office_presence_sensors
                ],
                power_configured=cfg.home_office_power_sensor is not None,
            )
        return result

    def presence(self) -> WorkPresence:
        """Return the combined presence of all sources."""

        readings = self.readings()
        office = [r for key, r in readings.items() if key != "home_office"]
        return work_presence(
            combine(office, self._a.config.office_combine) if office else None,
            readings.get("home_office"),
        )

    def _last_changed(self) -> datetime | None:
        changes = [
            state.last_changed
            for entity_id in self._entities()
            if (state := self._a.hass.states.get(entity_id)) is not None
        ]
        return max(changes) if changes else None

    # ----------------------------------------------------------------- evaluation

    async def async_evaluate(self, *, startup: bool = False) -> None:
        """Feed the current presence into the state machine and act on changes."""

        if not self._ready:
            return
        async with self._lock:
            cfg = self._a.config
            state = self._a.state.presence
            presence = self.presence()
            before = (state.present, state.location)
            home = Location.HOME_OFFICE
            update = advance(
                state,
                presence,
                dt_util.utcnow(),
                arrival_delay=cfg.home_office_activity_delay
                if presence.location == home
                else cfg.arrival_delay,
                departure_delay=cfg.home_office_idle_timeout
                if state.location == home
                else cfg.departure_delay,
                changed_at=self._last_changed() if startup else None,
            )
            if update.changed:
                if state.present and state.location is not None:
                    self._a.state.last_location = state.location.value
                self._a.save()
            if (state.present, state.location) != before:
                self._a.notify_listeners()
            if update.event is not None:
                await self._async_event(update.event)

    async def _async_event(self, event: PresenceEvent) -> None:
        _LOGGER.debug("Presence event: %s", event)
        if event.type == EventType.ARRIVED:
            self._a.state.departure_recheck_at = None
            self._arrival_recheck = None
            await self._async_clear_question()
            await self._async_arrival()
        else:
            self._a.state.left_at = event.at
            self._a.save()
            await self._async_departure(event.at, event.location)

    async def async_tick(self) -> None:
        """Confirm pending changes and evaluate waiting decisions."""

        if not self._ready:
            return
        state = self._a.state.presence
        now = dt_util.utcnow()
        if state.phase in (Phase.ARRIVING, Phase.LEAVING):
            await self.async_evaluate()
        if (
            state.present
            and state.arrival_open
            and (self._arrival_recheck is None or now >= self._arrival_recheck)
        ):
            await self._async_arrival()
        recheck = self._a.state.departure_recheck_at
        if (
            state.phase == Phase.AWAY
            and state.departure_open
            and state.left_at is not None
            and recheck is not None
            and now >= recheck
        ):
            location = _location(self._a.state.last_location)
            await self._async_departure(state.left_at, location, catch_up=True)
        expires = self._a.state.question_expires
        if expires is not None and now >= expires:
            await self._async_clear_question()

    async def async_midnight(self) -> None:
        """A new day: forget yesterday's departure, clock in again if still present."""

        state = self._a.state.presence
        self._a.state.departure_recheck_at = None
        state.departure_open = False
        data = self._a.status.data
        if state.present and data is not None and data.status == WorkStatus.CLOCKED_OUT:
            # E.g. a PC left running overnight: today starts with the time window
            state.arrival_open = True
            self._arrival_recheck = None
        self._a.save()

    def status_changed(self, previous: WorkStatus | None, summary: DaySummary) -> None:
        """Remember a clock out; later arrivals today only ask."""

        if (
            previous is not None
            and previous != WorkStatus.CLOCKED_OUT
            and summary.status == WorkStatus.CLOCKED_OUT
        ):
            state = self._a.state.presence
            state.suppressed_on = dt_util.now().date()
            state.arrival_open = False
            self._a.save()

    # ------------------------------------------------------------------- rules

    def _rules(self, location: Location | None) -> Rules:
        cfg = self._a.config
        office = location != Location.HOME_OFFICE
        window = cfg.break_window
        return Rules(
            arrival_mode=cfg.arrival_mode,
            break_mode=cfg.break_mode,
            end_of_day_mode=cfg.end_of_day_mode,
            # The walk from the zone to the desk only exists at the office
            arrival_offset=cfg.arrival_offset if office else timedelta(0),
            departure_offset=cfg.departure_offset if office else timedelta(0),
            window_start=cfg.window_start,
            window_end=cfg.window_end,
            break_start=window[0] if window else None,
            break_end=window[1] if window else None,
            end_of_day_time=cfg.end_of_day_time,
            end_of_day_on_target=cfg.end_of_day_on_target,
            ask_on_leave=cfg.ask_on_leave,
            ask_timeout=cfg.ask_timeout,
            catch_up=cfg.catch_up,
        )

    def _situation(self, summary: DaySummary) -> Situation:
        now = dt_util.now()
        latest = summary.latest.timestamp if summary.latest else None
        end = self._a.expected_end(summary)
        return Situation(
            now=now,
            status=summary.status,
            latest_stamp_at=dt_util.as_local(latest) if latest else None,
            enabled=self._a.enabled,
            no_work_reason=self._a.no_work_reason(now.date()),
            target_reached_at=dt_util.as_local(end) if end else None,
            suppressed=self._a.state.presence.suppressed(now.date()),
        )

    async def _async_arrival(self) -> None:
        state = self._a.state.presence
        if not state.arrival_open or not state.present or state.arrived_at is None:
            return
        summary = await self._a.async_fresh_summary()
        now = dt_util.utcnow()
        if summary is None:
            # Do not lose the arrival: decide once Crewmeister answers again
            self._arrival_recheck = now + RETRY_DECISION
            return
        # An arrival from an earlier day (e.g. PC running overnight) counts from today
        arrived = max(state.arrived_at, dt_util.start_of_local_day())
        decision = on_arrival(
            self._rules(state.location), self._situation(summary), dt_util.as_local(arrived)
        )
        if decision.outcome == Outcome.WAIT:
            self._arrival_recheck = decision.recheck_at
            self._record(decision, state.location)
            return
        state.arrival_open = False
        self._arrival_recheck = None
        self._a.save()
        await self._async_apply(decision, state.location)

    async def _async_departure(
        self, left_at: datetime, location: Location | None, *, catch_up: bool = False
    ) -> None:
        state = self._a.state.presence
        summary = await self._a.async_fresh_summary()
        if summary is None:
            self._a.state.departure_recheck_at = dt_util.utcnow() + RETRY_DECISION
            self._a.save()
            return
        decision = on_departure(
            self._rules(location),
            self._situation(summary),
            dt_util.as_local(left_at),
            catch_up=catch_up,
        )
        self._a.state.departure_recheck_at = decision.recheck_at
        if decision.recheck_at is None:
            state.departure_open = False
        self._a.save()
        if decision.outcome == Outcome.WAIT:
            self._record(decision, location)
            return
        await self._async_apply(decision, location)

    # ------------------------------------------------------------------ actions

    async def _async_apply(self, decision: Decision, location: Location | None) -> None:
        result = None
        loc = location.value if location else None
        if decision.outcome == Outcome.STAMP and decision.stamp_type is not None:
            result = await self._a.async_stamp(
                decision.stamp_type, decision.at, automatic=True, location=loc
            )
        elif decision.outcome == Outcome.ASK:
            await self._async_ask(decision, location)
        self._record(decision, location, result.value if result else None)

    async def _async_ask(self, decision: Decision, location: Location | None) -> None:
        a = self._a
        if not a.notifier.enabled or decision.at is None:
            return
        title_key, message_key = ASK_TEXTS.get(decision.reason, ASK_TEXTS[Reason.ARRIVED])
        if decision.reason == Reason.ARRIVED and location == Location.HOME_OFFICE:
            title_key, message_key = "home_office_title", "home_office_message"
        time_str = hm(decision.at)
        arg = action_arg(decision.at, decision.expires)
        buttons = [
            self._button(stamp_type, decision.reason, time_str, arg)
            for stamp_type in decision.choices
        ]
        buttons.append(Button(a.t("btn_ignore"), Action.IGNORE))
        departure = decision.stamp_type != StampType.START_WORK
        await a.notifier.async_send(
            Kind.PRESENCE,
            a.t(title_key),
            a.t(message_key, time=time_str),
            buttons,
            time_sensitive=departure,
        )
        if decision.expires is not None:
            a.state.question_expires = decision.expires
            a.save()

    def _button(
        self, stamp_type: StampType, reason: Reason, time_str: str, arg: str | None
    ) -> Button:
        t = self._a.t
        if stamp_type == StampType.START_WORK:
            if reason == Reason.RETURNED:
                return Button(t("btn_resume"), Action.RESUME, arg)
            return Button(t("btn_clock_in_at", time=time_str), Action.CLOCK_IN, arg)
        if stamp_type == StampType.START_BREAK:
            return Button(t("btn_break_at", time=time_str), Action.START_BREAK, arg)
        return Button(t("btn_clock_out_at", time=time_str), Action.CLOCK_OUT, arg)

    async def _async_clear_question(self) -> None:
        if self._a.state.question_expires is None:
            return
        self._a.state.question_expires = None
        self._a.save()
        await self._a.notifier.async_clear(Kind.PRESENCE)

    def _record(
        self, decision: Decision, location: Location | None, result: str | None = None
    ) -> None:
        """Remember the decision for the automation sensor."""

        record: dict[str, Any] = {
            "time": dt_util.utcnow().isoformat(),
            "outcome": decision.outcome.value,
            "reason": decision.reason.value,
            "stamp_type": decision.stamp_type.value if decision.stamp_type else None,
            "stamp_at": iso(decision.at),
            "location": location.value if location else None,
            "result": result,
        }
        if record != self._a.state.decision:
            _LOGGER.debug("Automatic stamping decision: %s", record)
            self._a.state.decision = record
            self._a.save()
            self._a.notify_listeners()

    @property
    def mode_summary(self) -> dict[str, StampMode]:
        """Return the configured modes (for diagnostics)."""

        cfg = self._a.config
        return {
            "arrival": cfg.arrival_mode,
            "break": cfg.break_mode,
            "end_of_day": cfg.end_of_day_mode,
        }


def _location(value: str | None) -> Location | None:
    try:
        return Location(value)
    except ValueError:
        return None
