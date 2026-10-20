"""Data update coordinators for the Crewmeister integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .absences import AbsenceEntry, async_absence_entries
from .api import (
    CrewmeisterAuthError,
    CrewmeisterClient,
    CrewmeisterError,
    CrewmeisterIdentity,
    Stamp,
    WorkStatus,
)
from .const import (
    ABSENCE_LOOKAHEAD,
    ABSENCE_MAX_DATA_AGE,
    ABSENCE_RETRY_INTERVAL,
    ABSENCE_UPDATE_INTERVAL,
)
from .helpers import StampDefaults, absence_states, update_interval_seconds
from .logic.config import AssistantConfig
from .logic.worktime import DaySummary, summarize, valid_stamps

if TYPE_CHECKING:
    from .assistant import CrewmeisterAssistant

_LOGGER = logging.getLogger(__name__)

type CrewmeisterConfigEntry = ConfigEntry[CrewmeisterRuntimeData]


@dataclass(slots=True)
class CrewmeisterRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: CrewmeisterClient
    status_coordinator: CrewmeisterStatusCoordinator
    absence_coordinator: CrewmeisterAbsenceCoordinator
    stamp_defaults: StampDefaults
    config: AssistantConfig
    assistant: CrewmeisterAssistant


@dataclass(frozen=True, slots=True)
class StatusData:
    """Recent stamps of the user, oldest first."""

    identity: CrewmeisterIdentity
    stamps: list[Stamp]

    @property
    def latest_stamp(self) -> Stamp | None:
        """Return the most recent stamp."""

        return self.stamps[-1] if self.stamps else None

    @property
    def status(self) -> WorkStatus:
        """Return the current work status."""

        return self.today().status

    def today(self) -> DaySummary:
        """Summarize work and breaks of the current day up to now."""

        now = dt_util.now()
        return summarize(self.stamps, now, dt_util.start_of_local_day(now))


class CrewmeisterStatusCoordinator(DataUpdateCoordinator[StatusData]):
    """Coordinator for the live stamp status."""

    config_entry: CrewmeisterConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CrewmeisterConfigEntry, client: CrewmeisterClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Crewmeister status",
            update_interval=timedelta(seconds=update_interval_seconds(entry.options)),
        )
        self.client = client

    async def _async_update_data(self) -> StatusData:
        try:
            identity = await self.client.async_get_identity()
            stamps = await self.client.async_get_recent_stamps(identity.user_id)
        except CrewmeisterAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CrewmeisterError as err:
            raise UpdateFailed(str(err)) from err
        return StatusData(identity=identity, stamps=valid_stamps(stamps))


class CrewmeisterAbsenceCoordinator(DataUpdateCoordinator[list[AbsenceEntry]]):
    """Coordinator for current and upcoming absences, sorted by start.

    Absences change rarely and are loaded months ahead, so a failed refresh keeps
    the last data (for up to ``ABSENCE_MAX_DATA_AGE``) and retries sooner instead
    of making the calendar and the absence sensors unavailable.
    """

    config_entry: CrewmeisterConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CrewmeisterConfigEntry, client: CrewmeisterClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Crewmeister absences",
            update_interval=ABSENCE_UPDATE_INTERVAL,
        )
        self.client = client
        self.last_success: datetime | None = None

    async def _async_update_data(self) -> list[AbsenceEntry]:
        try:
            entries = await self._async_fetch()
        except UpdateFailed as err:
            # Retry sooner, also if the very first refresh failed
            previous_interval = self.update_interval
            self.update_interval = ABSENCE_RETRY_INTERVAL
            if not self.data_is_current():
                raise
            if previous_interval != ABSENCE_RETRY_INTERVAL:
                _LOGGER.warning(
                    "Could not refresh Crewmeister absences, keeping the data from %s: %s",
                    dt_util.as_local(self.last_success).strftime("%Y-%m-%d %H:%M"),
                    err,
                )
            return self.data
        if self.update_interval != ABSENCE_UPDATE_INTERVAL:
            _LOGGER.info("Crewmeister absences are up to date again")
        self.update_interval = ABSENCE_UPDATE_INTERVAL
        self.last_success = dt_util.utcnow()
        return entries

    async def _async_fetch(self) -> list[AbsenceEntry]:
        today = dt_util.now().date()
        try:
            identity = await self.client.async_get_identity()
            absences = await self.client.async_get_absences(
                identity.user_id,
                today,
                today + ABSENCE_LOOKAHEAD,
                set(absence_states(self.config_entry.options)),
            )
        except CrewmeisterAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CrewmeisterError as err:
            raise UpdateFailed(str(err)) from err

        return await async_absence_entries(self.client, absences)

    def data_is_current(self) -> bool:
        """Return whether the data was loaded within ``ABSENCE_MAX_DATA_AGE``."""

        return (
            self.data is not None
            and self.last_success is not None
            and dt_util.utcnow() - self.last_success <= ABSENCE_MAX_DATA_AGE
        )

    def current(self) -> list[AbsenceEntry]:
        """Return the absences, or nothing once the data is too old to rely on.

        After a failed refresh the coordinator keeps its last data, so users that
        stay available (e.g. the workday sensor) must not use it indefinitely.
        """

        return (self.data or []) if self.data_is_current() else []

    def upcoming(self) -> list[AbsenceEntry]:
        """Return absences that have not ended yet."""

        now = dt_util.now()
        return [entry for entry in self.current() if entry.event.end_datetime_local > now]

    def active(self) -> AbsenceEntry | None:
        """Return the absence covering the current moment."""

        now = dt_util.now()
        for entry in self.current():
            if entry.event.start_datetime_local <= now < entry.event.end_datetime_local:
                return entry
        return None
