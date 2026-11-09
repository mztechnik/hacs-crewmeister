"""Break assistant and end of day reminders."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ..api import CrewmeisterError, StampType, WorkStatus
from ..logic.breaks import MAX_ADDED_BREAK, break_choices, clamp_break, missing_break
from ..logic.texts import format_duration
from ..logic.worktime import DaySummary, required_break, summarize
from ..notifications import Action, Button, Kind
from .state import BreakQuestion
from .util import action_arg, day_hm, hm, iso

if TYPE_CHECKING:
    from .core import CrewmeisterAssistant

_LOGGER = logging.getLogger(__name__)

# A backdated clock out offer must stay valid at least this long after sending
FORGOTTEN_OFFER_MARGIN = timedelta(hours=12)
MAX_ACTION_AGE = timedelta(days=3)


class Reminders:
    """Reminders, break checks and automatic breaks."""

    def __init__(self, assistant: CrewmeisterAssistant) -> None:
        self._a = assistant
        self._unsubs: list[CALLBACK_TYPE] = []

    def async_start(self) -> None:
        """Schedule the reminders at fixed times."""

        cfg = self._a.config
        window = cfg.break_window
        times = [
            (cfg.reminder_time, self._async_reminder_time),
            (cfg.forgotten_check_time, self._async_forgotten_check),
        ]
        if window is not None and cfg.break_window_auto:
            times.append((window[0], self._async_break_window_start))
        if window is not None and cfg.break_window_resume:
            times.append((window[1], self._async_break_window_end))
        for at, handler in times:
            if at is not None:
                self._unsubs.append(
                    async_track_time_change(
                        self._a.hass, handler, hour=at.hour, minute=at.minute, second=at.second
                    )
                )

    def async_stop(self) -> None:
        """Cancel the scheduled reminders."""

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ---------------------------------------------------------------- periodic

    async def async_tick(self) -> None:
        """Check reminders and the break assistant once a minute."""

        a = self._a
        await self._async_break_question_timeout()
        data = a.status.data
        if data is None:
            return
        cfg = a.config
        summary = data.today()
        today = dt_util.now().date().isoformat()
        now = dt_util.utcnow()

        if a.state.snooze_until and now >= a.state.snooze_until:
            a.state.snooze_until = None
            a.save()
            if summary.status != WorkStatus.CLOCKED_OUT:
                await self._async_send_still_clocked_in(summary)

        if summary.status == WorkStatus.CLOCKED_OUT:
            return
        if summary.shift_start and dt_util.as_local(summary.shift_start).date().isoformat() < today:
            # Most likely clocking out was forgotten; the forgotten check handles that
            return

        end = a.expected_end(summary)
        if (
            cfg.end_of_day_reminder
            and end is not None
            and now >= end + cfg.end_of_day_grace
            and a.mark("end_of_day", iso(summary.shift_start) or today)
        ):
            await a.notifier.async_send(
                Kind.REMINDER,
                a.t("end_of_day_title"),
                a.t(
                    "end_of_day_message",
                    target=format_duration(a.target_hours(summary) or timedelta(0)),
                    time=hm(end),
                ),
                [Button(a.t("btn_clock_out"), Action.CLOCK_OUT), a.snooze_button()],
                time_sensitive=True,
            )

        if cfg.max_work and summary.work >= cfg.max_work and a.mark("max_work", today):
            await a.notifier.async_send(
                Kind.REMINDER,
                a.t("max_work_title"),
                a.t("max_work_message", worked=format_duration(summary.work)),
                [Button(a.t("btn_clock_out"), Action.CLOCK_OUT), a.snooze_button()],
                time_sensitive=True,
            )

        since = iso(summary.status_since) or ""
        if (
            summary.status == WorkStatus.CLOCKED_IN
            and cfg.break_reminder_after
            and summary.work_since_break >= cfg.break_reminder_after
            and a.mark("break_due", since)
        ):
            await a.notifier.async_send(
                Kind.BREAK,
                a.t("break_due_title"),
                a.t("break_due_message", worked=format_duration(summary.work_since_break)),
                [Button(a.t("btn_break"), Action.START_BREAK)],
            )

        if (
            summary.status == WorkStatus.ON_BREAK
            and summary.current_break >= cfg.break_duration
            and (cfg.auto_resume or cfg.break_end_reminder)
            and a.mark("break_over", since)
        ):
            if cfg.auto_resume:
                await a.async_stamp(StampType.START_WORK, automatic=True)
            else:
                await a.notifier.async_send(
                    Kind.BREAK,
                    a.t("break_over_title"),
                    a.t("break_over_message", duration=format_duration(summary.current_break)),
                    [Button(a.t("btn_resume"), Action.RESUME)],
                    time_sensitive=True,
                )

    async def _async_send_still_clocked_in(self, summary: DaySummary) -> None:
        a = self._a
        await a.notifier.async_send(
            Kind.REMINDER,
            a.t("still_clocked_in_title"),
            a.t("still_clocked_in_message", worked=format_duration(summary.work)),
            [Button(a.t("btn_clock_out"), Action.CLOCK_OUT), a.snooze_button()],
            time_sensitive=True,
        )

    # ------------------------------------------------------------- fixed times

    async def _async_reminder_time(self, _now: datetime) -> None:
        summary = await self._a.async_fresh_summary()
        if summary is not None and summary.status != WorkStatus.CLOCKED_OUT:
            await self._async_send_still_clocked_in(summary)

    async def _async_forgotten_check(self, _now: datetime) -> None:
        """Offer to clock out a shift that started on an earlier day."""

        a = self._a
        summary = await a.async_fresh_summary()
        if summary is None or summary.status == WorkStatus.CLOCKED_OUT or not summary.shift_start:
            return
        if dt_util.as_local(summary.shift_start).date() >= dt_util.now().date():
            return

        cfg = a.config
        left_at = a.state.left_at
        if left_at is not None and left_at <= summary.shift_start:
            left_at = None
        target = a.target_hours(summary) or cfg.daily_hours
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
                    a.t("btn_clock_out_at", time=day_hm(offer)),
                    Action.CLOCK_OUT,
                    action_arg(offer),
                )
            )
        buttons.append(Button(a.t("btn_clock_out_now"), Action.CLOCK_OUT))

        start = day_hm(summary.shift_start)
        message = (
            a.t("forgotten_message_left", start=start, left=day_hm(left_at))
            if left_at
            else a.t("forgotten_message", start=start)
        )
        await a.notifier.async_send(
            Kind.REMINDER, a.t("forgotten_title"), message, buttons, time_sensitive=True
        )

    async def _async_break_window_start(self, _now: datetime) -> None:
        """Start the break automatically at the begin of the break window."""

        a = self._a
        if not a.enabled:
            return
        summary = await a.async_fresh_summary()
        if summary is not None and summary.status == WorkStatus.CLOCKED_IN:
            await a.async_stamp(StampType.START_BREAK, automatic=True)

    async def _async_break_window_end(self, _now: datetime) -> None:
        """Remind to resume work at the end of the break window."""

        a = self._a
        summary = await a.async_fresh_summary()
        if summary is None or summary.status != WorkStatus.ON_BREAK or not summary.status_since:
            return
        await a.notifier.async_send(
            Kind.BREAK,
            a.t("resume_time_title"),
            a.t(
                "resume_time_message",
                since=hm(summary.status_since),
                duration=format_duration(summary.current_break),
            ),
            [Button(a.t("btn_resume"), Action.RESUME)],
            time_sensitive=True,
        )

    # -------------------------------------------------------------- break check

    async def async_clocked_out(self) -> None:
        """Ask how long the break was if the required break is missing."""

        a = self._a
        cfg = a.config
        data = a.status.data
        if not cfg.break_check or data is None:
            return
        last = data.today()
        if last.shift_start is None or last.latest is None or last.latest.id is None:
            return
        # Look at the whole shift, even if it started yesterday
        shift = summarize(data.stamps, dt_util.utcnow(), last.shift_start)
        missing = missing_break(shift, cfg.break_after_6h, cfg.break_after_9h)
        if missing <= timedelta(0):
            return
        default = clamp_break(max(cfg.break_default, missing)) if cfg.break_default else None
        choices = break_choices(missing, default or missing)
        required = required_break(shift.work, cfg.break_after_6h, cfg.break_after_9h)
        timeout = int(cfg.break_question_timeout.total_seconds() // 60)
        if default is not None:
            hint = a.t("break_question_default", timeout=timeout, minutes=_minutes(default))
        else:
            hint = a.t("break_question_no_default")
        stamp_id = last.latest.id
        buttons = [
            Button(
                a.t("btn_break_minutes", minutes=_minutes(c)),
                Action.ADD_BREAK,
                f"{_minutes(c)}-{stamp_id}",
            )
            for c in choices
        ]
        buttons.append(Button(a.t("btn_no_break"), Action.NO_BREAK, str(stamp_id)))
        if not a.notifier.enabled:
            # Nobody can be asked: add the default right away
            if default is not None:
                await self._async_add_break(stamp_id, default, automatic=True)
            return
        await a.notifier.async_send(
            Kind.BREAK,
            a.t("break_question_title"),
            a.t(
                "break_question_message",
                worked=format_duration(shift.work),
                required=format_duration(required),
                taken=format_duration(shift.rest_breaks),
            )
            + " "
            + hint,
            buttons,
        )
        a.state.break_question = BreakQuestion(
            stamp_id,
            _minutes(default) if default is not None else 0,
            dt_util.utcnow() + cfg.break_question_timeout,
        )
        a.save()

    async def _async_break_question_timeout(self) -> None:
        a = self._a
        question = a.state.break_question
        if question is None or dt_util.utcnow() < question.expires:
            return
        a.state.break_question = None
        a.save()
        await a.notifier.async_clear(Kind.BREAK)
        if question.default_minutes > 0:
            await self._async_add_break(
                question.stamp_id, timedelta(minutes=question.default_minutes), automatic=True
            )

    async def async_break_answer(self, action: Action, arg: str | None) -> None:
        """Handle a button of the break question."""

        a = self._a
        if action == Action.NO_BREAK:
            if a.state.break_question is not None:
                a.state.break_question = None
                a.save()
            return
        try:
            minutes_str, stamp_id_str = (arg or "").split("-", 1)
            minutes, stamp_id = int(minutes_str), int(stamp_id_str)
        except ValueError:
            _LOGGER.debug("Invalid break action argument: %s", arg)
            return
        if not 0 < minutes <= MAX_ADDED_BREAK.total_seconds() / 60:
            _LOGGER.warning("Rejected break of %s min", minutes)
            return
        question = a.state.break_question
        if question is not None and question.stamp_id == stamp_id:
            a.state.break_question = None
            a.save()
        await self._async_add_break(stamp_id, timedelta(minutes=minutes))

    async def _async_add_break(
        self, stamp_id: int, duration: timedelta, *, automatic: bool = False
    ) -> None:
        a = self._a
        # Only breaks for the user's own recent stamps
        data = a.status.data
        if data is None or stamp_id not in {stamp.id for stamp in data.stamps}:
            _LOGGER.warning("Rejected break for unknown stamp %s", stamp_id)
            return
        async with a.stamp_lock:
            # The API adds the break; a second tap (e.g. phone and watch) must not
            # add it twice
            if a.state.sent.get("break_added") == str(stamp_id):
                _LOGGER.debug("Break for stamp %s was already added", stamp_id)
                return
            try:
                await a.client.async_set_break(stamp_id, duration)
            except CrewmeisterError as err:
                await a.async_failure(a.t("error_api", error=str(err)))
                return
            a.mark("break_added", str(stamp_id))
            await a.status.async_refresh()
        key = "break_added_default" if automatic else "break_added"
        await a.async_info(a.t(key, minutes=_minutes(duration)))


def _minutes(value: timedelta) -> int:
    return int(-(-value.total_seconds() // 60))
