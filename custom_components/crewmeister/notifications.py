"""Actionable notifications via the Home Assistant Companion App (Android and iOS)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import html
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import slugify

from .const import NOTIFICATION_ACTION_PREFIX

_LOGGER = logging.getLogger(__name__)

NOTIFY_DOMAIN = "notify"


@dataclass(frozen=True, slots=True)
class LiveColors:
    """Colors of the live display for one status."""

    # Icon, status bar chip and progress bar
    accent: str
    # Lock Screen card (iOS only)
    background: str
    text: str


LIVE_WORK_COLORS = LiveColors(accent="#03A9F4", background="#0B2638", text="#FFFFFF")
LIVE_BREAK_COLORS = LiveColors(accent="#F9A825", background="#3A2A06", text="#FFFFFF")


@dataclass(frozen=True, slots=True)
class Segment:
    """Part of a live display message, optionally shown in its own color."""

    text: str
    color: str | None = None


def render_segments(segments: list[Segment], *, html_colors: bool) -> str:
    """Join ``segments``; as HTML with colored text if ``html_colors`` (Android).

    The Android app renders messages as HTML, iOS shows tags as plain text.
    """

    if not html_colors:
        return "".join(segment.text for segment in segments)
    return "".join(
        f'<font color="{segment.color}">{html.escape(segment.text)}</font>'
        if segment.color
        else html.escape(segment.text)
        for segment in segments
    )


class Action(StrEnum):
    """Actions offered by notification buttons."""

    CLOCK_IN = "CLOCK_IN"
    CLOCK_OUT = "CLOCK_OUT"
    START_BREAK = "START_BREAK"
    RESUME = "RESUME"
    SNOOZE = "SNOOZE"
    IGNORE = "IGNORE"
    ADD_BREAK = "ADD_BREAK"


class Kind(StrEnum):
    """Notification slots; a new notification replaces the previous one of its kind."""

    PRESENCE = "presence"
    REMINDER = "reminder"
    BREAK = "break"
    INFO = "info"
    STATUS = "status"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class Button:
    """A notification button."""

    title: str
    action: Action
    arg: str | None = None


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """A decoded button press."""

    entry_id: str
    action: Action
    arg: str | None


def encode_action(entry_id: str, action: Action, arg: str | None = None) -> str:
    """Return the action identifier sent with a notification button."""

    parts = [NOTIFICATION_ACTION_PREFIX, entry_id, action.value]
    if arg is not None:
        parts.append(arg)
    return ":".join(parts)


def decode_action(value: Any) -> ActionEvent | None:
    """Decode an action identifier, ``None`` if it does not belong to this integration."""

    if not isinstance(value, str):
        return None
    parts = value.split(":", 3)
    if len(parts) < 3 or parts[0] != NOTIFICATION_ACTION_PREFIX:
        return None
    try:
        action = Action(parts[2])
    except ValueError:
        return None
    return ActionEvent(entry_id=parts[1], action=action, arg=parts[3] if len(parts) > 3 else None)


def build_payload(
    entry_id: str,
    kind: Kind,
    title: str,
    message: str,
    buttons: list[Button] | None = None,
    *,
    time_sensitive: bool = False,
) -> dict[str, Any]:
    """Return ``notify.mobile_app_*`` service data understood by Android and iOS."""

    data: dict[str, Any] = {
        "tag": tag(entry_id, kind),
        "group": f"crewmeister_{entry_id}",
        "channel": "Crewmeister",
        "importance": "high" if time_sensitive else "default",
    }
    if buttons:
        data["actions"] = [
            {"action": encode_action(entry_id, b.action, b.arg), "title": b.title} for b in buttons
        ]
    if time_sensitive:
        data["push"] = {"interruption-level": "time-sensitive"}
    return {"title": title, "message": message, "data": data}


def build_status_payload(
    entry_id: str, title: str, message: str, since: datetime, buttons: list[Button]
) -> dict[str, Any]:
    """Return an ongoing notification with a running timer (Android only)."""

    payload = build_payload(entry_id, Kind.STATUS, title, message, buttons)
    payload["data"].update(
        {
            "channel": "Crewmeister Status",
            "importance": "low",
            "sticky": "true",
            "persistent": True,
            "chronometer": True,
            "when": int(since.timestamp()),
            "notification_icon": "mdi:briefcase-clock",
            "alert_once": True,
        }
    )
    return payload


def build_live_payload(
    entry_id: str,
    title: str,
    message: list[Segment],
    *,
    critical_text: str,
    timer_start: datetime,
    progress: tuple[int, int] | None,
    on_break: bool,
    buttons: list[Button] | None = None,
    android: bool = False,
    icon: str | None = None,
) -> dict[str, Any]:
    """Return a Live Activity (iOS) / Live Update (Android) payload.

    Work and break differ in icon and colors. Android uses one accent color for
    icon, timer and progress bar, so the message colors work and break times;
    the card colors only apply on iOS. Buttons only show on Android, iOS Live
    Activities cannot show any.
    See https://companion.home-assistant.io/docs/notifications/live-activities
    """

    colors = LIVE_BREAK_COLORS if on_break else LIVE_WORK_COLORS
    data: dict[str, Any] = {
        "tag": tag(entry_id, Kind.LIVE),
        "live_update": True,
        "critical_text": critical_text,
        "chronometer": True,
        "when": int(timer_start.timestamp()),
        "notification_icon": icon or ("mdi:coffee" if on_break else "mdi:briefcase-clock"),
        "notification_icon_color": colors.accent,
        "color": colors.accent,
        "progress_bar_color": colors.accent,
        "background_color": colors.background,
        "text_color": colors.text,
        "silent": True,
        "alert_once": True,
        "sticky": True,
    }
    if progress is not None:
        data["progress"], data["progress_max"] = progress
    if buttons:
        data["actions"] = [
            {"action": encode_action(entry_id, b.action, b.arg), "title": b.title} for b in buttons
        ]
    text = render_segments(message, html_colors=android)
    return {"title": title, "message": text, "data": data}


def tag(entry_id: str, kind: Kind) -> str:
    """Return the notification tag of ``kind``."""

    return f"crewmeister_{entry_id}_{kind.value}"


class Notifier:
    """Send notifications to the configured Companion App devices."""

    def __init__(self, hass: HomeAssistant, entry_id: str, targets: list[str]) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._targets = targets

    @property
    def enabled(self) -> bool:
        """Return whether any notification target is configured."""

        return bool(self._targets)

    async def async_send(
        self,
        kind: Kind,
        title: str,
        message: str,
        buttons: list[Button] | None = None,
        *,
        time_sensitive: bool = False,
    ) -> None:
        """Send a notification, replacing an earlier one of the same ``kind``."""

        await self._async_call(
            build_payload(
                self._entry_id, kind, title, message, buttons, time_sensitive=time_sensitive
            )
        )

    async def async_send_status(
        self, title: str, message: str, since: datetime, buttons: list[Button]
    ) -> None:
        """Show the ongoing status notification."""

        await self._async_call(build_status_payload(self._entry_id, title, message, since, buttons))

    async def async_send_live(
        self,
        title: str,
        message: list[Segment],
        *,
        critical_text: str,
        timer_start: datetime,
        progress: tuple[int, int] | None,
        on_break: bool,
        buttons: list[Button] | None = None,
        icon: str | None = None,
    ) -> None:
        """Start or update the live display; updates with the same tag replace it."""

        android = self._android_targets()
        for target in self._targets:
            await self._async_call_target(
                target,
                build_live_payload(
                    self._entry_id,
                    title,
                    message,
                    critical_text=critical_text,
                    timer_start=timer_start,
                    progress=progress,
                    on_break=on_break,
                    buttons=buttons,
                    android=target in android,
                    icon=icon,
                ),
            )

    async def async_clear(self, kind: Kind) -> None:
        """Remove the notification of ``kind`` from the devices."""

        await self._async_call(
            {"message": "clear_notification", "data": {"tag": tag(self._entry_id, kind)}}
        )

    def _android_targets(self) -> set[str]:
        """Return the targets registered by the Android Companion App."""

        return {
            f"mobile_app_{slugify(entry.data['device_name'])}"
            for entry in self._hass.config_entries.async_entries("mobile_app")
            if entry.data.get("device_name") and entry.data.get("os_name") == "Android"
        }

    async def _async_call(self, payload: dict[str, Any]) -> None:
        for target in self._targets:
            await self._async_call_target(target, payload)

    async def _async_call_target(self, target: str, payload: dict[str, Any]) -> None:
        if not self._hass.services.has_service(NOTIFY_DOMAIN, target):
            _LOGGER.warning("Notification service notify.%s does not exist", target)
            return
        try:
            await self._hass.services.async_call(NOTIFY_DOMAIN, target, payload, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Sending notification via notify.%s failed: %s", target, err)
