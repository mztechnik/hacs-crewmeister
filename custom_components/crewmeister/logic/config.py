"""Typed view of the assistant options of a config entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import StrEnum
from typing import Any

from ..const import (
    CONF_ARRIVAL_DELAY,
    CONF_AUTO_RESUME,
    CONF_BACKDATE,
    CONF_BREAK_AFTER_6H,
    CONF_BREAK_AFTER_9H,
    CONF_BREAK_CHECK,
    CONF_BREAK_DURATION,
    CONF_BREAK_END_REMINDER,
    CONF_BREAK_REMINDER_AFTER,
    CONF_CLOCK_IN_MODE,
    CONF_CLOCK_OUT_MODE,
    CONF_DAILY_HOURS,
    CONF_DEPARTURE_DELAY,
    CONF_END_OF_DAY_GRACE,
    CONF_END_OF_DAY_REMINDER,
    CONF_FORGOTTEN_CHECK_TIME,
    CONF_HO_ACTIVITY_DELAY,
    CONF_HO_CLOCK_IN_MODE,
    CONF_HO_CLOCK_OUT_MODE,
    CONF_HO_IDLE_TIMEOUT,
    CONF_HO_POWER_SENSOR,
    CONF_HO_POWER_THRESHOLD,
    CONF_HO_PRESENCE_SENSORS,
    CONF_HO_SHORT_BREAK,
    CONF_HO_WINDOW_END,
    CONF_HO_WINDOW_START,
    CONF_LOCATION_HOME_OFFICE,
    CONF_LOCATION_OFFICE,
    CONF_LUNCH_BREAK_TIME,
    CONF_MAX_WORK_HOURS,
    CONF_NFC_TAGS,
    CONF_NOTIFY_CONFIRMATIONS,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_STATUS,
    CONF_NOTIFY_TARGETS,
    CONF_ONCE_PER_DAY,
    CONF_PERSON,
    CONF_PRESENCE_ENTITIES,
    CONF_REMIND_ON_LEAVE,
    CONF_REMINDER_TIME,
    CONF_SHORT_LEAVE_BREAK,
    CONF_SNOOZE_MINUTES,
    CONF_STAMP_LOCATION,
    CONF_WEEKDAY_HOURS_PREFIX,
    CONF_WIFI_SENSOR,
    CONF_WIFI_SSIDS,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    CONF_WORK_ZONES,
    CONF_WORKDAY_ENTITY,
    CONF_WORKDAYS,
)
from .workday import DEFAULT_WORKDAYS, WEEKDAYS


class StampMode(StrEnum):
    """How a detected arrival or departure is handled."""

    OFF = "off"
    ASK = "ask"
    AUTO = "auto"


# Defaults, also used to pre-fill the options form
DEFAULTS: dict[str, Any] = {
    CONF_WORKDAYS: DEFAULT_WORKDAYS,
    CONF_DAILY_HOURS: 8.0,
    CONF_NOTIFY_TARGETS: [],
    CONF_NOTIFY_CONFIRMATIONS: True,
    CONF_NOTIFY_STATUS: False,
    CONF_NOTIFY_LIVE: False,
    CONF_WORK_ZONES: [],
    CONF_WIFI_SSIDS: [],
    CONF_PRESENCE_ENTITIES: [],
    CONF_NFC_TAGS: [],
    CONF_CLOCK_IN_MODE: StampMode.OFF.value,
    CONF_CLOCK_OUT_MODE: StampMode.OFF.value,
    CONF_ARRIVAL_DELAY: 2,
    CONF_DEPARTURE_DELAY: 5,
    CONF_SHORT_LEAVE_BREAK: 0,
    CONF_WINDOW_START: "05:00:00",
    CONF_WINDOW_END: "22:00:00",
    CONF_BACKDATE: True,
    CONF_ONCE_PER_DAY: True,
    CONF_REMIND_ON_LEAVE: True,
    CONF_MAX_WORK_HOURS: 10.0,
    CONF_FORGOTTEN_CHECK_TIME: "07:00:00",
    CONF_SNOOZE_MINUTES: 30,
    CONF_END_OF_DAY_REMINDER: False,
    CONF_END_OF_DAY_GRACE: 20,
    CONF_BREAK_REMINDER_AFTER: 330,
    CONF_BREAK_DURATION: 30,
    CONF_BREAK_END_REMINDER: True,
    CONF_AUTO_RESUME: False,
    CONF_BREAK_CHECK: True,
    CONF_BREAK_AFTER_6H: 30,
    CONF_BREAK_AFTER_9H: 45,
    CONF_HO_POWER_THRESHOLD: 30.0,
    CONF_HO_PRESENCE_SENSORS: [],
    CONF_HO_CLOCK_IN_MODE: StampMode.OFF.value,
    CONF_HO_CLOCK_OUT_MODE: StampMode.AUTO.value,
    CONF_HO_SHORT_BREAK: 60,
    CONF_HO_ACTIVITY_DELAY: 5,
    CONF_HO_IDLE_TIMEOUT: 30,
    CONF_HO_WINDOW_START: "06:00:00",
    CONF_HO_WINDOW_END: "19:00:00",
    CONF_STAMP_LOCATION: False,
}


@dataclass(frozen=True, slots=True)
class AssistantConfig:
    """Assistant settings of one Crewmeister user."""

    workdays: list[str] = field(default_factory=lambda: list(DEFAULT_WORKDAYS))
    workday_entity: str | None = None
    daily_hours: timedelta = timedelta(hours=8)
    # Explicit target hours per weekday ("mon" ...); 0 means no target that day
    weekday_hours: dict[str, timedelta] = field(default_factory=dict)

    notify_targets: list[str] = field(default_factory=list)
    notify_confirmations: bool = True
    notify_status: bool = False
    notify_live: bool = False

    person: str | None = None
    work_zones: list[str] = field(default_factory=list)
    wifi_sensor: str | None = None
    wifi_ssids: list[str] = field(default_factory=list)
    presence_entities: list[str] = field(default_factory=list)
    nfc_tags: list[str] = field(default_factory=list)
    clock_in_mode: StampMode = StampMode.OFF
    clock_out_mode: StampMode = StampMode.OFF
    arrival_delay: timedelta = timedelta(minutes=2)
    departure_delay: timedelta = timedelta(minutes=5)
    short_leave_break: timedelta = timedelta(0)
    window_start: time = time(5, 0)
    window_end: time = time(22, 0)
    backdate: bool = True
    once_per_day: bool = True

    home_office_power_sensor: str | None = None
    home_office_power_threshold: float = 30.0
    home_office_presence_sensors: list[str] = field(default_factory=list)
    home_office_clock_in_mode: StampMode = StampMode.OFF
    home_office_clock_out_mode: StampMode = StampMode.AUTO
    home_office_short_break: timedelta = timedelta(minutes=60)
    home_office_activity_delay: timedelta = timedelta(minutes=5)
    home_office_idle_timeout: timedelta = timedelta(minutes=30)
    home_office_window_start: time = time(6, 0)
    home_office_window_end: time = time(19, 0)

    stamp_location: bool = False
    location_office: str | None = None
    location_home_office: str | None = None

    remind_on_leave: bool = True
    reminder_time: time | None = None
    max_work: timedelta | None = timedelta(hours=10)
    forgotten_check_time: time | None = time(7, 0)
    snooze: timedelta = timedelta(minutes=30)
    end_of_day_reminder: bool = False
    end_of_day_grace: timedelta = timedelta(minutes=20)

    break_reminder_after: timedelta | None = timedelta(minutes=330)
    break_duration: timedelta = timedelta(minutes=30)
    break_end_reminder: bool = True
    auto_resume: bool = False
    break_check: bool = True
    break_after_6h: timedelta = timedelta(minutes=30)
    break_after_9h: timedelta = timedelta(minutes=45)
    lunch_break_time: time | None = None

    @property
    def home_office_configured(self) -> bool:
        """Return whether home office detection is configured."""

        return bool(
            self.person and (self.home_office_power_sensor or self.home_office_presence_sensors)
        )

    @property
    def presence_configured(self) -> bool:
        """Return whether any presence source is configured."""

        return bool(
            (self.person and self.work_zones)
            or (self.wifi_sensor and self.wifi_ssids)
            or self.presence_entities
        )

    def target_hours(self, day: date) -> timedelta | None:
        """Return the target working time of ``day``, ``None`` if there is none."""

        weekday = WEEKDAYS[day.weekday()]
        if weekday in self.weekday_hours:
            hours = self.weekday_hours[weekday]
        elif weekday in self.workdays:
            hours = self.daily_hours
        else:
            return None
        return hours if hours > timedelta(0) else None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> AssistantConfig:
        """Parse options, falling back to defaults for missing or invalid values."""

        def get(key: str) -> Any:
            value = options.get(key)
            return DEFAULTS.get(key) if value is None else value

        def minutes(key: str) -> timedelta:
            return timedelta(minutes=max(0.0, _number(get(key), DEFAULTS[key])))

        def optional_hours(key: str) -> timedelta | None:
            hours = _number(get(key), DEFAULTS[key])
            return timedelta(hours=hours) if hours > 0 else None

        def optional_minutes(key: str) -> timedelta | None:
            value = minutes(key)
            return value if value > timedelta(0) else None

        return cls(
            workdays=[d for d in _str_list(get(CONF_WORKDAYS)) if d in WEEKDAYS],
            workday_entity=_entity(options.get(CONF_WORKDAY_ENTITY)),
            daily_hours=timedelta(hours=_number(get(CONF_DAILY_HOURS), 8.0)),
            weekday_hours={
                day: timedelta(hours=max(0.0, _number(value, 0.0)))
                for day in WEEKDAYS
                if (value := options.get(f"{CONF_WEEKDAY_HOURS_PREFIX}{day}")) is not None
            },
            notify_targets=[t.removeprefix("notify.") for t in _str_list(get(CONF_NOTIFY_TARGETS))],
            notify_confirmations=bool(get(CONF_NOTIFY_CONFIRMATIONS)),
            notify_status=bool(get(CONF_NOTIFY_STATUS)),
            notify_live=bool(get(CONF_NOTIFY_LIVE)),
            person=_entity(options.get(CONF_PERSON)),
            work_zones=_str_list(get(CONF_WORK_ZONES)),
            wifi_sensor=_entity(options.get(CONF_WIFI_SENSOR)),
            wifi_ssids=[s.strip() for s in _str_list(get(CONF_WIFI_SSIDS)) if s.strip()],
            presence_entities=_str_list(get(CONF_PRESENCE_ENTITIES)),
            nfc_tags=[t.strip() for t in _str_list(get(CONF_NFC_TAGS)) if t.strip()],
            clock_in_mode=_mode(get(CONF_CLOCK_IN_MODE)),
            clock_out_mode=_mode(get(CONF_CLOCK_OUT_MODE)),
            arrival_delay=minutes(CONF_ARRIVAL_DELAY),
            departure_delay=minutes(CONF_DEPARTURE_DELAY),
            short_leave_break=minutes(CONF_SHORT_LEAVE_BREAK),
            window_start=_time(get(CONF_WINDOW_START)) or time(5, 0),
            window_end=_time(get(CONF_WINDOW_END)) or time(22, 0),
            backdate=bool(get(CONF_BACKDATE)),
            once_per_day=bool(get(CONF_ONCE_PER_DAY)),
            home_office_power_sensor=_entity(options.get(CONF_HO_POWER_SENSOR)),
            home_office_power_threshold=_number(get(CONF_HO_POWER_THRESHOLD), 30.0),
            home_office_presence_sensors=_str_list(get(CONF_HO_PRESENCE_SENSORS)),
            home_office_clock_in_mode=_mode(get(CONF_HO_CLOCK_IN_MODE)),
            home_office_clock_out_mode=_mode(get(CONF_HO_CLOCK_OUT_MODE)),
            home_office_short_break=minutes(CONF_HO_SHORT_BREAK),
            home_office_activity_delay=minutes(CONF_HO_ACTIVITY_DELAY),
            home_office_idle_timeout=minutes(CONF_HO_IDLE_TIMEOUT) or timedelta(minutes=30),
            home_office_window_start=_time(get(CONF_HO_WINDOW_START)) or time(6, 0),
            home_office_window_end=_time(get(CONF_HO_WINDOW_END)) or time(19, 0),
            stamp_location=bool(get(CONF_STAMP_LOCATION)),
            location_office=_text(options.get(CONF_LOCATION_OFFICE)),
            location_home_office=_text(options.get(CONF_LOCATION_HOME_OFFICE)),
            remind_on_leave=bool(get(CONF_REMIND_ON_LEAVE)),
            reminder_time=_time(options.get(CONF_REMINDER_TIME)),
            max_work=optional_hours(CONF_MAX_WORK_HOURS),
            # An explicitly emptied field disables the check
            forgotten_check_time=_time(options[CONF_FORGOTTEN_CHECK_TIME])
            if CONF_FORGOTTEN_CHECK_TIME in options
            else _time(DEFAULTS[CONF_FORGOTTEN_CHECK_TIME]),
            snooze=minutes(CONF_SNOOZE_MINUTES) or timedelta(minutes=30),
            end_of_day_reminder=bool(get(CONF_END_OF_DAY_REMINDER)),
            end_of_day_grace=minutes(CONF_END_OF_DAY_GRACE),
            break_reminder_after=optional_minutes(CONF_BREAK_REMINDER_AFTER),
            break_duration=minutes(CONF_BREAK_DURATION) or timedelta(minutes=30),
            break_end_reminder=bool(get(CONF_BREAK_END_REMINDER)),
            auto_resume=bool(get(CONF_AUTO_RESUME)),
            break_check=bool(get(CONF_BREAK_CHECK)),
            break_after_6h=minutes(CONF_BREAK_AFTER_6H),
            break_after_9h=minutes(CONF_BREAK_AFTER_9H),
            lunch_break_time=_time(options.get(CONF_LUNCH_BREAK_TIME)),
        )


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return []


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _entity(value: Any) -> str | None:
    return value if isinstance(value, str) and "." in value else None


def _mode(value: Any) -> StampMode:
    try:
        return StampMode(value)
    except ValueError:
        return StampMode.OFF


def _time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None
