"""Constants for the Crewmeister integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "crewmeister"
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Config entry data
CONF_BASE_URL: Final = "base_url"
CONF_CREW_ID: Final = "crew_id"
CONF_USER_ID: Final = "user_id"
CONF_EMAIL: Final = "email"
CONF_FULL_NAME: Final = "full_name"
CONF_TOKEN_PAYLOAD: Final = "token_payload"

# Options
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_ABSENCE_STATES: Final = "absence_states"
CONF_STAMP_NOTE: Final = "stamp_note"
CONF_STAMP_TIME_ACCOUNT_ID: Final = "stamp_time_account_id"

# Options: working days
CONF_WORKDAYS: Final = "workdays"
CONF_WORKDAY_ENTITY: Final = "workday_entity"
CONF_DAILY_HOURS: Final = "daily_hours"
# Optional target hours per weekday: hours_mon ... hours_sun
CONF_WEEKDAY_HOURS_PREFIX: Final = "hours_"

# Options: notifications
CONF_NOTIFY_TARGETS: Final = "notify_targets"
CONF_NOTIFY_CONFIRMATIONS: Final = "notify_confirmations"
CONF_NOTIFY_STATUS: Final = "notify_status"
CONF_NOTIFY_LIVE: Final = "notify_live"

# Options: automatic stamping
CONF_PERSON: Final = "person"
CONF_WORK_ZONES: Final = "work_zones"
CONF_WIFI_SENSOR: Final = "wifi_sensor"
CONF_WIFI_SSIDS: Final = "wifi_ssids"
CONF_PRESENCE_ENTITIES: Final = "presence_entities"
CONF_NFC_TAGS: Final = "nfc_tags"
CONF_CLOCK_IN_MODE: Final = "clock_in_mode"
CONF_CLOCK_OUT_MODE: Final = "clock_out_mode"
CONF_ARRIVAL_DELAY: Final = "arrival_delay"
CONF_DEPARTURE_DELAY: Final = "departure_delay"
CONF_SHORT_LEAVE_BREAK: Final = "short_leave_break"
CONF_WINDOW_START: Final = "window_start"
CONF_WINDOW_END: Final = "window_end"
CONF_BACKDATE: Final = "backdate"
CONF_ONCE_PER_DAY: Final = "once_per_day"

# Options: home office
CONF_HO_POWER_SENSOR: Final = "home_office_power_sensor"
CONF_HO_POWER_THRESHOLD: Final = "home_office_power_threshold"
CONF_HO_PRESENCE_SENSORS: Final = "home_office_presence_sensors"
CONF_HO_CLOCK_IN_MODE: Final = "home_office_clock_in_mode"
CONF_HO_CLOCK_OUT_MODE: Final = "home_office_clock_out_mode"
CONF_HO_SHORT_BREAK: Final = "home_office_short_break"
CONF_HO_ACTIVITY_DELAY: Final = "home_office_activity_delay"
CONF_HO_IDLE_TIMEOUT: Final = "home_office_idle_timeout"
CONF_HO_WINDOW_START: Final = "home_office_window_start"
CONF_HO_WINDOW_END: Final = "home_office_window_end"

# Options: location sent with stamps
CONF_STAMP_LOCATION: Final = "stamp_location"
CONF_LOCATION_OFFICE: Final = "location_office"
CONF_LOCATION_HOME_OFFICE: Final = "location_home_office"

# Options: reminders
CONF_REMIND_ON_LEAVE: Final = "remind_on_leave"
CONF_REMINDER_TIME: Final = "reminder_time"
CONF_MAX_WORK_HOURS: Final = "max_work_hours"
CONF_FORGOTTEN_CHECK_TIME: Final = "forgotten_check_time"
CONF_SNOOZE_MINUTES: Final = "snooze_minutes"
CONF_END_OF_DAY_REMINDER: Final = "end_of_day_reminder"
CONF_END_OF_DAY_GRACE: Final = "end_of_day_grace"

# Options: break assistant
CONF_BREAK_REMINDER_AFTER: Final = "break_reminder_after"
CONF_BREAK_DURATION: Final = "break_duration"
CONF_BREAK_END_REMINDER: Final = "break_end_reminder"
CONF_AUTO_RESUME: Final = "auto_resume"
CONF_BREAK_CHECK: Final = "break_check"
CONF_BREAK_AFTER_6H: Final = "break_after_6h"
CONF_BREAK_AFTER_9H: Final = "break_after_9h"
CONF_LUNCH_BREAK_TIME: Final = "lunch_break_time"

DEFAULT_BASE_URL: Final = "https://api.crewmeister.com"

# Status polling interval bounds and default (seconds)
MIN_UPDATE_INTERVAL_SECONDS: Final = 300
MAX_UPDATE_INTERVAL_SECONDS: Final = 3600
DEFAULT_UPDATE_INTERVAL_SECONDS: Final = 1800

ABSENCE_UPDATE_INTERVAL: Final = timedelta(hours=1)
# After a failed refresh: retry sooner and keep the last data for this long
ABSENCE_RETRY_INTERVAL: Final = timedelta(minutes=10)
ABSENCE_MAX_DATA_AGE: Final = timedelta(hours=24)
ABSENCE_LOOKAHEAD: Final = timedelta(days=120)
ABSENCE_STATES: Final = ["APPROVED", "PRE_APPROVED", "REQUESTED", "REJECTED", "DRAFT", "REVOKED"]
DEFAULT_ABSENCE_STATES: Final = ["APPROVED", "PRE_APPROVED"]

SERVICE_CREATE_STAMP: Final = "create_stamp"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_NOTE: Final = "note"
ATTR_LOCATION: Final = "location"
ATTR_TIMESTAMP: Final = "timestamp"
ATTR_STAMP_TYPE: Final = "stamp_type"
ATTR_TIME_ACCOUNT_ID: Final = "time_account_id"

ATTRIBUTION: Final = "Data provided by Crewmeister"

# Prefix of actionable notification actions: crewmeister:<entry_id>:<action>[:<arg>]
NOTIFICATION_ACTION_PREFIX: Final = "crewmeister"
