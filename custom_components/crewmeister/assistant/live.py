"""Live Activity (iOS) / Live Update (Android) with the running work time."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, Event
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from ..api import WorkStatus
from ..const import DOMAIN
from ..logic.texts import format_duration
from ..logic.worktime import DaySummary
from ..notifications import LIVE_BREAK_COLORS, LIVE_WORK_COLORS, Action, Button, Kind, Segment, tag
from .util import hm, status_token

if TYPE_CHECKING:
    from .core import CrewmeisterAssistant

LIVE_UPDATE_INTERVAL = timedelta(minutes=15)
# iOS ends Live Activities after at most 8 hours; restart before that
LIVE_RESTART_AFTER = timedelta(hours=7, minutes=30)
LIVE_SEPARATOR = " · "
# Fired by the Android Companion App when the user swipes a notification away
EVENT_NOTIFICATION_CLEARED = "mobile_app_notification_cleared"


class LiveDisplay:
    """Keep the live display in sync with the work status."""

    def __init__(self, assistant: CrewmeisterAssistant) -> None:
        self._a = assistant
        self._unsubs: list[CALLBACK_TYPE] = []
        self._updated_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        """Return whether the live display is configured."""

        return self._a.config.notify_live and self._a.notifier.enabled

    def async_start(self) -> None:
        """Listen for the live display being swiped away."""

        if self.enabled:
            self._unsubs.append(
                self._a.hass.bus.async_listen(EVENT_NOTIFICATION_CLEARED, self._async_cleared)
            )

    def async_stop(self) -> None:
        """Stop listening."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_tick(self) -> None:
        """Refresh the live display now and then."""

        data = self._a.status.data
        if self.enabled and data is not None:
            await self._async_update(data.today())

    async def async_status_changed(self, summary: DaySummary) -> None:
        """Update the live display and the button notification right away."""

        if not self.enabled:
            return
        await self._async_update(summary, force=True)
        # The live display has no buttons on iOS; a silent notification carries them
        await self._async_update_status_notification(summary)

    async def async_show(self) -> None:
        """Show the live display again, e.g. after it was swiped away."""

        a = self._a
        if not self.enabled:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="live_disabled")
        summary = await a.async_fresh_summary()
        if summary is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="status_unavailable"
            )
        if summary.status == WorkStatus.CLOCKED_OUT:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="live_clocked_out"
            )
        if a.state.live_dismissed is not None:
            a.state.live_dismissed = None
            a.save()
        await self._async_update(summary, force=True)

    async def _async_cleared(self, event: Event) -> None:
        """Remember that the user swiped the live display away (Android only)."""

        a = self._a
        if event.data.get("tag") != tag(a.entry.entry_id, Kind.LIVE):
            return
        if not a.event_allowed(event):
            return
        data = a.status.data
        if data is None or a.state.live_started_at is None:
            return
        summary = data.today()
        if summary.status == WorkStatus.CLOCKED_OUT:
            return
        a.state.live_dismissed = status_token(summary)
        a.save()

    async def _async_update_status_notification(self, summary: DaySummary) -> None:
        a = self._a
        since = summary.status_since
        if summary.status == WorkStatus.CLOCKED_OUT or since is None:
            await a.notifier.async_clear(Kind.STATUS)
            return
        if summary.status == WorkStatus.CLOCKED_IN:
            message = a.t("status_clocked_in", time=hm(summary.shift_start or since))
            buttons = [
                Button(a.t("btn_break"), Action.START_BREAK),
                Button(a.t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        else:
            message = a.t("status_on_break", time=hm(since))
            buttons = [
                Button(a.t("btn_resume"), Action.RESUME),
                Button(a.t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        await a.notifier.async_send_quiet_status(a.t("status_title"), message, buttons)

    async def _async_update(self, summary: DaySummary, *, force: bool = False) -> None:
        a = self._a
        now = dt_util.utcnow()
        state = a.state
        if summary.status == WorkStatus.CLOCKED_OUT or summary.status_since is None:
            if state.live_started_at is not None or state.live_dismissed is not None:
                state.live_started_at = None
                state.live_dismissed = None
                a.save()
                await a.notifier.async_clear(Kind.LIVE)
            self._updated_at = None
            return
        if state.live_dismissed is not None:
            if state.live_dismissed == status_token(summary):
                # Swiped away; do not bring it back with the periodic refresh
                return
            state.live_dismissed = None
            a.save()
        if (
            not force
            and self._updated_at is not None
            and now - self._updated_at < LIVE_UPDATE_INTERVAL
        ):
            return
        if state.live_started_at is not None and now - state.live_started_at >= LIVE_RESTART_AFTER:
            await a.notifier.async_clear(Kind.LIVE)
            state.live_started_at = None
        if state.live_started_at is None:
            state.live_started_at = now
            a.save()
        self._updated_at = now

        end = a.expected_end(summary)
        target = a.target_hours(summary)
        if summary.status == WorkStatus.CLOCKED_IN:
            # The timer shows today's work time, breaks excluded
            timer_start = now - summary.work
            message = [
                Segment(
                    a.t("live_work", start=hm(summary.shift_start or summary.status_since)),
                    LIVE_WORK_COLORS.accent,
                ),
                Segment(LIVE_SEPARATOR),
                Segment(
                    a.t("live_breaks", breaks=format_duration(summary.breaks)),
                    LIVE_BREAK_COLORS.accent,
                ),
            ]
            critical = a.t("live_critical_work")
            buttons = [
                Button(a.t("btn_break"), Action.START_BREAK),
                Button(a.t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        else:
            timer_start = summary.status_since
            message = [
                Segment(
                    a.t("live_break", since=hm(summary.status_since)), LIVE_BREAK_COLORS.accent
                ),
                Segment(LIVE_SEPARATOR),
                Segment(
                    a.t("live_worked", worked=format_duration(summary.work)),
                    LIVE_WORK_COLORS.accent,
                ),
            ]
            critical = a.t("live_critical_break")
            buttons = [
                Button(a.t("btn_resume"), Action.RESUME),
                Button(a.t("btn_clock_out"), Action.CLOCK_OUT),
            ]
        if end is not None:
            message += [Segment(LIVE_SEPARATOR), Segment(a.t("live_end", end=hm(end)))]

        progress = None
        if target is not None:
            target_minutes = int(target.total_seconds() // 60)
            worked_minutes = int(summary.work.total_seconds() // 60)
            progress = (min(worked_minutes, target_minutes), target_minutes)
        on_break = summary.status == WorkStatus.ON_BREAK
        await a.notifier.async_send_live(
            a.t("status_title"),
            message,
            critical_text=critical,
            timer_start=timer_start,
            progress=progress,
            on_break=on_break,
            buttons=buttons,
            icon=a.config.live_icon_break if on_break else a.config.live_icon_work,
        )
