"""Client for interacting with the Crewmeister API."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, date, datetime, timedelta
import json
import logging
from typing import Any

import aiohttp

from .errors import (
    CrewmeisterAuthError,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterMissingIdentity,
)
from .models import Absence, CrewmeisterIdentity, Stamp, StampType

_LOGGER = logging.getLogger(__name__)

AUTH_ENDPOINT = "/api/v3/auth/user/"
STAMPS_ENDPOINT = "/api/v3/timetracking/stamps"
ABSENCES_ENDPOINT = "/api/v3/absencemanager/absences"
ABSENCE_TYPE_ENDPOINT = "/api/v3/absencemanager/absence-type-settings/{id}"
SET_BREAK_ENDPOINT = "/api/v3/timetracking/set-break-in-stamp-chain-tasks"

REQUEST_TIMEOUT = 30  # seconds
TOKEN_REFRESH_MARGIN = 300  # seconds before expiry
TOKEN_LIFETIME_WITHOUT_EXP = timedelta(minutes=30)


class CrewmeisterClient:
    """Client responsible for all Crewmeister API interaction."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
        *,
        identity: CrewmeisterIdentity | None = None,
        token_payload: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._identity = identity
        self._token: str | None = None
        self._token_payload = token_payload or {}
        self._token_expiration: datetime | None = None
        self._login_lock = asyncio.Lock()
        self._absence_types: dict[int, dict[str, Any]] = {}
        self._language = _normalize_language(language)

    @property
    def identity(self) -> CrewmeisterIdentity | None:
        """Return the cached identity."""

        return self._identity

    async def async_login(self) -> dict[str, Any]:
        """Authenticate, store a new JWT and return its decoded payload."""

        payload = {"username": self._username, "password": self._password}
        try:
            async with (
                asyncio.timeout(REQUEST_TIMEOUT),
                # Redirects could lead to http:// and expose the password
                self._session.post(
                    self._base_url + AUTH_ENDPOINT, json=payload, allow_redirects=False
                ) as response,
            ):
                if response.status in (400, 401, 403):
                    _LOGGER.debug(
                        "Authentication failed: status=%s body=%s",
                        response.status,
                        await _safe_read_body(response),
                    )
                    raise CrewmeisterAuthError("Authentication with Crewmeister API failed")
                if response.status != 200:
                    raise CrewmeisterConnectionError(
                        f"Crewmeister authentication returned {response.status}"
                    )
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CrewmeisterConnectionError("Cannot connect to Crewmeister API") from err

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise CrewmeisterAuthError("Crewmeister token missing in authentication response")

        self._token = token
        self._token_payload = decode_jwt_payload(token)
        # Without exp claim the token is reused for a while; a 401 still triggers a login
        self._token_expiration = _token_expiration(self._token_payload) or (
            datetime.now(UTC) + TOKEN_LIFETIME_WITHOUT_EXP
        )
        return self._token_payload

    async def _async_ensure_token(self, rejected_token: str | None = None) -> str:
        """Return a valid token, logging in if missing, expiring or rejected."""

        async with self._login_lock:
            if self._token is None or self._token == rejected_token or self._token_expires_soon():
                await self.async_login()
            assert self._token is not None
            return self._token

    def _token_expires_soon(self) -> bool:
        if self._token_expiration is None:
            return True
        remaining = (self._token_expiration - datetime.now(UTC)).total_seconds()
        return remaining < TOKEN_REFRESH_MARGIN

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform an authorized API request and return the decoded JSON body."""

        token = await self._async_ensure_token()
        status, body = await self._send(method, path, token, **kwargs)
        if status == 401:
            _LOGGER.debug("Token rejected by API, attempting re-authentication")
            token = await self._async_ensure_token(rejected_token=token)
            status, body = await self._send(method, path, token, **kwargs)

        if status == 401:
            raise CrewmeisterAuthError("Crewmeister API rejected the credentials")
        if 300 <= status < 400:
            # Redirects are not followed, the token must not leave the configured URL
            raise CrewmeisterConnectionError(f"Crewmeister API redirected ({status})")
        if status >= 400:
            _LOGGER.debug(
                "Crewmeister API request failed: method=%s path=%s status=%s body=%s",
                method,
                path,
                status,
                body,
            )
            detail = _extract_error_detail(body)
            message = f"Crewmeister API returned {status}"
            if detail:
                message = f"{message}: {detail}"
            if status >= 500:
                raise CrewmeisterConnectionError(message)
            raise CrewmeisterError(message)
        return body

    async def _send(self, method: str, path: str, token: str, **kwargs: Any) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self._language:
            headers["Accept-Language"] = self._language
        try:
            async with (
                asyncio.timeout(REQUEST_TIMEOUT),
                self._session.request(
                    method,
                    self._base_url + path,
                    headers=headers,
                    allow_redirects=False,
                    **kwargs,
                ) as response,
            ):
                return response.status, await _safe_read_body(response)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CrewmeisterConnectionError("Error communicating with Crewmeister API") from err

    async def async_get_identity(self) -> CrewmeisterIdentity:
        """Return or resolve the identity of the authenticated user."""

        if self._identity:
            return self._identity

        if not self._token_payload:
            await self._async_ensure_token()
        claims = _extract_identity_from_payload(self._token_payload)
        user_id = claims.get("user_id")
        crew_id = claims.get("crew_id")

        # No fallback to the latest accessible stamp: for supervisors and admins
        # that may be a colleague's stamp, and all stamps would be created for them
        if not user_id or not crew_id:
            raise CrewmeisterMissingIdentity("Unable to determine Crewmeister user identity")

        self._identity = CrewmeisterIdentity(
            user_id=int(user_id),
            crew_id=int(crew_id),
            email=claims.get("email"),
            full_name=claims.get("name"),
        )
        return self._identity

    async def async_get_latest_stamp(self, user_id: int | None = None) -> Stamp | None:
        """Return the most recent stamp, optionally limited to ``user_id``."""

        params: dict[str, Any] = {"pageSize": 1, "sort": "-timestamp"}
        if user_id:
            params["filter"] = f"userId=={user_id}"
        content = _page_content(await self._request("GET", STAMPS_ENDPOINT, params=params))
        return Stamp.from_api(content[0]) if content else None

    async def async_get_recent_stamps(self, user_id: int, count: int = 50) -> list[Stamp]:
        """Return the ``count`` most recent stamps of ``user_id``, newest first."""

        params: dict[str, Any] = {
            "pageSize": count,
            "sort": "-timestamp",
            "filter": f"userId=={user_id}",
        }
        content = _page_content(await self._request("GET", STAMPS_ENDPOINT, params=params))
        return [Stamp.from_api(item) for item in content]

    async def async_get_absences(
        self,
        user_id: int,
        start: date,
        end: date,
        states: set[str] | None = None,
    ) -> list[Absence]:
        """Fetch absences overlapping the given date range."""

        filters = [
            f"userId=={user_id}",
            f"from<='{end.isoformat()}'",
            f"to>='{start.isoformat()}'",
        ]
        if states:
            state_filter = ",".join(f"'{state}'" for state in sorted(states))
            filters.append(f"state=in=({state_filter})")
        params = {"pageSize": 200, "sort": "+from", "filter": ";".join(filters)}
        content = _page_content(await self._request("GET", ABSENCES_ENDPOINT, params=params))
        return [absence for item in content if (absence := Absence.from_api(item))]

    async def async_create_stamp(
        self,
        stamp_type: StampType,
        *,
        timestamp: datetime | None = None,
        note: str | None = None,
        location: str | None = None,
        time_account_id: int | None = None,
    ) -> Stamp:
        """Create a new stamp for the authenticated user."""

        identity = await self.async_get_identity()
        timestamp_utc = (timestamp or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)

        payload: dict[str, Any] = {
            "@type": "com.crewmeister/Stamp",
            "crewId": identity.crew_id,
            "userId": identity.user_id,
            "stampType": str(stamp_type),
            "timestamp": timestamp_utc.isoformat().replace("+00:00", "Z"),
        }
        if note:
            payload["note"] = note
        if location:
            payload["location"] = location
        if time_account_id is not None:
            payload["timeAccountId"] = time_account_id

        data = await self._request("POST", STAMPS_ENDPOINT, json=payload)
        # Synchronous writes answer with a SyncWriteResponse
        if isinstance(data, dict):
            resource = data.get("resourceAfterWrite")
            return Stamp.from_api(resource if isinstance(resource, dict) else data)
        return Stamp.from_api(payload)

    async def async_set_break(self, stamp_id: int, duration: timedelta) -> None:
        """Insert a break of ``duration`` into the stamp chain containing ``stamp_id``."""

        minutes = max(1, round(duration.total_seconds() / 60))
        payload = {
            "@type": "com.crewmeister/SetBreakInStampChainTask",
            "input": {
                "@type": "com.crewmeister/SetBreakInStampChainTaskInput",
                "duration": f"PT{minutes}M",
                "stampIdInStampChain": stamp_id,
            },
        }
        await self._request("POST", SET_BREAK_ENDPOINT, json=payload)

    async def async_get_absence_type_name(self, type_id: int) -> str | None:
        """Return the display name for an absence type."""

        info = self._absence_types.get(type_id)
        if info is None:
            try:
                data = await self._request("GET", ABSENCE_TYPE_ENDPOINT.format(id=type_id))
            except CrewmeisterError:
                _LOGGER.debug("Could not fetch absence type %s", type_id)
                return None
            if not isinstance(data, dict):
                return None
            self._absence_types[type_id] = info = data

        return (
            _extract_translated_name(info, self._language)
            or info.get("name")
            or info.get("displayName")
            or info.get("absenceTypeName")
        )


async def _safe_read_body(response: aiohttp.ClientResponse) -> Any:
    try:
        return await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        try:
            return await response.text()
        except aiohttp.ClientError:
            return None


def _page_content(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, list):
            return [item for item in content if isinstance(item, dict)]
    return []


def _token_expiration(payload: dict[str, Any]) -> datetime | None:
    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        return datetime.fromtimestamp(int(exp), UTC)
    except (TypeError, ValueError, OverflowError):
        _LOGGER.debug("Invalid exp claim in Crewmeister token: %s", exp)
        return None


def _extract_error_detail(body: Any) -> str | None:
    """Return a readable error detail from a failed API response."""

    if not body:
        return None
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return "; ".join(str(item) for item in body if item) or None
    if not isinstance(body, dict):
        return None

    for key in ("message", "error", "error_description", "detail", "title", "reason"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    errors = body.get("errors")
    if isinstance(errors, list):
        messages = [
            item if isinstance(item, str) else item.get("message")
            for item in errors
            if isinstance(item, (str, dict))
        ]
        joined = "; ".join(m for m in messages if isinstance(m, str) and m)
        if joined:
            return joined
    error_code = body.get("errorCode")
    return error_code if isinstance(error_code, str) else None


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload of a JWT without verification."""

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_identity_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract identity values from a JWT payload."""

    identity: dict[str, Any] = {}

    for key in ("userId", "user_id", "uid", "sub"):
        value = payload.get(key)
        if not value:
            continue
        if isinstance(value, str) and value.startswith("user:"):
            value = value.split(":", 1)[1]
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            identity["user_id"] = int(value)
        break

    for key in ("crewId", "crew_id", "cid", "crew"):
        value = payload.get(key)
        if not value:
            continue
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            identity["crew_id"] = int(value)
        break

    for key in ("email", "username", "upn"):
        if key in payload:
            identity["email"] = payload[key]
            break

    for key in ("name", "fullName", "displayName"):
        if key in payload:
            identity["name"] = payload[key]
            break

    return identity


def _normalize_language(language: str | None) -> str | None:
    """Return a language tag in the format expected by the API."""

    if not language:
        return None
    return language.replace("_", "-").strip() or None


def _extract_translated_name(data: dict[str, Any], language: str | None) -> str | None:
    """Best-effort extraction of a localized absence type name."""

    if not language:
        return None

    localized = data.get("displayNameLocalized") or data.get("nameLocalized")
    if isinstance(localized, str) and localized:
        return localized

    lang = language.lower()
    primary = lang.split("-", 1)[0]
    for key in ("translations", "nameTranslations"):
        translations = data.get(key)
        if not isinstance(translations, dict):
            continue
        for tag, value in translations.items():
            if not isinstance(value, str) or not value:
                continue
            tag_norm = str(tag).lower().replace("_", "-")
            if tag_norm == lang or tag_norm.split("-", 1)[0] == primary:
                return value
    return None
