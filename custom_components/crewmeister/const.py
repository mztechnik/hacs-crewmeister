"""Constants for the Crewmeister integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "crewmeister"
PLATFORMS: list[str] = ["button", "sensor", "binary_sensor", "calendar"]

CONF_BASE_URL = "base_url"
CONF_CREW_ID = "crew_id"
CONF_USER_ID = "user_id"
CONF_TIMEZONE = "timezone"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_ABSENCE_STATES = "absence_states"
CONF_STAMP_NOTE = "stamp_note"
CONF_STAMP_TIME_ACCOUNT_ID = "stamp_time_account_id"

DEFAULT_BASE_URL = "https://api.crewmeister.com"
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=60)

SERVICE_CREATE_STAMP = "create_stamp"
SERVICE_FIELD_CONFIG_ENTRY_ID = "config_entry_id"
SERVICE_FIELD_NOTE = "note"
SERVICE_FIELD_LOCATION = "location"
SERVICE_FIELD_TIMESTAMP = "timestamp"
SERVICE_FIELD_STAMP_TYPE = "stamp_type"
SERVICE_FIELD_TIME_ACCOUNT_ID = "time_account_id"

STAMP_TYPE_START_WORK = "START_WORK"
STAMP_TYPE_CLOCK_OUT = "CLOCK_OUT"
STAMP_TYPE_START_BREAK = "START_BREAK"
STAMP_TYPES = [STAMP_TYPE_START_WORK, STAMP_TYPE_START_BREAK, STAMP_TYPE_CLOCK_OUT]

ABSENCE_APPROVED_STATES = {"APPROVED", "PRE_APPROVED"}
ABSENCE_DEFAULT_LOOKAHEAD_DAYS = 120

TOKEN_REFRESH_MARGIN = 300  # seconds before expiry
