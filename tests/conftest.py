"""Shared fixtures for Crewmeister tests."""

from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.crewmeister.api import (
    Absence,
    CrewmeisterIdentity,
    Stamp,
)
from custom_components.crewmeister.const import (
    CONF_BASE_URL,
    CONF_CREW_ID,
    CONF_EMAIL,
    CONF_FULL_NAME,
    CONF_TOKEN_PAYLOAD,
    CONF_USER_ID,
    DEFAULT_BASE_URL,
    DOMAIN,
)

USER_ID = 644
CREW_ID = 352
IDENTITY = CrewmeisterIdentity(
    user_id=USER_ID, crew_id=CREW_ID, email="max@example.com", full_name="Max Muster"
)
TOKEN_PAYLOAD = {
    "userId": USER_ID,
    "crewId": CREW_ID,
    "email": "max@example.com",
    "name": "Max Muster",
}

ENTRY_DATA = {
    CONF_BASE_URL: DEFAULT_BASE_URL,
    "username": "max@example.com",
    "password": "secret",
    CONF_USER_ID: USER_ID,
    CONF_CREW_ID: CREW_ID,
    CONF_EMAIL: "max@example.com",
    CONF_FULL_NAME: "Max Muster",
    CONF_TOKEN_PAYLOAD: TOKEN_PAYLOAD,
}


def make_jwt(payload: dict[str, Any], expires_in: timedelta = timedelta(hours=1)) -> str:
    """Return an unsigned JWT with ``payload`` and an ``exp`` claim."""

    claims = {**payload, "exp": int((datetime.now(UTC) + expires_in).timestamp())}

    def encode(part: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode(claims)}.sig"


def make_stamp(stamp_type: str = "START_WORK", status: str = "OPEN", **extra: Any) -> Stamp:
    """Return a stamp as the API would deliver it."""

    return Stamp.from_api(
        {
            "id": 1,
            "userId": USER_ID,
            "crewId": CREW_ID,
            "stampType": stamp_type,
            "stampStatus": status,
            "timestamp": "2026-10-19T06:30:00Z",
            **extra,
        }
    )


def make_absence(start: str, end: str, **extra: Any) -> Absence:
    """Return an absence as the API would deliver it."""

    absence = Absence.from_api(
        {"from": start, "to": end, "absenceType": 7, "state": "APPROVED", **extra}
    )
    assert absence is not None
    return absence


# Monday, 2026-10-19 10:00 in the test time zone (US/Pacific)
NOW = datetime(2026, 10, 19, 17, 0, tzinfo=UTC)


class FakeBackend:
    """In-memory Crewmeister stamps behaving like the API."""

    def __init__(self) -> None:
        self.stamps: list[Stamp] = []
        self.breaks: list[tuple[int, timedelta]] = []
        self._next_id = 100

    def add(self, stamp_type: str, at: datetime) -> Stamp:
        """Append a stamp; the previous chain stamp gets closed."""

        self.stamps = [Stamp.from_api({**s.raw, "stampStatus": "CLOSED"}) for s in self.stamps]
        self._next_id += 1
        stamp = Stamp.from_api(
            {
                "id": self._next_id,
                "userId": USER_ID,
                "crewId": CREW_ID,
                "stampType": stamp_type,
                "stampStatus": "CLOSED" if stamp_type == "CLOCK_OUT" else "OPEN",
                "timestamp": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        self.stamps.append(stamp)
        self.stamps.sort(key=lambda s: s.timestamp)
        return stamp

    async def recent(self, user_id: int, count: int = 50) -> list[Stamp]:
        return list(reversed(self.stamps))[:count]

    async def latest(self, user_id: int | None = None) -> Stamp | None:
        return self.stamps[-1] if self.stamps else None

    async def create(
        self, stamp_type: str, *, timestamp: datetime | None = None, **_: Any
    ) -> Stamp:
        return self.add(str(stamp_type), timestamp or dt_util.utcnow())

    async def set_break(self, stamp_id: int, duration: timedelta) -> None:
        self.breaks.append((stamp_id, duration))


@pytest.fixture(autouse=True)
def frozen_now(freezer) -> None:
    """Run every test at a fixed point in time."""

    freezer.move_to(NOW)


@pytest.fixture
def backend() -> FakeBackend:
    """Return the fake backend, clocked in at 08:00 local time."""

    backend = FakeBackend()
    backend.add("START_WORK", NOW - timedelta(hours=2))
    return backend


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration in all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a Crewmeister config entry."""

    return MockConfigEntry(
        domain=DOMAIN, title="Max Muster", unique_id=str(USER_ID), data=dict(ENTRY_DATA)
    )


@pytest.fixture
def mock_client(backend: FakeBackend) -> Generator[AsyncMock]:
    """Patch the API client used by setup and config flow."""

    with (
        patch("custom_components.crewmeister.CrewmeisterClient", autospec=True) as client_cls,
        patch("custom_components.crewmeister.config_flow.CrewmeisterClient", new=client_cls),
    ):
        client = client_cls.return_value
        client.async_login.return_value = TOKEN_PAYLOAD
        client.async_get_identity.return_value = IDENTITY
        client.async_get_latest_stamp.side_effect = backend.latest
        client.async_get_recent_stamps.side_effect = backend.recent
        client.async_create_stamp.side_effect = backend.create
        client.async_set_break.side_effect = backend.set_break
        client.async_get_absences.return_value = []
        client.async_get_absence_type_name.return_value = "Urlaub"
        yield client
