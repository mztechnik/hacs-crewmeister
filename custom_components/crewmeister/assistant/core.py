"""The assistant of one Crewmeister account: shared services and stamping.

The work is split into components that all use this core:

- ``AutoStamper``: presence detection and the stamping rules
- ``AbsenceTracker``: vacation from Crewmeister, a calendar or a sensor
- ``Reminders``: break assistant and end of day reminders
- ``LiveDisplay``: Live Activity / Live Update

Automatic stamps that fail temporarily are kept in a queue and retried with
their original time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from ..api import (
    CrewmeisterClient,
    CrewmeisterConnectionError,
    CrewmeisterError,
    InvalidTransitionError,
    StampType,
    WorkStatus,
    validate_transition,
)
from ..const import DOMAIN
from ..helpers import StampDefaults, note_with_location
from ..logic.config import AssistantConfig
from ..logic.texts import format_duration, text
from ..logic.worktime import DaySummary, expected_end
from ..notifications import Action, Button, Kind, Notifier, decode_action
from .absence import AbsenceTracker
from .autostamp import AutoStamper
from .live import LiveDisplay
from .reminders import Reminders
from .state import STORAGE_VERSION, AssistantState, PendingStamp
from .util import (
    LOCATION_HOME_OFFICE,
    LOCATION_NONE,
    LOCATION_OFFICE,
    StampResult,
    day_hm,
    hm,
    parse_action_arg,
    status_key,
)

if TYPE_CHECKING:
    from ..coordinator import (
        CrewmeisterAbsenceCoordinator,
        CrewmeisterConfigEntry,
        CrewmeisterStatusCoordinator,
    )

_LOGGER = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(minutes=1)
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
# Backdated times offered in notifications must lie in this range around now
MAX_ACTION_AGE = timedelta(days=3)
ACTION_FUTURE_TOLERANCE = timedelta(minutes=2)
# Retry delays of queued stamps; the last one repeats until MAX_QUEUE_AGE
RETRY_DELAYS = [timedelta(minutes=m) for m in (1, 2, 5, 10, 30, 60)]
MAX_QUEUE_AGE = timedelta(hours=24)
# Tell the user after this many failed attempts
QUEUE_NOTIFY_AFTER = 3


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
        self.entry = entry
        self.client = client
        self.status = status
        self.absences = absences
        self.config = config
        self.defaults = stamp_defaults
        self.language = hass.config.language
        self.notifier = Notifier(hass, entry.entry_id, config.notify_targets)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.state = AssistantState()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []
        self._last_status: tuple[WorkStatus, str] | None = None
        # Serializes reading the status and stamping; triggers run as independent tasks
        self.stamp_lock = asyncio.Lock()

        self.absence = AbsenceTracker(self)
        self.auto = AutoStamper(self)
        self.reminders = Reminders(self)
        self.live = LiveDisplay(self)

    # ------------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        """Restore state and subscribe to the configured triggers."""

        self.state = AssistantState.from_dict(await self._store.async_load())
        hass = self.hass
        await self.absence.async_start()
        self.auto.async_start()
        self.reminders.async_start()
        self.live.async_start()
        if self.notifier.enabled:
            self._unsubs.append(
                hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, self._async_notification_action)
            )
        self._unsubs.append(async_track_time_interval(hass, self._async_tick, TICK_INTERVAL))
        self._unsubs.append(
            async_track_time_change(hass, self._async_midnight, hour=0, minute=0, second=5)
        )
        self._unsubs.append(self.status.async_add_listener(self._async_status_updated))
        self._async_status_updated()

    async def async_stop(self) -> None:
        """Unsubscribe from all triggers and write the state immediately."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for component in (self.auto, self.reminders, self.live, self.absence):
            component.async_stop()
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
        self.save()
        self.notify_listeners()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` when the enabled state, presence or a decision changes."""

        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def notify_listeners(self) -> None:
        """Inform the entities about a change."""

        for listener in list(self._listeners):
            listener()

    async def async_show_live(self) -> None:
        """Show the live display again, e.g. after it was swiped away."""

        await self.live.async_show()

    # ------------------------------------------------------------- work location

    @property
    def work_location(self) -> str:
        """Return where the user currently works according to the detection."""

        presence = self.state.presence
        if presence.present and presence.location is not None:
            return presence.location.value
        return LOCATION_NONE

    @property
    def work_location_since(self) -> datetime | None:
        """Return since when ``work_location`` applies."""

        presence = self.state.presence
        return presence.arrived_at if presence.present else presence.left_at

    def stamp_location(self, location: str | None = None) -> str | None:
        """Return the location text to send with a stamp, if enabled."""

        cfg = self.config
        if not cfg.stamp_location:
            return None
        location = location or self.work_location
        if location == LOCATION_NONE:
            # E.g. clocking out after leaving: use where the user worked last
            location = self.state.last_location or LOCATION_NONE
        if location == LOCATION_OFFICE:
            return cfg.location_office or self.t("location_office")
        if location == LOCATION_HOME_OFFICE:
            return cfg.location_home_office or self.t("location_home_office")
        return None

    def stamp_note_and_location(
        self, note: str | None, location: str | None = None
    ) -> tuple[str | None, str | None]:
        """Return note and location text of a stamp at ``location`` (default: detected)."""

        return note_with_location(
            note, self.stamp_location(location), as_note=self.config.location_as_note
        )

    # ------------------------------------------------------------------ stamping

    async def async_fresh_summary(self) -> DaySummary | None:
        """Refresh the status and return today's summary, ``None`` if unavailable."""

        await self.status.async_refresh()
        if not self.status.last_update_success or self.status.data is None:
            return None
        return self.status.data.today()

    async def async_stamp(
        self,
        stamp_type: StampType,
        at: datetime | None = None,
        *,
        automatic: bool = False,
        confirm: bool = True,
        location: str | None = None,
    ) -> StampResult:
        """Create a stamp after validating it against the current status.

        Invalid transitions of ``automatic`` stamps are dropped silently, since the
        user most likely stamped elsewhere in the meantime. If Crewmeister is not
        reachable, an automatic stamp is queued and retried with its time.
        """

        if automatic and at is None:
            at = dt_util.utcnow()
        async with self.stamp_lock:
            result = await self.async_stamp_locked(
                stamp_type, at, automatic=automatic, confirm=confirm, location=location
            )
        if result == StampResult.UNAVAILABLE and automatic:
            assert at is not None
            self._enqueue(stamp_type, at, location)
        return result

    async def async_stamp_locked(
        self,
        stamp_type: StampType,
        at: datetime | None = None,
        *,
        automatic: bool = False,
        confirm: bool = True,
        location: str | None = None,
    ) -> StampResult:
        """Create a stamp; the caller must hold ``stamp_lock``. Never queues."""

        summary = await self.async_fresh_summary()
        if summary is None:
            if not automatic:
                await self.async_failure(self.t("error_unavailable"))
            return StampResult.UNAVAILABLE
        try:
            validate_transition(stamp_type, summary.status)
        except InvalidTransitionError as err:
            if not automatic:
                await self.async_failure(self.t(f"error_{err.reason}"))
            return StampResult.SKIPPED
        latest = summary.latest.timestamp if summary.latest else None
        if at is not None and latest is not None and at <= latest:
            if not automatic:
                await self.async_failure(self.t("error_outdated"))
            return StampResult.SKIPPED

        note, location_text = self.stamp_note_and_location(self.defaults.note, location)
        try:
            await self.client.async_create_stamp(
                stamp_type,
                timestamp=at,
                note=note,
                location=location_text,
                time_account_id=self.defaults.time_account_id,
            )
        except CrewmeisterConnectionError as err:
            _LOGGER.warning("Crewmeister not reachable while stamping: %s", err)
            if not automatic:
                await self.async_failure(self.t("error_unavailable"))
            return StampResult.UNAVAILABLE
        except CrewmeisterError as err:
            await self.async_failure(self.t("error_api", error=str(err)))
            return StampResult.FAILED

        await self.status.async_refresh()
        if confirm and self.config.notify_confirmations and self.status.data:
            today = self.status.data.today()
            await self.async_info(
                self.t(
                    f"stamped_{stamp_type.value}",
                    time=hm(at or dt_util.utcnow()),
                    worked=format_duration(today.work),
                    breaks=format_duration(today.breaks),
                )
            )
        return StampResult.DONE

    # --------------------------------------------------------------------- queue

    def _enqueue(self, stamp_type: StampType, at: datetime, location: str | None) -> None:
        now = dt_util.utcnow()
        self.state.queue.append(
            PendingStamp(stamp_type, at, now, location, attempts=1, next_try=now + RETRY_DELAYS[0])
        )
        self.save()
        self.notify_listeners()

    async def async_process_queue(self) -> None:
        """Retry queued stamps that are due, oldest first."""

        now = dt_util.utcnow()
        while self.state.queue:
            item = self.state.queue[0]
            if item.next_try is not None and item.next_try > now:
                return
            if now - item.created > MAX_QUEUE_AGE:
                self.state.queue.pop(0)
                self.save()
                await self.async_failure(
                    self.t(
                        "queue_failed_message",
                        stamp=self.stamp_name(item.stamp_type),
                        time=day_hm(item.at),
                    )
                )
                continue
            async with self.stamp_lock:
                result = await self.async_stamp_locked(
                    item.stamp_type, item.at, automatic=True, location=item.location
                )
            if result == StampResult.UNAVAILABLE:
                item.attempts += 1
                delay = RETRY_DELAYS[min(item.attempts - 1, len(RETRY_DELAYS) - 1)]
                item.next_try = now + delay
                self.save()
                if item.attempts == QUEUE_NOTIFY_AFTER:
                    await self.notifier.async_send(
                        Kind.INFO,
                        self.t("queued_title"),
                        self.t(
                            "queued_message",
                            stamp=self.stamp_name(item.stamp_type),
                            time=day_hm(item.at),
                        ),
                    )
                return
            self.state.queue.pop(0)
            self.save()
            self.notify_listeners()

    # --------------------------------------------------------- notification taps

    def allowed_users(self) -> set[str]:
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

    def event_allowed(self, event: Event) -> bool:
        """Return whether ``event`` comes from a user allowed to stamp.

        Every Companion App device can fire arbitrary events, so events from
        devices of other Home Assistant users must be ignored. Events without
        a user (automations, scripts) are allowed.
        """

        user_id = event.context.user_id
        if user_id is None:
            return True
        allowed = self.allowed_users()
        if not allowed or user_id in allowed:
            return True
        _LOGGER.warning(
            "Ignoring %s from user %s: only the configured person and the owners of the "
            "configured notification devices may stamp for this Crewmeister account",
            event.event_type,
            user_id,
        )
        return False

    async def _async_notification_action(self, event: Event) -> None:
        decoded = decode_action(event.data.get("action"))
        if decoded is None or decoded.entry_id != self.entry.entry_id:
            return
        if not self.event_allowed(event):
            return
        action, arg = decoded.action, decoded.arg
        now = dt_util.utcnow()
        if action == Action.SNOOZE:
            self.state.snooze_until = now + self.config.snooze
            self.save()
            return
        if action in (Action.ADD_BREAK, Action.NO_BREAK):
            await self.reminders.async_break_answer(action, arg)
            return
        if action == Action.IGNORE:
            return
        at, expires = parse_action_arg(arg)
        if expires is not None and now >= expires:
            await self.async_failure(self.t("error_expired"))
            return
        if at is not None and not now - MAX_ACTION_AGE <= at <= now + ACTION_FUTURE_TOLERANCE:
            await self.async_failure(self.t("error_outdated"))
            return
        stamp_type = {
            Action.CLOCK_IN: StampType.START_WORK,
            Action.RESUME: StampType.START_WORK,
            Action.START_BREAK: StampType.START_BREAK,
            Action.CLOCK_OUT: StampType.CLOCK_OUT,
        }[action]
        await self.async_stamp(stamp_type, at)

    # ------------------------------------------------------------------- timers

    async def _async_tick(self, _now: datetime) -> None:
        """Run the periodic checks of all components once a minute."""

        await self.async_process_queue()
        await self.auto.async_tick()
        await self.absence.async_tick()
        await self.reminders.async_tick()
        await self.live.async_tick()

    async def _async_midnight(self, _now: datetime) -> None:
        # Day based sensors and summaries start over
        self.status.async_update_listeners()
        await self.absence.async_midnight()
        await self.auto.async_midnight()
        self.absences.async_update_listeners()

    @callback
    def _async_status_updated(self) -> None:
        data = self.status.data
        if data is None:
            return
        summary = data.today()
        key = status_key(summary)
        previous = self._last_status
        if key == previous:
            return
        self._last_status = key
        self.entry.async_create_task(
            self.hass, self._async_status_changed(previous[0] if previous else None, summary)
        )

    async def _async_status_changed(self, previous: WorkStatus | None, summary: DaySummary) -> None:
        self.auto.status_changed(previous, summary)
        await self.live.async_status_changed(summary)
        if (
            previous is not None
            and previous != WorkStatus.CLOCKED_OUT
            and summary.status == WorkStatus.CLOCKED_OUT
        ):
            await self.reminders.async_clocked_out()

    # ------------------------------------------------------------------- helpers

    def target_hours(self, summary: DaySummary) -> timedelta | None:
        """Return the target working time of the day the shift started."""

        start = summary.shift_start or summary.now
        return self.config.target_hours(dt_util.as_local(start).date())

    def expected_end(self, summary: DaySummary) -> datetime | None:
        """Return when today's target working time is reached, including breaks."""

        target = self.target_hours(summary)
        if target is None:
            return None
        cfg = self.config
        return expected_end(summary, target, cfg.break_after_6h, cfg.break_after_9h)

    def no_work_reason(self, day: date) -> str | None:
        """Return why ``day`` is no working day, ``None`` if it is one."""

        return self.absence.no_work_reason(day)

    async def async_info(self, message: str) -> None:
        """Send an informational notification."""

        await self.notifier.async_send(Kind.INFO, self.t("status_title"), message)

    async def async_failure(self, message: str) -> None:
        """Log and send a failure notification."""

        _LOGGER.warning("Crewmeister assistant: %s", message)
        await self.notifier.async_send(Kind.INFO, self.t("stamp_failed_title"), message)

    def snooze_button(self) -> Button:
        """Return the snooze button."""

        minutes = int(self.config.snooze.total_seconds() // 60)
        return Button(self.t("btn_snooze", minutes=minutes), Action.SNOOZE)

    def stamp_name(self, stamp_type: StampType) -> str:
        """Return the translated name of a stamp type."""

        return self.t(f"stamp_{stamp_type.value}")

    def mark(self, key: str, marker: str) -> bool:
        """Remember that ``key`` was handled for ``marker``; False if it already was."""

        if self.state.sent.get(key) == marker:
            return False
        self.state.sent[key] = marker
        self.save()
        return True

    def save(self) -> None:
        """Save the state soon."""

        self._store.async_delay_save(self.state.as_dict, 1)

    def t(self, key: str, **placeholders: Any) -> str:
        """Return a translated notification text."""

        return text(self.language, key, **placeholders)


async def async_remove_assistant_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored state of the assistant of ``entry_id``."""

    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}").async_remove()
