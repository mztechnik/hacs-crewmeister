"""Tests for the Crewmeister API client."""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
import json
import re

import aiohttp
from aioresponses import aioresponses
import pytest

from custom_components.crewmeister.api import (
    CrewmeisterAuthError,
    CrewmeisterClient,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterMissingIdentity,
    StampType,
)
from custom_components.crewmeister.api.client import (
    ABSENCE_TYPE_ENDPOINT,
    ABSENCES_ENDPOINT,
    AUTH_ENDPOINT,
    SET_BREAK_ENDPOINT,
    STAMPS_ENDPOINT,
)

from .conftest import CREW_ID, IDENTITY, TOKEN_PAYLOAD, USER_ID, make_jwt

BASE = "https://api.example.com"
STAMPS_URL = re.compile(rf"^{re.escape(BASE + STAMPS_ENDPOINT)}(\?.*)?$")
ABSENCES_URL = re.compile(rf"^{re.escape(BASE + ABSENCES_ENDPOINT)}(\?.*)?$")


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def api() -> aioresponses:
    with aioresponses() as mocked:
        yield mocked


def _client(session: aiohttp.ClientSession, **kwargs) -> CrewmeisterClient:
    return CrewmeisterClient(session, BASE + "/", "max@example.com", "secret", **kwargs)


async def test_login_decodes_token(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})

    payload = await _client(session).async_login()

    assert payload["userId"] == USER_ID
    assert payload["crewId"] == CREW_ID


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_login_rejected(session, api, status) -> None:
    api.post(BASE + AUTH_ENDPOINT, status=status, payload={"message": "nope"})

    with pytest.raises(CrewmeisterAuthError):
        await _client(session).async_login()


async def test_login_server_error_is_not_auth_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, status=503)

    with pytest.raises(CrewmeisterConnectionError):
        await _client(session).async_login()


async def test_login_connection_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, exception=aiohttp.ClientConnectionError())

    with pytest.raises(CrewmeisterConnectionError):
        await _client(session).async_login()


async def test_identity_from_token(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})

    identity = await _client(session).async_get_identity()

    assert identity == IDENTITY


async def test_identity_does_not_use_other_users_stamps(session, api) -> None:
    # For supervisors the latest accessible stamp may belong to a colleague
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt({"sub": "abc"})})
    api.get(STAMPS_URL, payload={"content": [{"userId": 5, "crewId": 6}]})

    with pytest.raises(CrewmeisterMissingIdentity):
        await _client(session).async_get_identity()


async def test_identity_missing(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt({})})
    api.get(STAMPS_URL, payload={"content": []})

    with pytest.raises(CrewmeisterMissingIdentity):
        await _client(session).async_get_identity()


async def test_latest_stamp(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(
        STAMPS_URL,
        payload={
            "content": [
                {
                    "stampType": "START_BREAK",
                    "stampStatus": "OPEN",
                    "timestamp": "2026-10-19T10:00:00Z",
                    "chainStartStampId": "12",
                }
            ]
        },
    )

    stamp = await _client(session).async_get_latest_stamp(USER_ID)

    assert stamp is not None
    assert stamp.stamp_type == StampType.START_BREAK
    assert stamp.timestamp == datetime(2026, 10, 19, 10, tzinfo=UTC)
    assert stamp.chain_start_stamp_id == 12
    request = next(iter(api.requests.values()))
    assert request  # one GET performed


async def test_unauthorized_request_relogs_once(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, status=401)
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, payload={"content": []})

    assert await _client(session).async_get_latest_stamp() is None


async def test_unauthorized_twice_raises_auth_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)}, repeat=True)
    api.get(STAMPS_URL, status=401, repeat=True)

    with pytest.raises(CrewmeisterAuthError):
        await _client(session).async_get_latest_stamp()


async def test_token_reused_until_expiry(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, payload={"content": []}, repeat=True)
    client = _client(session)

    await client.async_get_latest_stamp()
    await client.async_get_latest_stamp()

    auth_calls = [key for key in api.requests if key[0] == "POST"]
    assert len(api.requests[auth_calls[0]]) == 1


async def test_expiring_token_is_refreshed(session, api) -> None:
    api.post(
        BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD, timedelta(seconds=60))}
    )
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, payload={"content": []}, repeat=True)
    client = _client(session)

    await client.async_get_latest_stamp()
    await client.async_get_latest_stamp()

    auth_calls = [key for key in api.requests if key[0] == "POST"]
    assert len(api.requests[auth_calls[0]]) == 2


async def test_error_detail_in_message(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, status=422, payload={"errors": [{"message": "bad filter"}]})

    with pytest.raises(CrewmeisterError, match="422: bad filter"):
        await _client(session).async_get_latest_stamp()


async def test_server_error_is_connection_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, status=502, body="Bad Gateway")

    with pytest.raises(CrewmeisterConnectionError):
        await _client(session).async_get_latest_stamp()


