"""Data coordinators for the Crewmeister integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CrewmeisterClient, CrewmeisterError, CrewmeisterStamp
from .const import (
    DEFAULT_UPDATE_INTERVAL,
    STAMP_TYPE_CLOCK_OUT,
    STAMP_TYPE_START_BREAK,
    STAMP_TYPE_START_WORK,
)

_LOGGER = logging.getLogger(__name__)


def _derive_status(stamp: CrewmeisterStamp | None) -> str:
    if not stamp:
        return "clocked_out"

    stamp_type = stamp.stamp_type
    status = stamp.status

    if status == "OPEN":
        if stamp_type == STAMP_TYPE_START_BREAK:
            return "on_break"
        if stamp_type == STAMP_TYPE_START_WORK:
            return "clocked_in"

    if stamp_type == STAMP_TYPE_CLOCK_OUT:
        return "clocked_out"

    # Fall back to previous behaviour
    return "clocked_out"


class CrewmeisterStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator responsible for the live stamp status."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: CrewmeisterClient,
        update_interval: timedelta | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Crewmeister status",
            update_interval=update_interval or DEFAULT_UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            identity = await self.client.async_get_identity()
            stamp = await self.client.async_get_latest_stamp(identity.user_id)
        except CrewmeisterError as err:
            raise UpdateFailed(str(err)) from err

        status = _derive_status(stamp)
        return {
            "identity": identity,
            "latest_stamp": stamp.raw if stamp else None,
            "status": status,
            "is_clocked_in": status == "clocked_in",
            "is_on_break": status == "on_break",
        }
