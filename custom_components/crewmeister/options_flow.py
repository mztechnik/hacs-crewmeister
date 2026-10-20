"""Options flow of the Crewmeister integration.

A menu leads to one form per topic. Within a form, related fields are grouped in
sections; rarely needed fine tuning is collapsed. The stored options stay flat,
so the section structure can change without migrating existing entries.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)
import voluptuous as vol

from .const import (
    ABSENCE_STATES,
    CONF_ABSENCE_STATES,
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
    CONF_STAMP_NOTE,
    CONF_STAMP_TIME_ACCOUNT_ID,
    CONF_UPDATE_INTERVAL,
    CONF_WEEKDAY_HOURS_PREFIX,
    CONF_WIFI_SENSOR,
    CONF_WIFI_SSIDS,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    CONF_WORK_ZONES,
    CONF_WORKDAY_ENTITY,
    CONF_WORKDAYS,
    MAX_UPDATE_INTERVAL_SECONDS,
    MIN_UPDATE_INTERVAL_SECONDS,
)
from .helpers import absence_states, clean_note, positive_int, update_interval_seconds
from .logic.config import DEFAULTS, StampMode
from .logic.texts import text
from .logic.workday import WEEKDAYS

# Optional fields whose emptied value must be stored (None disables a default)
KEEP_EMPTY = {CONF_FORGOTTEN_CHECK_TIME}

MENU = [
    "schedule",
    "notifications",
    "auto_stamp",
    "home_office",
    "reminders",
    "breaks",
    "advanced",
]
# Forms whose features only work with a notification device
NEEDS_NOTIFICATIONS = {"auto_stamp", "home_office", "reminders", "breaks"}


def _minutes(maximum: int, step: int = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=maximum, step=step, unit_of_measurement="min", mode=NumberSelectorMode.BOX
        )
    )


def _hours(minimum: float, maximum: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.25,
            unit_of_measurement="h",
            mode=NumberSelectorMode.BOX,
        )
    )


def _entity(domain: str | list[str], *, multiple: bool = False) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=multiple))


def _mode() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[m.value for m in StampMode],
            mode=SelectSelectorMode.LIST,
            translation_key="stamp_mode",
        )
    )


def _section(fields: dict[Any, Any], *, collapsed: bool = False) -> section:
    return section(vol.Schema(fields), {"collapsed": collapsed})


SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_WORKDAYS): SelectSelector(
            SelectSelectorConfig(
                options=WEEKDAYS,
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key="weekday",
            )
        ),
        vol.Required(CONF_DAILY_HOURS): _hours(1, 16),
        vol.Optional(CONF_WORKDAY_ENTITY): _entity("binary_sensor"),
        vol.Required("weekday_hours"): _section(
            {vol.Optional(f"{CONF_WEEKDAY_HOURS_PREFIX}{day}"): _hours(0, 16) for day in WEEKDAYS},
            collapsed=True,
        ),
    }
)

AUTO_STAMP_SCHEMA = vol.Schema(
    {
        vol.Required("detection"): _section(
            {
                vol.Optional(CONF_PERSON): _entity("person"),
                vol.Optional(CONF_WORK_ZONES): _entity("zone", multiple=True),
                vol.Optional(CONF_WIFI_SENSOR): _entity("sensor"),
                vol.Optional(CONF_WIFI_SSIDS): TextSelector(TextSelectorConfig(multiple=True)),
                vol.Optional(CONF_PRESENCE_ENTITIES): _entity(
                    ["binary_sensor", "input_boolean"], multiple=True
                ),
            }
        ),
        vol.Required("behaviour"): _section(
            {
                vol.Required(CONF_CLOCK_IN_MODE): _mode(),
                vol.Required(CONF_CLOCK_OUT_MODE): _mode(),
                vol.Required(CONF_BACKDATE): BooleanSelector(),
                vol.Required(CONF_SHORT_LEAVE_BREAK): _minutes(180, 5),
            }
        ),
        vol.Required("timing"): _section(
            {
                vol.Required(CONF_ARRIVAL_DELAY): _minutes(60),
                vol.Required(CONF_DEPARTURE_DELAY): _minutes(60),
                vol.Required(CONF_WINDOW_START): TimeSelector(),
                vol.Required(CONF_WINDOW_END): TimeSelector(),
                vol.Required(CONF_ONCE_PER_DAY): BooleanSelector(),
            },
            collapsed=True,
        ),
        vol.Required("nfc"): _section(
            {vol.Optional(CONF_NFC_TAGS): TextSelector(TextSelectorConfig(multiple=True))},
            collapsed=True,
        ),
    }
)

HOME_OFFICE_SCHEMA = vol.Schema(
    {
        vol.Required("detection"): _section(
            {
                vol.Optional(CONF_PERSON): _entity("person"),
                vol.Optional(CONF_HO_POWER_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(CONF_HO_POWER_THRESHOLD): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=1000,
                        step=1,
                        unit_of_measurement="W",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_HO_PRESENCE_SENSORS): _entity("binary_sensor", multiple=True),
            }
        ),
        vol.Required("behaviour"): _section(
            {
                vol.Required(CONF_HO_CLOCK_IN_MODE): _mode(),
                vol.Required(CONF_HO_CLOCK_OUT_MODE): _mode(),
                vol.Required(CONF_HO_SHORT_BREAK): _minutes(240, 5),
            }
        ),
        vol.Required("timing"): _section(
            {
                vol.Required(CONF_HO_ACTIVITY_DELAY): _minutes(60),
                vol.Required(CONF_HO_IDLE_TIMEOUT): _minutes(240, 5),
                vol.Required(CONF_HO_WINDOW_START): TimeSelector(),
                vol.Required(CONF_HO_WINDOW_END): TimeSelector(),
            },
            collapsed=True,
        ),
    }
)

REMINDERS_SCHEMA = vol.Schema(
    {
        vol.Required("end_of_day"): _section(
            {
                vol.Required(CONF_END_OF_DAY_REMINDER): BooleanSelector(),
                vol.Required(CONF_END_OF_DAY_GRACE): _minutes(240, 5),
                vol.Required(CONF_MAX_WORK_HOURS): _hours(0, 16),
            }
        ),
        vol.Required("still_clocked_in"): _section(
            {
                vol.Required(CONF_REMIND_ON_LEAVE): BooleanSelector(),
                vol.Optional(CONF_REMINDER_TIME): TimeSelector(),
                vol.Optional(CONF_FORGOTTEN_CHECK_TIME): TimeSelector(),
                vol.Required(CONF_SNOOZE_MINUTES): _minutes(240, 5),
            }
        ),
    }
)

BREAKS_SCHEMA = vol.Schema(
    {
        vol.Required("during_work"): _section(
            {
                vol.Required(CONF_BREAK_REMINDER_AFTER): _minutes(720, 15),
                vol.Required(CONF_BREAK_DURATION): _minutes(180, 5),
                vol.Required(CONF_BREAK_END_REMINDER): BooleanSelector(),
                vol.Required(CONF_AUTO_RESUME): BooleanSelector(),
                vol.Optional(CONF_LUNCH_BREAK_TIME): TimeSelector(),
            }
        ),
        vol.Required("break_check"): _section(
            {
                vol.Required(CONF_BREAK_CHECK): BooleanSelector(),
                vol.Required(CONF_BREAK_AFTER_6H): _minutes(120, 5),
                vol.Required(CONF_BREAK_AFTER_9H): _minutes(120, 5),
            },
            collapsed=True,
        ),
    }
)

ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UPDATE_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_UPDATE_INTERVAL_SECONDS,
                max=MAX_UPDATE_INTERVAL_SECONDS,
                step=60,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_ABSENCE_STATES): SelectSelector(
            SelectSelectorConfig(
                options=ABSENCE_STATES,
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key=CONF_ABSENCE_STATES,
            )
        ),
        vol.Optional(CONF_STAMP_NOTE): TextSelector(),
        vol.Optional(CONF_STAMP_TIME_ACCOUNT_ID): NumberSelector(
            NumberSelectorConfig(min=1, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required("location"): _section(
            {
                vol.Required(CONF_STAMP_LOCATION): BooleanSelector(),
                vol.Optional(CONF_LOCATION_OFFICE): TextSelector(),
                vol.Optional(CONF_LOCATION_HOME_OFFICE): TextSelector(),
            },
            collapsed=True,
        ),
    }
)


def _fields(schema: vol.Schema) -> dict[str, str | None]:
    """Map every field key to the section containing it (``None`` = top level)."""

    fields: dict[str, str | None] = {}
    for key, value in schema.schema.items():
        if isinstance(value, section):
            fields.update({str(inner): str(key) for inner in value.schema.schema})
        else:
            fields[str(key)] = None
    return fields


def _flatten(user_input: dict[str, Any], schema: vol.Schema) -> dict[str, Any]:
    """Return the submitted values of all fields, sections resolved."""

    values: dict[str, Any] = {}
    for key, section_key in _fields(schema).items():
        source = user_input.get(section_key, {}) if section_key else user_input
        values[key] = source.get(key)
    return values


def _nest(values: dict[str, Any], schema: vol.Schema) -> dict[str, Any]:
    """Arrange flat ``values`` like the (sectioned) form expects them."""

    nested: dict[str, Any] = {}
    for key, section_key in _fields(schema).items():
        if values.get(key) is None:
            continue
        target = nested.setdefault(section_key, {}) if section_key else nested
        target[key] = values[key]
    return nested


def _clean_number(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _clean_advanced(values: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_UPDATE_INTERVAL: update_interval_seconds(values),
        CONF_ABSENCE_STATES: absence_states(values),
        CONF_STAMP_NOTE: clean_note(values.get(CONF_STAMP_NOTE)),
        CONF_STAMP_TIME_ACCOUNT_ID: positive_int(values.get(CONF_STAMP_TIME_ACCOUNT_ID)),
        CONF_STAMP_LOCATION: bool(values.get(CONF_STAMP_LOCATION)),
        CONF_LOCATION_OFFICE: clean_note(values.get(CONF_LOCATION_OFFICE)),
        CONF_LOCATION_HOME_OFFICE: clean_note(values.get(CONF_LOCATION_HOME_OFFICE)),
    }


class CrewmeisterOptionsFlow(OptionsFlowWithReload):
    """Menu with one form per topic; each form is saved on its own."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options menu."""

        return self.async_show_menu(step_id="init", menu_options=MENU)

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Working days and target working time."""

        return self._form("schedule", SCHEDULE_SCHEMA, user_input)

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Companion App devices, confirmations and live display."""

        services = sorted(
            service
            for service in self.hass.services.async_services_for_domain("notify")
            if service.startswith("mobile_app_")
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFY_TARGETS): SelectSelector(
                    SelectSelectorConfig(
                        options=services,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_NOTIFY_CONFIRMATIONS): BooleanSelector(),
                vol.Required(CONF_NOTIFY_LIVE): BooleanSelector(),
                vol.Required(CONF_NOTIFY_STATUS): BooleanSelector(),
            }
        )
        return self._form("notifications", schema, user_input)

    async def async_step_auto_stamp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Presence detection and how arrivals and departures are handled."""

        return self._form("auto_stamp", AUTO_STAMP_SCHEMA, user_input)

    async def async_step_home_office(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Home office detection via power draw and desk presence."""

        return self._form("home_office", HOME_OFFICE_SCHEMA, user_input)

    async def async_step_reminders(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """End of day and clock out reminders."""

        return self._form("reminders", REMINDERS_SCHEMA, user_input)

    async def async_step_breaks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Break assistant."""

        return self._form("breaks", BREAKS_SCHEMA, user_input)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Polling interval, absence filter and stamp defaults."""

        current = self.config_entry.options
        suggested = {
            CONF_UPDATE_INTERVAL: update_interval_seconds(current),
            CONF_ABSENCE_STATES: absence_states(current),
            CONF_STAMP_NOTE: clean_note(current.get(CONF_STAMP_NOTE)),
            CONF_STAMP_TIME_ACCOUNT_ID: positive_int(current.get(CONF_STAMP_TIME_ACCOUNT_ID)),
            CONF_STAMP_LOCATION: bool(current.get(CONF_STAMP_LOCATION, False)),
            CONF_LOCATION_OFFICE: current.get(CONF_LOCATION_OFFICE),
            CONF_LOCATION_HOME_OFFICE: current.get(CONF_LOCATION_HOME_OFFICE),
        }
        return self._form("advanced", ADVANCED_SCHEMA, user_input, _clean_advanced, suggested)

    def _form(
        self,
        step_id: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
        clean: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        suggested: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the form of ``step_id`` or merge its input into the options."""

        if user_input is not None:
            values = _flatten(user_input, schema)
            # Optional fields left empty are removed (feature off / default)
            values = clean(values) if clean else {k: _clean_number(v) for k, v in values.items()}
            options = {
                key: value
                for key, value in {**self.config_entry.options, **values}.items()
                if value not in (None, "", []) or key in KEEP_EMPTY
            }
            return self.async_create_entry(data=options)

        if suggested is None:
            current = self.config_entry.options
            suggested = {key: current.get(key, DEFAULTS.get(key)) for key in _fields(schema)}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, _nest(suggested, schema)),
            description_placeholders={"notify_hint": self._notify_hint(step_id)},
        )

    def _notify_hint(self, step_id: str) -> str:
        """Warn in forms whose features need a notification device."""

        if step_id not in NEEDS_NOTIFICATIONS or self.config_entry.options.get(CONF_NOTIFY_TARGETS):
            return ""
        return text(self.hass.config.language, "options_notify_hint")
