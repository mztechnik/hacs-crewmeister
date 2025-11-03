"""Button entities for Crewmeister."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CrewmeisterClient, CrewmeisterError
from .const import (
    DOMAIN,
    STAMP_TYPE_CLOCK_OUT,
    STAMP_TYPE_START_BREAK,
    STAMP_TYPE_START_WORK,
)
from .coordinator import CrewmeisterStatusCoordinator


@dataclass(frozen=True, kw_only=True)
class CrewmeisterButtonEntityDescription(ButtonEntityDescription):
    """Describes Crewmeister button entity."""

    stamp_type: str


BUTTON_DESCRIPTIONS: tuple[CrewmeisterButtonEntityDescription, ...] = (
    CrewmeisterButtonEntityDescription(
        key="clock_in",
        translation_key="clock_in",
        icon="mdi:login",
        stamp_type=STAMP_TYPE_START_WORK,
    ),
    CrewmeisterButtonEntityDescription(
        key="start_break",
        translation_key="start_break",
        icon="mdi:coffee",
        stamp_type=STAMP_TYPE_START_BREAK,
    ),
    CrewmeisterButtonEntityDescription(
        key="clock_out",
        translation_key="clock_out",
        icon="mdi:logout",
        stamp_type=STAMP_TYPE_CLOCK_OUT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crewmeister button entities."""

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: CrewmeisterStatusCoordinator = runtime_data["coordinator"]
    client: CrewmeisterClient = runtime_data["client"]

    entities = [
        CrewmeisterStampButton(coordinator, client, entry.entry_id, description)
        for description in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)


class CrewmeisterStampButton(CoordinatorEntity[CrewmeisterStatusCoordinator], ButtonEntity):
    """Representation of a Crewmeister stamp button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CrewmeisterStatusCoordinator,
        client: CrewmeisterClient,
        entry_id: str,
        description: CrewmeisterButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._client = client
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo | None:
        identity = self.coordinator.data.get("identity")
        if identity is None:
            return None
        name = identity.full_name or identity.email or "Crewmeister"
        return DeviceInfo(
            identifiers={(DOMAIN, str(identity.user_id))},
            manufacturer="Crewmeister",
            name=name,
        )

    async def async_press(self) -> None:
        stamp_type = self.entity_description.stamp_type
        status = (
            self.coordinator.data.get("status")
            if isinstance(self.coordinator.data, dict)
            else None
        )

        self._ensure_valid_transition(stamp_type, status)
        stamp_kwargs = self._derive_stamp_kwargs(stamp_type, status)

        try:
            await self._client.async_create_stamp(stamp_type, **stamp_kwargs)
        except CrewmeisterError as err:
            raise HomeAssistantError(
                f"Failed to trigger Crewmeister stamp: {err}"
            ) from err

        await self.coordinator.async_request_refresh()

    def _ensure_valid_transition(self, stamp_type: str, status: str | None) -> None:
        """Validate that the requested transition is allowed."""

        if status is None:
            return

        if stamp_type == STAMP_TYPE_START_WORK:
            if status == "clocked_in":
                raise HomeAssistantError(
                    "Failed to trigger Crewmeister stamp: already clocked in"
                )
        elif stamp_type == STAMP_TYPE_START_BREAK:
            if status != "clocked_in":
                raise HomeAssistantError(
                    "Failed to trigger Crewmeister stamp: no active shift to pause"
                )
        elif stamp_type == STAMP_TYPE_CLOCK_OUT:
            if status not in {"clocked_in", "on_break"}:
                raise HomeAssistantError(
                    "Failed to trigger Crewmeister stamp: no active shift to clock out from"
                )

    def _prepare_stamp_kwargs(
        self, stamp_type: str, status: str | None
    ) -> dict[str, object]:
        """Build the payload for a new stamp based on the latest coordinator data."""

        data = self.coordinator.data if isinstance(self.coordinator.data, dict) else None
        latest_stamp = data.get("latest_stamp") if isinstance(data, dict) else None
        latest_stamp = latest_stamp if isinstance(latest_stamp, dict) else None

        chain_start = self._extract_chain_start(latest_stamp)
        allocation_date = latest_stamp.get("allocationDate") if latest_stamp else None

        include_chain = False
        if stamp_type == STAMP_TYPE_START_WORK:
            include_chain = status == "on_break"
        elif stamp_type in (STAMP_TYPE_START_BREAK, STAMP_TYPE_CLOCK_OUT):
            include_chain = True

        kwargs: dict[str, object] = {}
        if include_chain and chain_start is not None:
            kwargs["chain_start_stamp_id"] = chain_start
            if isinstance(allocation_date, str) and allocation_date:
                kwargs["allocation_date"] = allocation_date
        elif include_chain:
            # If we cannot determine the chain start locally we let the API
            # resolve the correct relationship instead of blocking the request.
            # This mirrors the behaviour prior to the refactor and avoids
            # breaking flows when the coordinator snapshot is stale.
            return {}

        return kwargs

    def _derive_stamp_kwargs(
        self,
        stamp_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, object]:
        """Return payload parameters derived from the latest stamp.

        ``stamp_type`` and ``status`` are optional so legacy calls that do not pass
        arguments continue to work. When omitted we pull the data from the entity
        description and coordinator snapshot respectively.
        """

        resolved_stamp_type = stamp_type or self.entity_description.stamp_type
        resolved_status = status
        if resolved_status is None and isinstance(self.coordinator.data, dict):
            resolved_status = self.coordinator.data.get("status")

        return self._prepare_stamp_kwargs(resolved_stamp_type, resolved_status)

    @staticmethod
    def _extract_chain_start(latest_stamp: dict[str, object] | None) -> int | None:
        if not latest_stamp:
            return None

        raw_value = latest_stamp.get("chainStartStampId")
        if raw_value is None:
            raw_value = latest_stamp.get("chain_start_stamp_id")  # defensive

        value = CrewmeisterStampButton._coerce_int(raw_value)
        if value is not None:
            return value

        # Some API responses omit ``chainStartStampId`` on the first stamp of a chain
        # but include the ``id`` of that stamp. Falling back to the ``id`` ensures we
        # can continue the chain while respecting the documented constraint that the
        # start identifier must remain stable across follow-up stamps.
        return CrewmeisterStampButton._coerce_int(latest_stamp.get("id"))

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None