async def test_create_stamp_payload(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.post(
        BASE + STAMPS_ENDPOINT,
        payload={"resourceAfterWrite": {"stampType": "CLOCK_OUT", "stampStatus": "CLOSED"}},
    )

    stamp = await _client(session, identity=IDENTITY).async_create_stamp(
        StampType.CLOCK_OUT,
        timestamp=datetime(2026, 10, 19, 17, 5, 30, 123, tzinfo=UTC),
        note="Feierabend",
        time_account_id=3,
    )

    assert stamp.stamp_type == "CLOCK_OUT"
    (call,) = [
        calls[0]
        for (method, url), calls in api.requests.items()
        if method == "POST" and str(url).endswith(STAMPS_ENDPOINT)
    ]
    assert call.kwargs["json"] == {
        "@type": "com.crewmeister/Stamp",
        "crewId": CREW_ID,
        "userId": USER_ID,
        "stampType": "CLOCK_OUT",
        "timestamp": "2026-10-19T17:05:30Z",
        "note": "Feierabend",
        "timeAccountId": 3,
    }
    assert call.kwargs["headers"]["Authorization"].startswith("Bearer ")


async def test_absences(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(
        ABSENCES_URL,
        payload={
            "content": [
                {"from": "2026-10-20", "to": "2026-10-24", "absenceType": 7, "state": "APPROVED"},
                {"from": None, "to": "2026-10-24"},
            ]
        },
    )

    absences = await _client(session).async_get_absences(
        USER_ID, date(2026, 10, 19), date(2026, 12, 31), {"APPROVED", "PRE_APPROVED"}
    )

    assert len(absences) == 1
    assert absences[0].type_id == 7
    ((_, url),) = [key for key in api.requests if key[0] == "GET"]
    assert url.query["filter"] == (
        "userId==644;from<='2026-12-31';to>='2026-10-19';state=in=('APPROVED','PRE_APPROVED')"
    )


async def test_absence_type_name_localized_and_cached(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(
        BASE + ABSENCE_TYPE_ENDPOINT.format(id=7),
        payload={"name": "Vacation", "translations": {"de_DE": "Urlaub"}},
    )
    client = _client(session, language="de")

    assert await client.async_get_absence_type_name(7) == "Urlaub"
    assert await client.async_get_absence_type_name(7) == "Urlaub"


async def test_absence_type_name_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(BASE + ABSENCE_TYPE_ENDPOINT.format(id=7), status=404)

    assert await _client(session).async_get_absence_type_name(7) is None


async def test_recent_stamps(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(
        STAMPS_URL,
        payload={
            "content": [
                {"id": 2, "stampType": "CLOCK_OUT", "timestamp": "2026-10-19T16:00:00Z"},
                {"id": 1, "stampType": "START_WORK", "timestamp": "2026-10-19T08:00:00Z"},
            ]
        },
    )

    stamps = await _client(session).async_get_recent_stamps(USER_ID, 10)

    assert [s.id for s in stamps] == [2, 1]
    ((_, url),) = [key for key in api.requests if key[0] == "GET"]
    assert url.query["filter"] == "userId==644"
    assert url.query["sort"] == "-timestamp"
    assert url.query["pageSize"] == "10"


async def test_set_break(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.post(BASE + SET_BREAK_ENDPOINT, status=201, payload={})

    await _client(session).async_set_break(13, timedelta(minutes=20))

    (call,) = [
        calls[0]
        for (method, url), calls in api.requests.items()
        if method == "POST" and str(url).endswith(SET_BREAK_ENDPOINT)
    ]
    assert call.kwargs["json"] == {
        "@type": "com.crewmeister/SetBreakInStampChainTask",
        "input": {
            "@type": "com.crewmeister/SetBreakInStampChainTaskInput",
            "duration": "PT20M",
            "stampIdInStampChain": 13,
        },
    }


async def test_login_redirect_is_not_followed(session, api) -> None:
    # Following a redirect could send the password to an http:// URL
    api.post(
        BASE + AUTH_ENDPOINT,
        status=307,
        headers={"Location": "http://api.example.com" + AUTH_ENDPOINT},
    )

    with pytest.raises(CrewmeisterConnectionError):
        await _client(session).async_login()
    (call,) = next(iter(api.requests.values()))
    assert call.kwargs["allow_redirects"] is False


async def test_redirected_request_is_an_error(session, api) -> None:
    api.post(BASE + AUTH_ENDPOINT, payload={"token": make_jwt(TOKEN_PAYLOAD)})
    api.get(STAMPS_URL, status=302, headers={"Location": "http://elsewhere.example.com/"})

    with pytest.raises(CrewmeisterConnectionError):
        await _client(session).async_get_latest_stamp()
    (call,) = next(calls for (method, _), calls in api.requests.items() if method == "GET")
    assert call.kwargs["allow_redirects"] is False


async def test_token_without_exp_is_reused(session, api) -> None:
    def encode(part: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    token = f"{encode({'alg': 'none'})}.{encode(TOKEN_PAYLOAD)}.sig"
    api.post(BASE + AUTH_ENDPOINT, payload={"token": token}, repeat=True)
    api.get(STAMPS_URL, payload={"content": []}, repeat=True)
    client = _client(session)

    await client.async_get_latest_stamp()
    await client.async_get_latest_stamp()

    auth_calls = [key for key in api.requests if key[0] == "POST"]
    assert len(api.requests[auth_calls[0]]) == 1
