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
        status = self.coordinator.data.get("status") if isinstance(self.coordinator.data, dict) else None
        stamp_kwargs = self._derive_stamp_kwargs(stamp_type, status)

        if stamp_type in (STAMP_TYPE_START_BREAK, STAMP_TYPE_CLOCK_OUT) and "chain_start_stamp_id" not in stamp_kwargs:
            raise HomeAssistantError("Failed to trigger Crewmeister stamp: no active shift found")
        if stamp_type == STAMP_TYPE_START_WORK and status == "on_break" and "chain_start_stamp_id" not in stamp_kwargs:
            raise HomeAssistantError("Failed to trigger Crewmeister stamp: unable to resume break")

        try:
            await self._client.async_create_stamp(stamp_type, **stamp_kwargs)
        except CrewmeisterError as err:
            raise HomeAssistantError(f"Failed to trigger Crewmeister stamp: {err}") from err
        await self.coordinator.async_request_refresh()

    def _derive_stamp_kwargs(self, stamp_type: str, status: str | None) -> dict[str, object]:
        """Return payload parameters for the requested stamp type."""

        if not isinstance(self.coordinator.data, dict):
            return {}

        latest_stamp = self.coordinator.data.get("latest_stamp")
        if not isinstance(latest_stamp, dict):
            return {}

        chain_start: int | None = latest_stamp.get("chainStartStampId")
        allocation_date = latest_stamp.get("allocationDate")
        if not isinstance(chain_start, int):
            candidate = latest_stamp.get("id")
            if isinstance(candidate, int):
                chain_start = candidate

        include_chain = False
        if stamp_type == STAMP_TYPE_START_WORK:
            include_chain = status == "on_break"
        else:
            include_chain = True

        if include_chain and chain_start is not None:
            kwargs: dict[str, object] = {"chain_start_stamp_id": chain_start}
            if isinstance(allocation_date, str) and allocation_date:
                kwargs["allocation_date"] = allocation_date
            return kwargs

        return {}
