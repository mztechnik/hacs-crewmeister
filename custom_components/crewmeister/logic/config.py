"""Typed view of the assistant options of a config entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import StrEnum
from typing import Any

from ..const import (
    CONF_ABSENCE_CALENDAR,
    CONF_ABSENCE_KEYWORDS,
    CONF_ABSENCE_SENSOR,
    CONF_ARRIVAL_DELAY,
    CONF_ARRIVAL_OFFSET,
    CONF_ASK_ON_LEAVE,
    CONF_ASK_TIMEOUT,
    CONF_AUTO_RESUME,
    CONF_BREAK_AFTER_6H,
    CONF_BREAK_AFTER_9H,
    CONF_BREAK_CHECK,
    CONF_BREAK_DEFAULT,
    CONF_BREAK_DURATION,
    CONF_BREAK_END_REMINDER,
    CONF_BREAK_MODE,
    CONF_BREAK_QUESTION_TIMEOUT,
    CONF_BREAK_REMINDER_AFTER,
    CONF_BREAK_WINDOW_AUTO,
    CONF_BREAK_WINDOW_END,
    CONF_BREAK_WINDOW_RESUME,
    CONF_BREAK_WINDOW_START,
    CONF_CATCH_UP,
    CONF_CLOCK_IN_MODE,
    CONF_DAILY_HOURS,
    CONF_DEPARTURE_DELAY,
    CONF_DEPARTURE_OFFSET,
    CONF_END_OF_DAY_GRACE,
    CONF_END_OF_DAY_MODE,
    CONF_END_OF_DAY_ON_TARGET,
    CONF_END_OF_DAY_REMINDER,
    CONF_END_OF_DAY_TIME,
    CONF_FORGOTTEN_CHECK_TIME,
    CONF_HO_ACTIVITY_DELAY,
    CONF_HO_IDLE_TIMEOUT,
    CONF_HO_POWER_SENSOR,
    CONF_HO_POWER_THRESHOLD,
    CONF_HO_PRESENCE_SENSORS,
    CONF_LIVE_ICON_BREAK,
    CONF_LIVE_ICON_WORK,
    CONF_LOCATION_AS_NOTE,
    CONF_LOCATION_HOME_OFFICE,
    CONF_LOCATION_OFFICE,
    CONF_MAX_WORK_HOURS,
    CONF_NOTIFY_CONFIRMATIONS,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_TARGETS,
    CONF_OFFICE_COMBINE,
    CONF_PERSON,
    CONF_PRESENCE_ENTITIES,
    CONF_REMINDER_TIME,
    CONF_SNOOZE_MINUTES,
    CONF_STAMP_LOCATION,
    CONF_WIFI_SENSOR,
    CONF_WIFI_SSIDS,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    CONF_WORK_ZONES,
    CONF_WORKDAY_ENTITY,
    CONF_WORKDAYS,
    DEFAULT_LIVE_ICON_BREAK,
    DEFAULT_LIVE_ICON_WORK,
)
from .sources import Combine
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
    CONF_WINDOW_START: "05:00:00",
    CONF_WINDOW_END: "22:00:00",
    CONF_ABSENCE_KEYWORDS: [],
    CONF_NOTIFY_TARGETS: [],
    CONF_NOTIFY_CONFIRMATIONS: True,
    CONF_NOTIFY_LIVE: False,
    CONF_LIVE_ICON_WORK: DEFAULT_LIVE_ICON_WORK,
    CONF_LIVE_ICON_BREAK: DEFAULT_LIVE_ICON_BREAK,
    CONF_WORK_ZONES: [],
    CONF_WIFI_SSIDS: [],
    CONF_PRESENCE_ENTITIES: [],
    CONF_OFFICE_COMBINE: Combine.ANY.value,
    CONF_ARRIVAL_DELAY: 2,
    CONF_DEPARTURE_DELAY: 10,
    CONF_HO_POWER_THRESHOLD: 30.0,
    CONF_HO_PRESENCE_SENSORS: [],
    CONF_HO_ACTIVITY_DELAY: 5,
    CONF_HO_IDLE_TIMEOUT: 30,
    CONF_CLOCK_IN_MODE: StampMode.OFF.value,
    CONF_ARRIVAL_OFFSET: 0,
    CONF_DEPARTURE_OFFSET: 0,
    CONF_BREAK_MODE: StampMode.OFF.value,
    CONF_BREAK_WINDOW_AUTO: False,
    CONF_BREAK_WINDOW_RESUME: False,
    CONF_END_OF_DAY_MODE: StampMode.OFF.value,
    CONF_END_OF_DAY_ON_TARGET: True,
    CONF_ASK_ON_LEAVE: False,
    CONF_ASK_TIMEOUT: 30,
    CONF_CATCH_UP: True,
    CONF_STAMP_LOCATION: False,
    CONF_LOCATION_AS_NOTE: False,
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
    CONF_BREAK_DEFAULT: 30,
    CONF_BREAK_QUESTION_TIMEOUT: 60,
}


@dataclass(frozen=True, slots=True)
class AssistantConfig:
    """Assistant settings of one Crewmeister user."""

    # Working time and absences
    workdays: list[str] = field(default_factory=lambda: list(DEFAULT_WORKDAYS))
    workday_entity: str | None = None
    daily_hours: timedelta = timedelta(hours=8)
    window_start: time = time(5, 0)
    window_end: time = time(22, 0)
    absence_calendar: str | None = None
    absence_keywords: list[str] = field(default_factory=list)
    absence_sensor: str | None = None

    # Notifications
    notify_targets: list[str] = field(default_factory=list)
    notify_confirmations: bool = True
    notify_live: bool = False
    live_icon_work: str = DEFAULT_LIVE_ICON_WORK
    live_icon_break: str = DEFAULT_LIVE_ICON_BREAK

    # Office detection
    person: str | None = None
    work_zones: list[str] = field(default_factory=list)
    wifi_sensor: str | None = None
    wifi_ssids: list[str] = field(default_factory=list)
    presence_entities: list[str] = field(default_factory=list)
    office_combine: Combine = Combine.ANY
    arrival_delay: timedelta = timedelta(minutes=2)
    departure_delay: timedelta = timedelta(minutes=10)

    # Home office detection
    home_office_power_sensor: str | None = None
    home_office_power_threshold: float = 30.0
    home_office_presence_sensors: list[str] = field(default_factory=list)
    home_office_activity_delay: timedelta = timedelta(minutes=5)
    home_office_idle_timeout: timedelta = timedelta(minutes=30)

    # Stamping rules (office and home office)
    arrival_mode: StampMode = StampMode.OFF
    arrival_offset: timedelta = timedelta(0)
    departure_offset: timedelta = timedelta(0)
    break_mode: StampMode = StampMode.OFF
    break_window_start: time | None = None
    break_window_end: time | None = None
    break_window_auto: bool = False
    break_window_resume: bool = False
    end_of_day_mode: StampMode = StampMode.OFF
    end_of_day_time: time | None = None
    end_of_day_on_target: bool = True
    ask_on_leave: bool = False
    ask_timeout: timedelta = timedelta(minutes=30)
    catch_up: bool = True

    # Location sent with stamps
    stamp_location: bool = False
    location_office: str | None = None
    location_home_office: str | None = None
    location_as_note: bool = False

    # Reminders
    reminder_time: time | None = None
    max_work: timedelta | None = timedelta(hours=10)
    forgotten_check_time: time | None = time(7, 0)
    snooze: timedelta = timedelta(minutes=30)
    end_of_day_reminder: bool = False
    end_of_day_grace: timedelta = timedelta(minutes=20)

    # Break assistant
    break_reminder_after: timedelta | None = timedelta(minutes=330)
    break_duration: timedelta = timedelta(minutes=30)
    break_end_reminder: bool = True
    auto_resume: bool = False
    break_check: bool = True
    break_after_6h: timedelta = timedelta(minutes=30)
    break_after_9h: timedelta = timedelta(minutes=45)
    break_default: timedelta = timedelta(minutes=30)
    break_question_timeout: timedelta = timedelta(minutes=60)

    @property
    def office_configured(self) -> bool:
        """Return whether any office source is configured."""

        return bool(
            (self.person and self.work_zones)
            or (self.wifi_sensor and self.wifi_ssids)
            or self.presence_entities
        )

    @property
    def home_office_configured(self) -> bool:
        """Return whether home office detection is configured."""

        return bool(
            self.person and (self.home_office_power_sensor or self.home_office_presence_sensors)
        )

    @property
    def presence_configured(self) -> bool:
        """Return whether any presence detection is configured."""

        return self.office_configured or self.home_office_configured

    @property
    def break_window(self) -> tuple[time, time] | None:
        """Return the break window, ``None`` if not configured."""

        if self.break_window_start is None or self.break_window_end is None:
            return None
        if self.break_window_start == self.break_window_end:
            return None
        return self.break_window_start, self.break_window_end

    def target_hours(self, day: date) -> timedelta | None:
        """Return the target working time of ``day``, ``None`` if there is none."""

        if WEEKDAYS[day.weekday()] not in self.workdays:
            return None
        return self.daily_hours if self.daily_hours > timedelta(0) else None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> AssistantConfig:
        """Parse options, falling back to defaults for missing or invalid values."""

        def get(key: str) -> Any:
            value = options.get(key)
            return DEFAULTS.get(key) if value is None else value

        def minutes(key: str) -> timedelta:
            return timedelta(minutes=max(0.0, _number(get(key), DEFAULTS[key])))

        def positive_minutes(key: str) -> timedelta:
            return minutes(key) or timedelta(minutes=DEFAULTS[key])

        def optional_hours(key: str) -> timedelta | None:
            hours = _number(get(key), DEFAULTS[key])
            return timedelta(hours=hours) if hours > 0 else None

        def optional_minutes(key: str) -> timedelta | None:
            value = minutes(key)
            return value if value > timedelta(0) else None

        def flag(key: str) -> bool:
            return bool(get(key))

        def entities(key: str) -> list[str]:
            return [e for e in _str_list(get(key)) if "." in e]

        def texts(key: str) -> list[str]:
            return [s.strip() for s in _str_list(get(key)) if s.strip()]

        return cls(
            workdays=[d for d in _str_list(get(CONF_WORKDAYS)) if d in WEEKDAYS],
            workday_entity=_entity(options.get(CONF_WORKDAY_ENTITY)),
            daily_hours=timedelta(hours=max(0.0, _number(get(CONF_DAILY_HOURS), 8.0))),
            window_start=_time(get(CONF_WINDOW_START)) or time(5, 0),
            window_end=_time(get(CONF_WINDOW_END)) or time(22, 0),
            absence_calendar=_entity(options.get(CONF_ABSENCE_CALENDAR)),
            absence_keywords=texts(CONF_ABSENCE_KEYWORDS),
            absence_sensor=_entity(options.get(CONF_ABSENCE_SENSOR)),
            notify_targets=[t.removeprefix("notify.") for t in _str_list(get(CONF_NOTIFY_TARGETS))],
            notify_confirmations=flag(CONF_NOTIFY_CONFIRMATIONS),
            notify_live=flag(CONF_NOTIFY_LIVE),
            live_icon_work=_text(options.get(CONF_LIVE_ICON_WORK)) or DEFAULT_LIVE_ICON_WORK,
            live_icon_break=_text(options.get(CONF_LIVE_ICON_BREAK)) or DEFAULT_LIVE_ICON_BREAK,
            person=_entity(options.get(CONF_PERSON)),
            work_zones=entities(CONF_WORK_ZONES),
            wifi_sensor=_entity(options.get(CONF_WIFI_SENSOR)),
            wifi_ssids=texts(CONF_WIFI_SSIDS),
            presence_entities=entities(CONF_PRESENCE_ENTITIES),
            office_combine=_enum(Combine, get(CONF_OFFICE_COMBINE), Combine.ANY),
            arrival_delay=minutes(CONF_ARRIVAL_DELAY),
            departure_delay=minutes(CONF_DEPARTURE_DELAY),
            home_office_power_sensor=_entity(options.get(CONF_HO_POWER_SENSOR)),
            home_office_power_threshold=_number(get(CONF_HO_POWER_THRESHOLD), 30.0),
            home_office_presence_sensors=entities(CONF_HO_PRESENCE_SENSORS),
            home_office_activity_delay=minutes(CONF_HO_ACTIVITY_DELAY),
            home_office_idle_timeout=positive_minutes(CONF_HO_IDLE_TIMEOUT),
            arrival_mode=_enum(StampMode, get(CONF_CLOCK_IN_MODE), StampMode.OFF),
            arrival_offset=minutes(CONF_ARRIVAL_OFFSET),
            departure_offset=minutes(CONF_DEPARTURE_OFFSET),
            break_mode=_enum(StampMode, get(CONF_BREAK_MODE), StampMode.OFF),
            break_window_start=_time(options.get(CONF_BREAK_WINDOW_START)),
            break_window_end=_time(options.get(CONF_BREAK_WINDOW_END)),
            break_window_auto=flag(CONF_BREAK_WINDOW_AUTO),
            break_window_resume=flag(CONF_BREAK_WINDOW_RESUME),
            end_of_day_mode=_enum(StampMode, get(CONF_END_OF_DAY_MODE), StampMode.OFF),
            end_of_day_time=_time(options.get(CONF_END_OF_DAY_TIME)),
            end_of_day_on_target=flag(CONF_END_OF_DAY_ON_TARGET),
            ask_on_leave=flag(CONF_ASK_ON_LEAVE),
            ask_timeout=positive_minutes(CONF_ASK_TIMEOUT),
            catch_up=flag(CONF_CATCH_UP),
            stamp_location=flag(CONF_STAMP_LOCATION),
            location_office=_text(options.get(CONF_LOCATION_OFFICE)),
            location_home_office=_text(options.get(CONF_LOCATION_HOME_OFFICE)),
            location_as_note=flag(CONF_LOCATION_AS_NOTE),
            reminder_time=_time(options.get(CONF_REMINDER_TIME)),
            max_work=optional_hours(CONF_MAX_WORK_HOURS),
            # An explicitly emptied field disables the check
            forgotten_check_time=_time(options[CONF_FORGOTTEN_CHECK_TIME])
            if CONF_FORGOTTEN_CHECK_TIME in options
            else _time(DEFAULTS[CONF_FORGOTTEN_CHECK_TIME]),
            snooze=positive_minutes(CONF_SNOOZE_MINUTES),
            end_of_day_reminder=flag(CONF_END_OF_DAY_REMINDER),
            end_of_day_grace=minutes(CONF_END_OF_DAY_GRACE),
            break_reminder_after=optional_minutes(CONF_BREAK_REMINDER_AFTER),
            break_duration=positive_minutes(CONF_BREAK_DURATION),
            break_end_reminder=flag(CONF_BREAK_END_REMINDER),
            auto_resume=flag(CONF_AUTO_RESUME),
            break_check=flag(CONF_BREAK_CHECK),
            break_after_6h=minutes(CONF_BREAK_AFTER_6H),
            break_after_9h=minutes(CONF_BREAK_AFTER_9H),
            break_default=minutes(CONF_BREAK_DEFAULT),
            break_question_timeout=positive_minutes(CONF_BREAK_QUESTION_TIMEOUT),
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


def _enum[E: StrEnum](kind: type[E], value: Any, default: E) -> E:
    try:
        return kind(value)
    except ValueError:
        return default


def _time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None
