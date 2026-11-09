"""Migration of options from version 0.4/0.5 (config entry version 1) to V2."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any

# Options that no longer exist in V2
REMOVED = {
    "nfc_tags",
    "once_per_day",
    "short_leave_break",
    "backdate",
    "notify_status",
    "lunch_break_time",
    "resume_reminder_time",
    "remind_on_leave",
    "clock_out_mode",
    "home_office_clock_in_mode",
    "home_office_clock_out_mode",
    "home_office_short_break",
    "home_office_window_start",
    "home_office_window_end",
}
WEEKDAY_HOURS_PREFIX = "hours_"
# Options set by the migration that may already exist in the V2 format
V2_KEYS = {
    "end_of_day_mode",
    "ask_on_leave",
    "break_window_start",
    "break_window_end",
    "break_window_auto",
    "break_window_resume",
}
OFF, ASK = "off", "ask"


def _office_configured(options: Mapping[str, Any]) -> bool:
    return bool(
        (options.get("person") and options.get("work_zones"))
        or (options.get("wifi_sensor") and options.get("wifi_ssids"))
        or options.get("presence_entities")
    )


def _home_office_configured(options: Mapping[str, Any]) -> bool:
    return bool(
        options.get("person")
        and (options.get("home_office_power_sensor") or options.get("home_office_presence_sensors"))
    )


def _merge_modes(
    office: str | None, home_office: str | None, office_used: bool, home_used: bool
) -> str:
    """Return one mode for office and home office; differing modes become "ask"."""

    office = office or OFF
    home_office = home_office or OFF
    if office_used and home_used:
        return office if office == home_office else ASK
    if home_used:
        return home_office
    return office


def _time(value: Any) -> time | None:
    if isinstance(value, str) and value:
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None


def migrate_options_v1(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the V2 options for the options of a version 1 entry."""

    old = dict(options)
    new = {
        key: value
        for key, value in old.items()
        if key not in REMOVED and not key.startswith(WEEKDAY_HOURS_PREFIX)
    }
    office_used = _office_configured(old)
    home_used = _home_office_configured(old)

    # Arrival: one mode for office and home office (home office defaulted to off)
    new["clock_in_mode"] = _merge_modes(
        old.get("clock_in_mode"), old.get("home_office_clock_in_mode"), office_used, home_used
    )
    # Clocking out on departure now happens in the end of day period; by default
    # once the target working time is reached (home office defaulted to auto)
    new["end_of_day_mode"] = _merge_modes(
        old.get("clock_out_mode"),
        old.get("home_office_clock_out_mode", "auto"),
        office_used,
        home_used,
    )
    # The reminder when leaving becomes the question when leaving during work
    new["ask_on_leave"] = bool(old.get("remind_on_leave", True)) and office_used

    # Fixed lunch break and resume reminder become the break window
    lunch = _time(old.get("lunch_break_time"))
    resume = _time(old.get("resume_reminder_time"))
    if lunch is not None:
        duration = old.get("break_duration") or 30
        try:
            minutes = float(duration)
        except (TypeError, ValueError):
            minutes = 30.0
        end = resume or (datetime.combine(datetime.min, lunch) + timedelta(minutes=minutes)).time()
        if end > lunch:
            new["break_window_start"] = lunch.isoformat()
            new["break_window_end"] = end.isoformat()
            new["break_window_auto"] = True
            new["break_window_resume"] = resume is not None
    # Values already in the V2 format win
    new.update({key: value for key, value in old.items() if key in V2_KEYS})
    return new
