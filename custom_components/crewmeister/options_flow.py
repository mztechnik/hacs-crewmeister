"""Options flow of the Crewmeister integration.

A menu leads to one short form per topic. Within a form, related fields are
grouped in sections; fine tuning with good defaults is collapsed. The stored
options stay flat, so the section structure can change without migrating
existing entries.
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
    IconSelector,
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
    CONF_ABSENCE_CALENDAR,
    CONF_ABSENCE_KEYWORDS,
    CONF_ABSENCE_SENSOR,
    CONF_ABSENCE_STATES,
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
    CONF_STAMP_NOTE,
    CONF_STAMP_TIME_ACCOUNT_ID,
    CONF_UPDATE_INTERVAL,
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
from .logic.sources import Combine
from .logic.texts import text
from .logic.workday import WEEKDAYS

# Optional fields whose emptied value must be stored (None disables a default)
KEEP_EMPTY = {CONF_FORGOTTEN_CHECK_TIME}

MENU = ["schedule", "office", "home_office", "rules", "notifications", "breaks", "advanced"]
# Forms whose features only work with a notification device
NEEDS_NOTIFICATIONS = {"rules", "breaks"}


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


def _select(options: list[str], translation_key: str, *, multiple: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=multiple,
            mode=SelectSelectorMode.LIST,
            translation_key=translation_key,
        )
    )


def _mode() -> SelectSelector:
    return _select([m.value for m in StampMode], "stamp_mode")


def _texts() -> TextSelector:
    return TextSelector(TextSelectorConfig(multiple=True))


def _section(fields: dict[Any, Any], *, collapsed: bool = False) -> section:
    return section(vol.Schema(fields), {"collapsed": collapsed})


SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_WORKDAYS): _select(WEEKDAYS, "weekday", multiple=True),
        vol.Required(CONF_DAILY_HOURS): _hours(0, 16),
        vol.Optional(CONF_WORKDAY_ENTITY): _entity("binary_sensor"),
        vol.Required("absence"): _section(
            {
                vol.Optional(CONF_ABSENCE_CALENDAR): _entity("calendar"),
                vol.Optional(CONF_ABSENCE_KEYWORDS): _texts(),
                vol.Optional(CONF_ABSENCE_SENSOR): _entity(["binary_sensor", "input_boolean"]),
                vol.Required(CONF_ABSENCE_STATES): _select(
                    [state.lower() for state in ABSENCE_STATES], CONF_ABSENCE_STATES, multiple=True
                ),
            }
        ),
        vol.Required("window"): _section(
            {
                vol.Required(CONF_WINDOW_START): TimeSelector(),
                vol.Required(CONF_WINDOW_END): TimeSelector(),
            },
            collapsed=True,
        ),
    }
)

OFFICE_SCHEMA = vol.Schema(
    {
        vol.Required("detection"): _section(
            {
                vol.Optional(CONF_PERSON): _entity("person"),
                vol.Optional(CONF_WORK_ZONES): _entity("zone", multiple=True),
                vol.Optional(CONF_WIFI_SENSOR): _entity("sensor"),
                vol.Optional(CONF_WIFI_SSIDS): _texts(),
                vol.Optional(CONF_PRESENCE_ENTITIES): _entity(
                    ["binary_sensor", "input_boolean"], multiple=True
                ),
                vol.Required(CONF_OFFICE_COMBINE): _select(
                    [c.value for c in Combine], CONF_OFFICE_COMBINE
                ),
            }
        ),
        vol.Required("timing"): _section(
            {
                vol.Required(CONF_ARRIVAL_DELAY): _minutes(60),
                vol.Required(CONF_DEPARTURE_DELAY): _minutes(60),
            },
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
        vol.Required("timing"): _section(
            {
                vol.Required(CONF_HO_ACTIVITY_DELAY): _minutes(60),
                vol.Required(CONF_HO_IDLE_TIMEOUT): _minutes(240, 5),
            },
            collapsed=True,
        ),
    }
)

RULES_SCHEMA = vol.Schema(
    {
        vol.Required("arrival"): _section(
            {
                vol.Required(CONF_CLOCK_IN_MODE): _mode(),
                vol.Required(CONF_ARRIVAL_OFFSET): _minutes(60),
            }
        ),
        vol.Required("break_window"): _section(
            {
                vol.Required(CONF_BREAK_MODE): _mode(),
                vol.Optional(CONF_BREAK_WINDOW_START): TimeSelector(),
                vol.Optional(CONF_BREAK_WINDOW_END): TimeSelector(),
                vol.Required(CONF_BREAK_WINDOW_AUTO): BooleanSelector(),
                vol.Required(CONF_BREAK_WINDOW_RESUME): BooleanSelector(),
            }
        ),
        vol.Required("end_of_day"): _section(
            {
                vol.Required(CONF_END_OF_DAY_MODE): _mode(),
                vol.Optional(CONF_END_OF_DAY_TIME): TimeSelector(),
                vol.Required(CONF_END_OF_DAY_ON_TARGET): BooleanSelector(),
                vol.Required(CONF_DEPARTURE_OFFSET): _minutes(60),
                vol.Required(CONF_CATCH_UP): BooleanSelector(),
            }
        ),
        vol.Required("leave"): _section(
            {
                vol.Required(CONF_ASK_ON_LEAVE): BooleanSelector(),
                vol.Required(CONF_ASK_TIMEOUT): _minutes(240, 5),
            },
            collapsed=True,
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
            }
        ),
        vol.Required("break_check"): _section(
            {
                vol.Required(CONF_BREAK_CHECK): BooleanSelector(),
                vol.Required(CONF_BREAK_DEFAULT): _minutes(120, 5),
                vol.Required(CONF_BREAK_QUESTION_TIMEOUT): _minutes(720, 5),
            }
        ),
        vol.Required("end_of_day"): _section(
            {
                vol.Required(CONF_END_OF_DAY_REMINDER): BooleanSelector(),
                vol.Required(CONF_MAX_WORK_HOURS): _hours(0, 16),
                vol.Optional(CONF_REMINDER_TIME): TimeSelector(),
                vol.Optional(CONF_FORGOTTEN_CHECK_TIME): TimeSelector(),
            }
        ),
        vol.Required("fine_tuning"): _section(
            {
                vol.Required(CONF_END_OF_DAY_GRACE): _minutes(240, 5),
                vol.Required(CONF_SNOOZE_MINUTES): _minutes(240, 5),
                vol.Required(CONF_BREAK_AFTER_6H): _minutes(120, 5),
                vol.Required(CONF_BREAK_AFTER_9H): _minutes(120, 5),
            },
            collapsed=True,
        ),
    }
)

ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Required("location"): _section(
            {
                vol.Required(CONF_STAMP_LOCATION): BooleanSelector(),
                vol.Optional(CONF_LOCATION_OFFICE): TextSelector(),
                vol.Optional(CONF_LOCATION_HOME_OFFICE): TextSelector(),
                vol.Required(CONF_LOCATION_AS_NOTE): BooleanSelector(),
            }
        ),
        vol.Required(CONF_UPDATE_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_UPDATE_INTERVAL_SECONDS,
                max=MAX_UPDATE_INTERVAL_SECONDS,
                step=60,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_STAMP_NOTE): TextSelector(),
        vol.Optional(CONF_STAMP_TIME_ACCOUNT_ID): NumberSelector(
            NumberSelectorConfig(min=1, step=1, mode=NumberSelectorMode.BOX)
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


def _clean_schedule(values: dict[str, Any]) -> dict[str, Any]:
    cleaned = {k: _clean_number(v) for k, v in values.items()}
    cleaned[CONF_ABSENCE_STATES] = absence_states(values)
    return cleaned


def _clean_advanced(values: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_UPDATE_INTERVAL: update_interval_seconds(values),
        CONF_STAMP_NOTE: clean_note(values.get(CONF_STAMP_NOTE)),
        CONF_STAMP_TIME_ACCOUNT_ID: positive_int(values.get(CONF_STAMP_TIME_ACCOUNT_ID)),
        CONF_STAMP_LOCATION: bool(values.get(CONF_STAMP_LOCATION)),
        CONF_LOCATION_OFFICE: clean_note(values.get(CONF_LOCATION_OFFICE)),
        CONF_LOCATION_HOME_OFFICE: clean_note(values.get(CONF_LOCATION_HOME_OFFICE)),
        CONF_LOCATION_AS_NOTE: bool(values.get(CONF_LOCATION_AS_NOTE)),
    }


def _validate_office(values: dict[str, Any]) -> dict[str, str]:
    if values.get(CONF_WORK_ZONES) and not values.get(CONF_PERSON):
        return {"base": "zones_need_person"}
    if bool(values.get(CONF_WIFI_SENSOR)) != bool(values.get(CONF_WIFI_SSIDS)):
        return {"base": "wifi_incomplete"}
    return {}


def _validate_home_office(values: dict[str, Any]) -> dict[str, str]:
    sensors = values.get(CONF_HO_POWER_SENSOR) or values.get(CONF_HO_PRESENCE_SENSORS)
    if sensors and not values.get(CONF_PERSON):
        return {"base": "home_office_needs_person"}
    return {}


def _validate_rules(values: dict[str, Any]) -> dict[str, str]:
    start, end = values.get(CONF_BREAK_WINDOW_START), values.get(CONF_BREAK_WINDOW_END)
    if bool(start) != bool(end) or (start and start == end):
        return {"base": "break_window_incomplete"}
    if values.get(CONF_BREAK_MODE) not in (None, StampMode.OFF.value) and not start:
        return {"base": "break_window_missing"}
    if (
        values.get(CONF_END_OF_DAY_MODE) not in (None, StampMode.OFF.value)
        and not values.get(CONF_END_OF_DAY_TIME)
        and not values.get(CONF_END_OF_DAY_ON_TARGET)
    ):
        return {"base": "end_of_day_never"}
    return {}


class CrewmeisterOptionsFlow(OptionsFlowWithReload):
    """Menu with one form per topic; each form is saved on its own."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options menu."""

        return self.async_show_menu(step_id="init", menu_options=MENU)

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Working days, target working time and absences."""

        current = self.config_entry.options
        suggested = self._suggested(SCHEDULE_SCHEMA)
        suggested[CONF_ABSENCE_STATES] = [state.lower() for state in absence_states(current)]
        return self._form("schedule", SCHEDULE_SCHEMA, user_input, _clean_schedule, suggested)

    async def async_step_office(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Office detection via zone, Wi-Fi or other entities."""

        return self._form("office", OFFICE_SCHEMA, user_input, validate=_validate_office)

    async def async_step_home_office(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Home office detection via power draw and desk presence."""

        return self._form(
            "home_office", HOME_OFFICE_SCHEMA, user_input, validate=_validate_home_office
        )

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What is stamped when arriving and leaving."""

        return self._form("rules", RULES_SCHEMA, user_input, validate=_validate_rules)

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
                vol.Required("live_icons"): _section(
                    {
                        vol.Optional(CONF_LIVE_ICON_WORK): IconSelector(),
                        vol.Optional(CONF_LIVE_ICON_BREAK): IconSelector(),
                    },
                    collapsed=True,
                ),
            }
        )
        return self._form("notifications", schema, user_input)

    async def async_step_breaks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Break assistant and reminders."""

        return self._form("breaks", BREAKS_SCHEMA, user_input)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Location sent with stamps, polling interval and stamp defaults."""

        current = self.config_entry.options
        suggested = {
            CONF_UPDATE_INTERVAL: update_interval_seconds(current),
            CONF_STAMP_NOTE: clean_note(current.get(CONF_STAMP_NOTE)),
            CONF_STAMP_TIME_ACCOUNT_ID: positive_int(current.get(CONF_STAMP_TIME_ACCOUNT_ID)),
            CONF_STAMP_LOCATION: bool(current.get(CONF_STAMP_LOCATION, False)),
            CONF_LOCATION_OFFICE: current.get(CONF_LOCATION_OFFICE),
            CONF_LOCATION_HOME_OFFICE: current.get(CONF_LOCATION_HOME_OFFICE),
            CONF_LOCATION_AS_NOTE: bool(current.get(CONF_LOCATION_AS_NOTE, False)),
        }
        return self._form("advanced", ADVANCED_SCHEMA, user_input, _clean_advanced, suggested)

    def _suggested(self, schema: vol.Schema) -> dict[str, Any]:
        current = self.config_entry.options
        return {key: current.get(key, DEFAULTS.get(key)) for key in _fields(schema)}

    def _form(
        self,
        step_id: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
        clean: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        suggested: dict[str, Any] | None = None,
        *,
        validate: Callable[[dict[str, Any]], dict[str, str]] | None = None,
    ) -> ConfigFlowResult:
        """Show the form of ``step_id`` or merge its input into the options."""

        errors: dict[str, str] = {}
        if user_input is not None:
            values = _flatten(user_input, schema)
            errors = validate(values) if validate else {}
            if not errors:
                # Optional fields left empty are removed (feature off / default)
                values = (
                    clean(values) if clean else {k: _clean_number(v) for k, v in values.items()}
                )
                options = {
                    key: value
                    for key, value in {**self.config_entry.options, **values}.items()
                    if value not in (None, "", []) or key in KEEP_EMPTY
                }
                return self.async_create_entry(data=options)
            suggested = values

        if suggested is None:
            suggested = self._suggested(schema)
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, _nest(suggested, schema)),
            errors=errors,
            description_placeholders={"notify_hint": self._notify_hint(step_id)},
        )

    def _notify_hint(self, step_id: str) -> str:
        """Warn in forms whose features need a notification device."""

        if step_id not in NEEDS_NOTIFICATIONS or self.config_entry.options.get(CONF_NOTIFY_TARGETS):
            return ""
        return text(self.hass.config.language, "options_notify_hint")
