"""Assistant automating stamping: presence detection, reminders and breaks.

Everything here is optional; without configuration the assistant stays passive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_HOME, STATE_OFF, STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .api import (
    Absence,
    CrewmeisterClient,
    CrewmeisterError,
    InvalidTransitionError,
    StampType,
    WorkStatus,
    validate_transition,
)
from .const import DOMAIN
from .helpers import StampDefaults, note_with_location
from .logic.config import AssistantConfig, StampMode
from .logic.home_office import HomeOfficeEvent, HomeOfficeEventType, HomeOfficeState, advance
from .logic.texts import format_duration, text
from .logic.workday import NoWorkReason, no_work_reason
from .logic.worktime import DaySummary, expected_end, required_break, summarize
from .notifications import (
    LIVE_BREAK_COLORS,
    LIVE_WORK_COLORS,
    Action,
    Button,
    Kind,
    Notifier,
    Segment,
    decode_action,
)

if TYPE_CHECKING:
    from .coordinator import (
        CrewmeisterAbsenceCoordinator,
        CrewmeisterConfigEntry,
        CrewmeisterStatusCoordinator,
    )

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
TICK_INTERVAL = timedelta(minutes=1)
LIVE_UPDATE_INTERVAL = timedelta(minutes=15)
# iOS ends Live Activities after at most 8 hours; restart before that
LIVE_RESTART_AFTER = timedelta(hours=7, minutes=30)
LIVE_SEPARATOR = " · "
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
EVENT_TAG_SCANNED = "tag_scanned"
# Backdated times offered in notifications must lie in this range around now
MAX_ACTION_AGE = timedelta(days=3)
ACTION_FUTURE_TOLERANCE = timedelta(minutes=2)
MAX_ADDED_BREAK = timedelta(hours=2)
# A backdated clock out offer must stay valid at least this long after sending
FORGOTTEN_OFFER_MARGIN = timedelta(hours=12)

LOCATION_OFFICE = "office"
LOCATION_HOME_OFFICE = "home_office"
LOCATION_NONE = "none"
WORK_LOCATIONS = [LOCATION_OFFICE, LOCATION_HOME_OFFICE, LOCATION_NONE]


@dataclass(slots=True)
class AssistantState:
    """State that must survive a restart of Home Assistant."""

    enabled: bool = True
    # Last time the user left work, offered when clocking out was forgotten
    left_at: datetime | None = None
    # Departure that has not been handled yet (waiting for the delay)
    pending_departure: datetime | None = None
    # Arrival that has not been handled yet (waiting for the delay)
    pending_arrival: datetime | None = None
    last_clock_in_day: date | None = None
    snooze_until: datetime | None = None
    live_started_at: datetime | None = None
    home_office: HomeOfficeState = field(default_factory=HomeOfficeState)
    # Where the user worked last ("office" / "home_office"), sent with stamps
    last_location: str | None = None
    # Markers preventing duplicate notifications, e.g. {"max_work": "2026-10-19"}
    sent: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable representation."""

        return {
            "enabled": self.enabled,
            "left_at": _iso(self.left_at),
            "pending_departure": _iso(self.pending_departure),
            "pending_arrival": _iso(self.pending_arrival),
            "last_clock_in_day": self.last_clock_in_day.isoformat()
            if self.last_clock_in_day
            else None,
            "snooze_until": _iso(self.snooze_until),
            "live_started_at": _iso(self.live_started_at),
            "home_office_since": _iso(self.home_office.session_since),
            "home_office_idle_since": _iso(self.home_office.idle_since),
            "last_location": self.last_location,
            "sent": self.sent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AssistantState:
        """Restore the state saved by ``as_dict``."""

        if not data:
            return cls()
        last_day = data.get("last_clock_in_day")
        return cls(
            enabled=bool(data.get("enabled", True)),
            left_at=dt_util.parse_datetime(data.get("left_at") or ""),
            pending_departure=dt_util.parse_datetime(data.get("pending_departure") or ""),
            pending_arrival=dt_util.parse_datetime(data.get("pending_arrival") or ""),
            last_clock_in_day=date.fromisoformat(last_day) if last_day else None,
            snooze_until=dt_util.parse_datetime(data.get("snooze_until") or ""),
            live_started_at=dt_util.parse_datetime(data.get("live_started_at") or ""),
            home_office=HomeOfficeState(
                session_since=dt_util.parse_datetime(data.get("home_office_since") or ""),
                idle_since=dt_util.parse_datetime(data.get("home_office_idle_since") or ""),
            ),
            last_location=data.get("last_location"),
            sent=dict(data.get("sent") or {}),
        )


class CrewmeisterAssistant:
    """Automates stamping for one Crewmeister user (config entry)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CrewmeisterConfigEntry,
        client: CrewmeisterClient,
        status: CrewmeisterStatusCoordinator,
        absences: CrewmeisterAbsenceCoordinator,
        config: AssistantConfig,
        stamp_defaults: StampDefaults,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._status = status
        self._absences = absences
        self.config = config
        self._defaults = stamp_defaults
        self._language = hass.config.language
        self._notifier = Notifier(hass, entry.entry_id, config.notify_targets)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.state = AssistantState()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._arrival_timer: CALLBACK_TYPE | None = None
        self._departure_timer: CALLBACK_TYPE | None = None
        self._at_work = False
        self._presence_ready = False
        self._live_updated_at: datetime | None = None
        self._last_status: tuple[WorkStatus, str] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._location_since: datetime | None = None
        # Serializes reading the status and stamping; triggers run as independent tasks
        self._stamp_lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        """Restore state and subscribe to the configured triggers."""

        self.state = AssistantState.from_dict(await self._store.async_load())
        cfg = self.config
        hass = self.hass

        if cfg.presence_configured or cfg.home_office_configured:
            # Device trackers may still be loading; judge presence once HA has started
            self._unsubs.append(async_at_started(hass, self._async_presence_start))
        if cfg.presence_configured:
            entities = [*cfg.work_zones, *cfg.presence_entities]
            if cfg.person:
                entities.append(cfg.person)
            if cfg.wifi_sensor:
                entities.append(cfg.wifi_sensor)
            self._unsubs.append(
                async_track_state_change_event(hass, entities, self._async_presence_changed)
            )

        if cfg.home_office_configured:
            entities = [cfg.person, *cfg.home_office_presence_sensors]
            if cfg.home_office_power_sensor:
                entities.append(cfg.home_office_power_sensor)
            self._unsubs.append(
                async_track_state_change_event(hass, entities, self._async_home_office_changed)
            )

        if cfg.nfc_tags:
            self._unsubs.append(hass.bus.async_listen(EVENT_TAG_SCANNED, self._async_tag_scanned))
        if self._notifier.enabled:
            self._unsubs.append(
                hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, self._async_notification_action)
            )

        self._unsubs.append(async_track_time_interval(hass, self._async_tick, TICK_INTERVAL))
        self._unsubs.append(
            async_track_time_change(hass, self._async_midnight, hour=0, minute=0, second=5)
        )
        for at, handler in (
            (cfg.reminder_time, self._async_reminder_time),
            (cfg.forgotten_check_time, self._async_forgotten_check),
            (cfg.lunch_break_time, self._async_lunch_break),
        ):
            if at is not None:
                self._unsubs.append(
                    async_track_time_change(
                        hass, handler, hour=at.hour, minute=at.minute, second=at.second
                    )
                )

        self._unsubs.append(self._status.async_add_listener(self._async_status_updated))
        self._async_status_updated()

    async def async_stop(self) -> None:
        """Unsubscribe from all triggers and write the state immediately."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_arrival()
        self._cancel_departure()
        # A reload must see the latest state; also cancels the delayed save, which
        # could otherwise recreate the file after the entry was removed
        await self._store.async_save(self.state.as_dict())

    # ------------------------------------------------------------- enable switch

    @property
    def enabled(self) -> bool:
        """Return whether presence based stamping is active."""

        return self.state.enabled

    def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable presence based stamping."""

        self.state.enabled = enabled
        if not enabled:
            self._cancel_arrival()
            self._cancel_departure()
            self.state.pending_arrival = None
            self.state.pending_departure = None
        self._save()
        self._notify_listeners()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` when the enabled state or the work location changes."""

        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------- work location

    @property
    def work_location(self) -> str:
        """Return where the user currently works according to the detection."""

        if self._at_work:
            return LOCATION_OFFICE
        if self.state.home_office.active:
            return LOCATION_HOME_OFFICE
        return LOCATION_NONE

    @property
    def work_location_since(self) -> datetime | None:
        """Return since when ``work_location`` applies (only known since startup)."""

        if self.work_location == LOCATION_HOME_OFFICE:
            return self.state.home_office.session_since
        return self._location_since

    def stamp_location(self) -> str | None:
        """Return the location text to send with a stamp, if enabled."""

        cfg = self.config
        if not cfg.stamp_location:
            return None
        location = self.work_location
        if location == LOCATION_NONE:
            # E.g. clocking out after leaving: use where the user worked last
            location = self.state.last_location or LOCATION_NONE
        if location == LOCATION_OFFICE:
            return cfg.location_office or self._t("location_office")
        if location == LOCATION_HOME_OFFICE:
            return cfg.location_home_office or self._t("location_home_office")
        return None

    def stamp_note_and_location(
        self, note: str | None, location: str | None = None
    ) -> tuple[str | None, str | None]:
        """Return note and location of a stamp; ``location`` defaults to the detected one."""

        return note_with_location(
            note,
            location if location is not None else self.stamp_location(),
            as_note=self.config.location_as_note,
        )

    def _location_changed(self, previous: str) -> None:
        location = self.work_location
        if location == previous:
            return
        self._location_since = dt_util.utcnow()
        if location != LOCATION_NONE:
            self.state.last_location = location
        self._save()
        self._notify_listeners()

    # ------------------------------------------------------------------ presence

    def _compute_at_work(self) -> bool:
        cfg = self.config
        states = self.hass.states
        if cfg.person:
            for zone in cfg.work_zones:
                state = states.get(zone)
                if state and cfg.person in state.attributes.get("persons", []):
                    return True
        wifi = states.get(cfg.wifi_sensor) if cfg.wifi_sensor else None
        if wifi and wifi.state in cfg.wifi_ssids:
            return True
        for entity_id in cfg.presence_entities:
            state = states.get(entity_id)
            if state and state.state in (STATE_ON, STATE_HOME):
                return True
        return False

    @callback
    def _async_presence_start(self, _hass: HomeAssistant) -> None:
        previous = self.work_location
        if self.config.presence_configured:
            self._at_work = self._compute_at_work()
        self._presence_ready = True
        self._restore_pending_arrival()
        self._restore_pending_departure()
        self._location_since = dt_util.utcnow()
        self._location_changed(previous)
        if self.config.home_office_configured:
            self._entry.async_create_task(self.hass, self._async_home_office_update())

    @callback
    def _async_presence_changed(self, _event: Event[EventStateChangedData]) -> None:
        if not self._presence_ready:
            return
        at_work = self._compute_at_work()
        if at_work == self._at_work:
            return
        previous = self.work_location
        self._at_work = at_work
        self._location_changed(previous)
        now = dt_util.utcnow()
        if at_work:
            self._on_arrival(now)
        else:
            self._on_departure(now)

    def _on_arrival(self, now: datetime) -> None:
        cfg = self.config
        self._clear_pending_arrival()
        if (left := self.state.pending_departure) is not None:
            # Back before the departure was handled
            self._cancel_departure()
            self.state.pending_departure = None
            self._save()
            away = now - left
            if (
                self.enabled
                and cfg.clock_out_mode == StampMode.AUTO
                and cfg.departure_delay <= away <= cfg.short_leave_break
            ):
                self._entry.async_create_task(self.hass, self._async_short_leave(left, now))
            return
        if not self.enabled or cfg.clock_in_mode == StampMode.OFF:
            return
        self.state.pending_arrival = now
        self._save()
        self._schedule_arrival(now)

    def _schedule_arrival(self, arrived_at: datetime) -> None:
        self._cancel_arrival()
        self._arrival_timer = async_track_point_in_utc_time(
            self.hass,
            HassJob(partial(self._async_arrival_confirmed, arrived_at), cancel_on_shutdown=True),
            max(arrived_at + self.config.arrival_delay, dt_util.utcnow()),
        )

    def _restore_pending_arrival(self) -> None:
        arrived_at = self.state.pending_arrival
        if arrived_at is None:
            return
        if not self._at_work or not self.enabled or self.config.clock_in_mode == StampMode.OFF:
            self._clear_pending_arrival()
            return
        self._schedule_arrival(arrived_at)

    def _clear_pending_arrival(self) -> None:
        self._cancel_arrival()
        if self.state.pending_arrival is not None:
            self.state.pending_arrival = None
            self._save()

    async def _async_arrival_confirmed(self, arrived_at: datetime, _now: datetime) -> None:
        self._arrival_timer = None
        self._clear_pending_arrival()
        if self._at_work:
            await self._async_handle_arrival(arrived_at)

    async def _async_handle_arrival(self, arrived_at: datetime) -> None:
        cfg = self.config
        local = dt_util.as_local(arrived_at)
        if not _in_window(local.time(), cfg.window_start, cfg.window_end):
            return
        if not self._is_workday(local.date()):
            return
        await self._async_handle_work_start(
            arrived_at, cfg.clock_in_mode, "arrived_title", "arrived_message"
        )

    async def _async_handle_work_start(
        self, started_at: datetime, mode: StampMode, title_key: str, message_key: str
    ) -> None:
        """Clock in (or end a break) after work started at ``started_at``."""

        cfg = self.config
        if not self.enabled or mode == StampMode.OFF:
            return
        summary = await self._async_fresh_summary()
        if summary is None:
            return
        at = started_at if cfg.backdate else None
        time_str = _hm(at or dt_util.utcnow())

        if summary.status == WorkStatus.CLOCKED_OUT:
            day = dt_util.as_local(started_at).date()
            if mode == StampMode.AUTO and cfg.once_per_day and self.state.last_clock_in_day == day:
                # Already clocked in automatically today: ask instead of stamping again
                mode = StampMode.ASK
            if mode == StampMode.AUTO:
                await self._async_stamp(StampType.START_WORK, at, automatic=True)
            else:
                await self._notifier.async_send(
                    Kind.PRESENCE,
                    self._t(title_key),
                    self._t(message_key, time=time_str),
                    [
                        Button(
                            self._t("btn_clock_in_at", time=time_str), Action.CLOCK_IN, _epoch(at)
                        ),
                        Button(self._t("btn_ignore"), Action.IGNORE),
                    ],
                )
        elif summary.status == WorkStatus.ON_BREAK:
            if mode == StampMode.AUTO:
                await self._async_stamp(StampType.START_WORK, at, automatic=True)
            else:
                await self._notifier.async_send(
                    Kind.PRESENCE,
                    self._t("returned_title"),
                    self._t("returned_message", time=time_str),
                    [
                        Button(self._t("btn_resume"), Action.RESUME, _epoch(at)),
                        Button(self._t("btn_ignore"), Action.IGNORE),
                    ],
                )

    def _on_departure(self, now: datetime) -> None:
        self._clear_pending_arrival()
        self.state.left_at = now
        if self.enabled:
            self.state.pending_departure = now
            self._schedule_departure(now)
        self._save()

    def _departure_delay(self) -> timedelta:
        cfg = self.config
        if cfg.clock_out_mode == StampMode.AUTO and cfg.short_leave_break > cfg.departure_delay:
            return cfg.short_leave_break
        return cfg.departure_delay

    def _schedule_departure(self, left_at: datetime) -> None:
        self._cancel_departure()
        when = max(left_at + self._departure_delay(), dt_util.utcnow())
        self._departure_timer = async_track_point_in_utc_time(
            self.hass,
            HassJob(self._async_departure_confirmed, cancel_on_shutdown=True),
            when,
        )

    def _restore_pending_departure(self) -> None:
        left_at = self.state.pending_departure
        if left_at is None:
            return
        if self._at_work or not self.enabled:
            self.state.pending_departure = None
            self._save()
            return
        self._schedule_departure(left_at)

    async def _async_departure_confirmed(self, _now: datetime) -> None:
        self._departure_timer = None
        left_at = self.state.pending_departure
        self.state.pending_departure = None
        self._save()
        if left_at is not None and not self._at_work:
            await self._async_handle_departure(left_at)

    async def _async_handle_departure(self, left_at: datetime) -> None:
        await self._async_handle_work_end(
            left_at,
            self.config.clock_out_mode,
            "left_title",
            "left_message",
            remind=self.config.remind_on_leave,
        )

    async def _async_handle_work_end(
        self,
        ended_at: datetime,
        mode: StampMode,
        title_key: str,
        message_key: str,
        *,
        remind: bool = False,
    ) -> None:
        """Clock out (or ask) after work ended at ``ended_at``."""

        cfg = self.config
        if not self.enabled:
            return
        if mode == StampMode.OFF and not remind:
            return
        summary = await self._async_fresh_summary()
        if summary is None or summary.status == WorkStatus.CLOCKED_OUT:
            return
        at = ended_at if cfg.backdate else None
        time_str = _hm(ended_at)

        if mode == StampMode.AUTO:
            await self._async_stamp(StampType.CLOCK_OUT, at, automatic=True)
        elif mode == StampMode.ASK:
            buttons = [
                Button(
                    self._t("btn_clock_out_at", time=_hm(at or dt_util.utcnow())),
                    Action.CLOCK_OUT,
                    _epoch(at),
                )
            ]
            if summary.status == WorkStatus.CLOCKED_IN:
                buttons.append(
                    Button(self._t("btn_break_at", time=time_str), Action.START_BREAK, _epoch(at))
                )
            buttons.append(Button(self._t("btn_ignore"), Action.IGNORE))
            await self._notifier.async_send(
                Kind.PRESENCE,
                self._t(title_key),
                self._t(message_key, time=time_str),
                buttons,
                time_sensitive=True,
            )
        else:
            await self._notifier.async_send(
                Kind.REMINDER,
                self._t(title_key),
                self._t(message_key, time=time_str),
                [
                    Button(
                        self._t("btn_clock_out_at", time=time_str),
                        Action.CLOCK_OUT,
                        _epoch(ended_at),
                    ),
                    self._snooze_button(),
                ],
                time_sensitive=True,
            )

    async def _async_short_leave(self, left_at: datetime, back_at: datetime) -> None:
        """Turn a short absence from work into a break."""

        # Both stamps under one lock, so e.g. auto resume cannot stamp in between
        async with self._stamp_lock:
            summary = await self._async_fresh_summary()
            if summary is None or summary.status != WorkStatus.CLOCKED_IN:
                return
            if not await self._async_stamp_locked(
                StampType.START_BREAK, left_at, automatic=True, confirm=False
            ):
                return
            if not await self._async_stamp_locked(
                StampType.START_WORK, back_at, automatic=True, confirm=False
            ):
                return
        await self._async_info(self._t("short_leave_message", start=_hm(left_at), end=_hm(back_at)))

    def _cancel_arrival(self) -> None:
        if self._arrival_timer:
            self._arrival_timer()
            self._arrival_timer = None

    def _cancel_departure(self) -> None:
        if self._departure_timer:
            self._departure_timer()
            self._departure_timer = None

    # ---------------------------------------------------------------- home office

    def _home_office_activity(self) -> bool:
        """Return whether the person is at home and active at the desk."""

        cfg = self.config
        states = self.hass.states
        person = states.get(cfg.person) if cfg.person else None
        if person is None or person.state != STATE_HOME:
            return False
        power = states.get(cfg.home_office_power_sensor) if cfg.home_office_power_sensor else None
        if power is not None:
            try:
                if float(power.state) >= cfg.home_office_power_threshold:
                    return True
            except ValueError:
                pass
        return any(
            (state := states.get(entity_id)) is not None and state.state == STATE_ON
            for entity_id in cfg.home_office_presence_sensors
        )

    @callback
    def _async_home_office_changed(self, _event: Event[EventStateChangedData]) -> None:
        if self._presence_ready:
            self._entry.async_create_task(self.hass, self._async_home_office_update())

    async def _async_home_office_update(self) -> None:
        """Feed the current activity into the home office detection."""

        cfg = self.config
        if not cfg.home_office_configured or not self._presence_ready:
            return
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        start, end = cfg.home_office_window_start, cfg.home_office_window_end
        may_start = _in_window(local.time(), start, end) and self._is_workday(local.date())
        earliest = (
            dt_util.as_utc(datetime.combine(local.date(), start, tzinfo=local.tzinfo))
            if start <= end
            else None
        )
        short_break = (
            cfg.home_office_short_break
            if cfg.home_office_clock_out_mode == StampMode.AUTO
            else timedelta(0)
        )
        ho = self.state.home_office
        before = (ho.session_since, ho.idle_since)
        previous = self.work_location
        event = advance(
            ho,
            self._home_office_activity(),
            now,
            activity_delay=cfg.home_office_activity_delay,
            idle_after=cfg.home_office_idle_timeout,
            short_break=short_break,
            may_start=may_start,
            earliest_start=earliest,
        )
        if (ho.session_since, ho.idle_since) != before:
            self._save()
        self._location_changed(previous)
        if event is not None:
            await self._async_home_office_event(event)

    async def _async_home_office_event(self, event: HomeOfficeEvent) -> None:
        cfg = self.config
        if event.type == HomeOfficeEventType.START:
            await self._async_handle_work_start(
                event.at,
                cfg.home_office_clock_in_mode,
                "home_office_title",
                "home_office_message",
            )
        elif event.type == HomeOfficeEventType.END:
            if self._at_work or self.state.last_location == LOCATION_OFFICE:
                # The user moved to the office meanwhile; the running shift is not
                # a home office shift and must not be ended by the idle PC at home
                return
            await self._async_handle_work_end(
                event.at,
                cfg.home_office_clock_out_mode,
                "home_office_idle_title",
                "home_office_idle_message",
            )
        elif self.enabled and event.until is not None:
            await self._async_short_leave(event.at, event.until)

    # ----------------------------------------------------------- other triggers

    def _allowed_users(self) -> set[str]:
        """Return the HA users that may stamp for this Crewmeister account.

        These are the user of the configured person and the owners of the
        configured Companion App devices.
        """

        cfg = self.config
        users: set[str] = set()
        person = self.hass.states.get(cfg.person) if cfg.person else None
        if person and (user_id := person.attributes.get("user_id")):
            users.add(user_id)
        targets = set(cfg.notify_targets)
        for entry in self.hass.config_entries.async_entries("mobile_app"):
            name, user_id = entry.data.get("device_name"), entry.data.get("user_id")
            if name and user_id and f"mobile_app_{slugify(name)}" in targets:
                users.add(user_id)
        return users

    def _event_allowed(self, event: Event) -> bool:
        """Return whether ``event`` comes from a user allowed to stamp.

        Every Companion App device can fire arbitrary events, so events from
        devices of other Home Assistant users must be ignored. Events without
        a user (automations, scripts) are allowed. Without a configured person
        or notification device nobody can be told apart, so all users may stamp.
        """

        user_id = event.context.user_id
        if user_id is None:
            return True
        allowed = self._allowed_users()
        if not allowed or user_id in allowed:
            return True
        _LOGGER.warning(
            "Ignoring %s from user %s: only the configured person and the owners of the "
            "configured notification devices may stamp for this Crewmeister account",
            event.event_type,
            user_id,
        )
        return False

    async def _async_tag_scanned(self, event: Event) -> None:
        if event.data.get("tag_id") not in self.config.nfc_tags:
            return
        if not self._event_allowed(event):
            return
        summary = await self._async_fresh_summary()
        if summary is None:
            await self._async_failure(self._t("error_unavailable"))
            return
        if summary.status == WorkStatus.CLOCKED_IN:
            await self._async_stamp(StampType.CLOCK_OUT)
        else:
            await self._async_stamp(StampType.START_WORK)

    async def _async_notification_action(self, event: Event) -> None:
        decoded = decode_action(event.data.get("action"))
        if decoded is None or decoded.entry_id != self._entry.entry_id:
            return
        if not self._event_allowed(event):
            return
        action, arg = decoded.action, decoded.arg
        at = _parse_epoch(arg) if action not in (Action.ADD_BREAK, Action.SNOOZE) else None
        now = dt_util.utcnow()
        if at is not None and not now - MAX_ACTION_AGE <= at <= now + ACTION_FUTURE_TOLERANCE:
            await self._async_failure(self._t("error_outdated"))
            return
        if action == Action.SNOOZE:
            self.state.snooze_until = dt_util.utcnow() + self.config.snooze
            self._save()
        elif action == Action.ADD_BREAK:
            await self._async_add_break(arg)
        elif action in (Action.CLOCK_IN, Action.RESUME):
            await self._async_stamp(StampType.START_WORK, at)
        elif action == Action.START_BREAK:
            await self._async_stamp(StampType.START_BREAK, at)
        elif action == Action.CLOCK_OUT:
            await self._async_stamp(StampType.CLOCK_OUT, at)

    async def _async_tick(self, _now: datetime) -> None:
        """Check reminders and the break assistant once a minute."""

        if self.config.home_office_configured:
            await self._async_home_office_update()
        data = self._status.data
        if data is None:
            return
        cfg = self.config
        summary = data.today()
        today = dt_util.now().date().isoformat()

        if self.state.snooze_until and dt_util.utcnow() >= self.state.snooze_until:
            self.state.snooze_until = None
            self._save()
            if summary.status != WorkStatus.CLOCKED_OUT:
                await self._async_send_still_clocked_in(summary)

        if summary.status == WorkStatus.CLOCKED_OUT:
            return
        if cfg.notify_live:
            await self._async_update_live(summary)
        if summary.shift_start and dt_util.as_local(summary.shift_start).date().isoformat() < today:
            # Most likely clocking out was forgotten; the forgotten check handles that
            return

        end = self._expected_end(summary)
        if (
            cfg.end_of_day_reminder
            and end is not None
            and dt_util.utcnow() >= end + cfg.end_of_day_grace
            and self._mark("end_of_day", _iso(summary.shift_start) or today)
        ):
            target = self._target_hours(summary)
            await self._notifier.async_send(
                Kind.REMINDER,
                self._t("end_of_day_title"),
                self._t(
                    "end_of_day_message",
                    target=format_duration(target or timedelta(0)),
                    time=_hm(end),
                ),
                [Button(self._t("btn_clock_out"), Action.CLOCK_OUT), self._snooze_button()],
                time_sensitive=True,
            )

        if cfg.max_work and summary.work >= cfg.max_work and self._mark("max_work", today):
            await self._notifier.async_send(
                Kind.REMINDER,
                self._t("max_work_title"),
                self._t("max_work_message", worked=format_duration(summary.work)),
                [Button(self._t("btn_clock_out"), Action.CLOCK_OUT), self._snooze_button()],
                time_sensitive=True,
            )

        since = _iso(summary.status_since) or ""
        if (
            summary.status == WorkStatus.CLOCKED_IN
            and cfg.break_reminder_after
            and summary.work_since_break >= cfg.break_reminder_after
            and self._mark("break_due", since)
        ):
            await self._notifier.async_send(
                Kind.BREAK,
                self._t("break_due_title"),
                self._t("break_due_message", worked=format_duration(summary.work_since_break)),
                [Button(self._t("btn_break"), Action.START_BREAK)],
            )

        if (
            summary.status == WorkStatus.ON_BREAK
            and summary.current_break >= cfg.break_duration
            and (cfg.auto_resume or cfg.break_end_reminder)
            and self._mark("break_over", since)
        ):
            if cfg.auto_resume:
                await self._async_stamp(StampType.START_WORK, automatic=True)
            else:
                await self._notifier.async_send(
                    Kind.BREAK,
                    self._t("break_over_title"),
                    self._t("break_over_message", duration=format_duration(summary.current_break)),
                    [Button(self._t("btn_resume"), Action.RESUME)],
                    time_sensitive=True,
                )

    async def _async_midnight(self, _now: datetime) -> None:
        # Day based sensors and summaries start over
        self._status.async_update_listeners()
        ho = self.state.home_office
        data = self._status.data
        if ho.active and ho.idle_since is None and data and data.status == WorkStatus.CLOCKED_OUT:
            # A PC left running overnight must not keep yesterday's session alive
            previous = self.work_location
            ho.session_since = None
            # Ongoing activity counts from now, i.e. from the start of the new day
            ho.activity_since = dt_util.utcnow() if self._home_office_activity() else None
            self._save()
            self._location_changed(previous)
        # Absences are loaded 120 days ahead; only re-evaluate, no extra API call
        self._absences.async_update_listeners()

    async def _async_reminder_time(self, _now: datetime) -> None:
        summary = await self._async_fresh_summary()
        if summary is not None and summary.status != WorkStatus.CLOCKED_OUT:
            await self._async_send_still_clocked_in(summary)

    async def _async_forgotten_check(self, _now: datetime) -> None:
        """Offer to clock out a shift that started on an earlier day."""

        summary = await self._async_fresh_summary()
        if summary is None or summary.status == WorkStatus.CLOCKED_OUT or not summary.shift_start:
            return
        if dt_util.as_local(summary.shift_start).date() >= dt_util.now().date():
            return

        cfg = self.config
        left_at = self.state.left_at
        if left_at is not None and left_at <= summary.shift_start:
            left_at = None
        target = self._target_hours(summary) or cfg.daily_hours
        offer = left_at or summary.shift_start + target + required_break(
            target, cfg.break_after_6h, cfg.break_after_9h
        )
        latest = summary.latest.timestamp if summary.latest else None
        now = dt_util.utcnow()
        buttons = []
        # Only offer times a tap will accept: after the latest stamp, not in the
        # future and young enough to still be valid for a while
        if (latest is None or offer > latest) and (
            now - MAX_ACTION_AGE + FORGOTTEN_OFFER_MARGIN <= offer <= now
        ):
            buttons.append(
                Button(
                    self._t("btn_clock_out_at", time=_day_hm(offer)),
                    Action.CLOCK_OUT,
                    _epoch(offer),
                )
            )
        buttons.append(Button(self._t("btn_clock_out_now"), Action.CLOCK_OUT))

        start = _day_hm(summary.shift_start)
        message = (
            self._t("forgotten_message_left", start=start, left=_day_hm(left_at))
            if left_at
            else self._t("forgotten_message", start=start)
        )
        await self._notifier.async_send(
            Kind.REMINDER, self._t("forgotten_title"), message, buttons, time_sensitive=True
        )

    async def _async_lunch_break(self, _now: datetime) -> None:
        summary = await self._async_fresh_summary()
        if summary is not None and summary.status == WorkStatus.CLOCKED_IN:
            await self._async_stamp(StampType.START_BREAK, automatic=True)

    # -------------------------------------------------------------- status changes

    @callback
    def _async_status_updated(self) -> None:
        data = self._status.data
        if data is None:
            return
        summary = data.today()
        latest = summary.latest
        key = (summary.status, _iso(latest.timestamp) if latest else "")
        previous = self._last_status
        if key == previous:
            return
        self._last_status = key
        self._entry.async_create_task(
            self.hass, self._async_status_changed(previous[0] if previous else None, summary)
        )

    async def _async_status_changed(self, previous: WorkStatus | None, summary: DaySummary) -> None:
        if self.config.notify_live:
            await self._async_update_live(summary, force=True)
        elif self.config.notify_status:
            await self._async_update_status_notification(summary)
        if (
            previous is not None
            and previous != WorkStatus.CLOCKED_OUT
            and summary.status == WorkStatus.CLOCKED_OUT
            and self.config.break_check
        ):
            await self._async_check_break()

    async def _async_update_status_notification(self, summary: DaySummary) -> None:
        since = summary.status_since
        if summary.status == WorkStatus.CLOCKED_OUT or since is None:
            await self._notifier.async_clear(Kind.STATUS)
            return
        if summary.status == WorkStatus.CLOCKED_IN:
            message = self._t("status_clocked_in", time=_hm(summary.shift_start or since))
            buttons = [
                Button(self._t("btn_break"), Action.START_BREAK),
                Button(self._t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        else:
            message = self._t("status_on_break", time=_hm(since))
            buttons = [
                Button(self._t("btn_resume"), Action.RESUME),
                Button(self._t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        await self._notifier.async_send_status(self._t("status_title"), message, since, buttons)

    async def _async_update_live(self, summary: DaySummary, *, force: bool = False) -> None:
        """Show or update the Live Activity (iOS) / Live Update (Android)."""

        now = dt_util.utcnow()
        state = self.state
        if summary.status == WorkStatus.CLOCKED_OUT or summary.status_since is None:
            if state.live_started_at is not None:
                state.live_started_at = None
                self._save()
                await self._notifier.async_clear(Kind.LIVE)
            self._live_updated_at = None
            return
        if (
            not force
            and self._live_updated_at is not None
            and now - self._live_updated_at < LIVE_UPDATE_INTERVAL
        ):
            return
        if state.live_started_at is not None and now - state.live_started_at >= LIVE_RESTART_AFTER:
            await self._notifier.async_clear(Kind.LIVE)
            state.live_started_at = None
        if state.live_started_at is None:
            state.live_started_at = now
            self._save()
        self._live_updated_at = now

        end = self._expected_end(summary)
        target = self._target_hours(summary)
        if summary.status == WorkStatus.CLOCKED_IN:
            # The timer shows today's work time, breaks excluded
            timer_start = now - summary.work
            message = [
                Segment(
                    self._t("live_work", start=_hm(summary.shift_start or summary.status_since)),
                    LIVE_WORK_COLORS.accent,
                ),
                Segment(LIVE_SEPARATOR),
                Segment(
                    self._t("live_breaks", breaks=format_duration(summary.breaks)),
                    LIVE_BREAK_COLORS.accent,
                ),
            ]
            critical = self._t("live_critical_work")
            buttons = [
                Button(self._t("btn_break"), Action.START_BREAK),
                Button(self._t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        else:
            timer_start = summary.status_since
            message = [
                Segment(
                    self._t("live_break", since=_hm(summary.status_since)),
                    LIVE_BREAK_COLORS.accent,
                ),
                Segment(LIVE_SEPARATOR),
                Segment(
                    self._t("live_worked", worked=format_duration(summary.work)),
                    LIVE_WORK_COLORS.accent,
                ),
            ]
            critical = self._t("live_critical_break")
            buttons = [
                Button(self._t("btn_resume"), Action.RESUME),
                Button(self._t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        if end is not None:
            message += [Segment(LIVE_SEPARATOR), Segment(self._t("live_end", end=_hm(end)))]

        progress = None
        if target is not None:
            target_minutes = int(target.total_seconds() // 60)
            worked_minutes = int(summary.work.total_seconds() // 60)
            progress = (min(worked_minutes, target_minutes), target_minutes)
        await self._notifier.async_send_live(
            self._t("status_title"),
            message,
            critical_text=critical,
            timer_start=timer_start,
            progress=progress,
            on_break=summary.status == WorkStatus.ON_BREAK,
            buttons=buttons,
        )

    async def _async_check_break(self) -> None:
        """Warn if the finished shift had less break than required."""

        data = self._status.data
        if data is None:
            return
        last = data.today()
        if last.shift_start is None or last.latest is None:
            return
        # Look at the whole shift, even if it started yesterday
        shift = summarize(data.stamps, dt_util.utcnow(), last.shift_start)
        cfg = self.config
        required = required_break(shift.work, cfg.break_after_6h, cfg.break_after_9h)
        missing = required - shift.rest_breaks
        if missing <= timedelta(0):
            return
        minutes = int(-(-missing.total_seconds() // 60))  # round up
        buttons = []
        if last.latest.id is not None:
            buttons.append(
                Button(
                    self._t("btn_add_break", minutes=minutes),
                    Action.ADD_BREAK,
                    f"{minutes}-{last.latest.id}",
                )
            )
        await self._notifier.async_send(
            Kind.BREAK,
            self._t("break_missing_title"),
            self._t(
                "break_missing_message",
                worked=format_duration(shift.work),
                required=format_duration(required),
                taken=format_duration(shift.rest_breaks),
            ),
            buttons,
        )

    async def _async_add_break(self, arg: str | None) -> None:
        try:
            minutes_str, stamp_id_str = (arg or "").split("-", 1)
            minutes, stamp_id = int(minutes_str), int(stamp_id_str)
        except ValueError:
            _LOGGER.debug("Invalid break action argument: %s", arg)
            return
        # Only breaks for the user's own recent stamps and of plausible length
        data = self._status.data
        known_ids = {stamp.id for stamp in data.stamps} if data else set()
        if stamp_id not in known_ids or not 0 < minutes <= MAX_ADDED_BREAK.total_seconds() / 60:
            _LOGGER.warning("Rejected break action for stamp %s (%s min)", stamp_id, minutes)
            return
        async with self._stamp_lock:
            # The API adds the break; a second tap (e.g. phone and watch) must not
            # add it twice
            if self.state.sent.get("break_added") == str(stamp_id):
                _LOGGER.debug("Break for stamp %s was already added", stamp_id)
                return
            try:
                await self._client.async_set_break(stamp_id, timedelta(minutes=minutes))
            except CrewmeisterError as err:
                await self._async_failure(self._t("error_api", error=str(err)))
                return
            self._mark("break_added", str(stamp_id))
            await self._status.async_refresh()
        await self._async_info(self._t("break_added", minutes=minutes))

    # ------------------------------------------------------------------- helpers

    async def _async_fresh_summary(self) -> DaySummary | None:
        """Refresh the status and return today's summary, ``None`` if unavailable."""

        await self._status.async_refresh()
        if not self._status.last_update_success or self._status.data is None:
            return None
        return self._status.data.today()

    async def _async_stamp(
        self,
        stamp_type: StampType,
        at: datetime | None = None,
        *,
        automatic: bool = False,
        confirm: bool = True,
    ) -> bool:
        """Create a stamp after validating it against the current status.

        Invalid transitions of ``automatic`` stamps are dropped silently, since the
        user most likely stamped elsewhere in the meantime. Concurrent triggers are
        serialized, so the second one sees the stamp of the first.
        """

        async with self._stamp_lock:
            return await self._async_stamp_locked(
                stamp_type, at, automatic=automatic, confirm=confirm
            )

    async def _async_stamp_locked(
        self,
        stamp_type: StampType,
        at: datetime | None = None,
        *,
        automatic: bool = False,
        confirm: bool = True,
    ) -> bool:
        """Create a stamp; the caller must hold ``_stamp_lock``."""

        summary = await self._async_fresh_summary()
        if summary is None:
            await self._async_failure(self._t("error_unavailable"))
            return False
        try:
            validate_transition(stamp_type, summary.status)
        except InvalidTransitionError as err:
            if not automatic:
                await self._async_failure(self._t(f"error_{err.reason}"))
            return False
        latest = summary.latest.timestamp if summary.latest else None
        if at is not None and latest is not None and at <= latest:
            if not automatic:
                await self._async_failure(self._t("error_outdated"))
            return False

        note, location = self.stamp_note_and_location(self._defaults.note)
        try:
            await self._client.async_create_stamp(
                stamp_type,
                timestamp=at,
                note=note,
                location=location,
                time_account_id=self._defaults.time_account_id,
            )
        except CrewmeisterError as err:
            await self._async_failure(self._t("error_api", error=str(err)))
            return False

        if stamp_type == StampType.START_WORK:
            self.state.last_clock_in_day = dt_util.as_local(at or dt_util.utcnow()).date()
            self._save()
        await self._status.async_refresh()

        if confirm and self.config.notify_confirmations and self._status.data:
            today = self._status.data.today()
            await self._async_info(
                self._t(
                    f"stamped_{stamp_type.value}",
                    time=_hm(at or dt_util.utcnow()),
                    worked=format_duration(today.work),
                    breaks=format_duration(today.breaks),
                )
            )
        return True

    async def _async_send_still_clocked_in(self, summary: DaySummary) -> None:
        await self._notifier.async_send(
            Kind.REMINDER,
            self._t("still_clocked_in_title"),
            self._t("still_clocked_in_message", worked=format_duration(summary.work)),
            [Button(self._t("btn_clock_out"), Action.CLOCK_OUT), self._snooze_button()],
            time_sensitive=True,
        )

    async def _async_info(self, message: str) -> None:
        await self._notifier.async_send(Kind.INFO, self._t("status_title"), message)

    async def _async_failure(self, message: str) -> None:
        _LOGGER.warning("Crewmeister assistant: %s", message)
        await self._notifier.async_send(Kind.INFO, self._t("stamp_failed_title"), message)

    def _snooze_button(self) -> Button:
        minutes = int(self.config.snooze.total_seconds() // 60)
        return Button(self._t("btn_snooze", minutes=minutes), Action.SNOOZE)

    def _target_hours(self, summary: DaySummary) -> timedelta | None:
        start = summary.shift_start or summary.now
        return self.config.target_hours(dt_util.as_local(start).date())

    def _expected_end(self, summary: DaySummary) -> datetime | None:
        """Return when today's target working time is reached, including breaks."""

        target = self._target_hours(summary)
        if target is None:
            return None
        cfg = self.config
        return expected_end(summary, target, cfg.break_after_6h, cfg.break_after_9h)

    def _is_workday(self, day: date) -> bool:
        absences = [entry.absence for entry in self._absences.current()]
        return no_work_reason_for(self.hass, self.config, absences, day) is None

    def _mark(self, key: str, marker: str) -> bool:
        """Remember that ``key`` was handled for ``marker``; False if it already was."""

        if self.state.sent.get(key) == marker:
            return False
        self.state.sent[key] = marker
        self._save()
        return True

    def _save(self) -> None:
        self._store.async_delay_save(self.state.as_dict, 1)

    def _t(self, key: str, **placeholders: Any) -> str:
        return text(self._language, key, **placeholders)


async def async_remove_assistant_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored state of the assistant of ``entry_id``."""

    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}").async_remove()


def no_work_reason_for(
    hass: HomeAssistant, config: AssistantConfig, absences: list[Absence], day: date
) -> NoWorkReason | None:
    """Return why ``day`` is no working day for the user, ``None`` if it is one."""

    sensor_on: bool | None = None
    state = hass.states.get(config.workday_entity) if config.workday_entity else None
    if state and state.state in (STATE_ON, STATE_OFF):
        sensor_on = state.state == STATE_ON
    return no_work_reason(day, config.workdays, sensor_on, absences)


def _in_window(now: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _epoch(value: datetime | None) -> str | None:
    return str(int(value.timestamp())) if value else None


def _parse_epoch(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dt_util.utc_from_timestamp(int(value))
    except (ValueError, OverflowError, OSError):
        return None


def _hm(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%H:%M")


def _day_hm(value: datetime | None) -> str:
    if value is None:
        return ""
    local = dt_util.as_local(value)
    if local.date() == dt_util.now().date():
        return local.strftime("%H:%M")
    return local.strftime("%d.%m. %H:%M")
