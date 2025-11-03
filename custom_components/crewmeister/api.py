"""Client for interacting with the Crewmeister API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import logging
from typing import Any

import aiohttp
import async_timeout

from .const import (
    CONF_CREW_ID,
    CONF_USER_ID,
    STAMP_TYPES,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

AUTH_ENDPOINT = "/api/v3/auth/user/"
STAMPS_ENDPOINT = "/api/v3/timetracking/stamps"
ABSENCES_ENDPOINT = "/api/v3/absencemanager/absences"
ABSENCE_TYPE_ENDPOINT = "/api/v3/absencemanager/absence-type-settings/{id}"


class CrewmeisterError(Exception):
    """Base exception for Crewmeister errors."""


class CrewmeisterAuthError(CrewmeisterError):
    """Raised when authentication fails."""


class CrewmeisterConnectionError(CrewmeisterError):
    """Raised when the API cannot be reached."""


class CrewmeisterMissingIdentity(CrewmeisterError):
    """Raised when user identity data cannot be determined."""


@dataclass(slots=True)
class CrewmeisterIdentity:
    """Represents the authenticated user's identity."""

    user_id: int
    crew_id: int
    email: str | None = None
    full_name: str | None = None


@dataclass(slots=True)
class CrewmeisterStamp:
    """Represents a time tracking stamp."""

    raw: dict[str, Any]

    @property
    def timestamp(self) -> datetime | None:
        """Return the timestamp of the stamp."""

        value = self.raw.get("timestamp")
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:  # pragma: no cover - defensive
            _LOGGER.debug("Unable to parse stamp timestamp: %s", value)
            return None
        return dt

    @property
    def stamp_type(self) -> str | None:
        """Return the stamp type."""

        return self.raw.get("stampType")

    @property
    def status(self) -> str | None:
        """Return the stamp status."""

        return self.raw.get("stampStatus")


class CrewmeisterClient:
    """Client responsible for all Crewmeister API interaction."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
        identity: CrewmeisterIdentity | None = None,
        token: str | None = None,
        token_payload: dict[str, Any] | None = None,
        *,
        language: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._identity = identity
        self._token = token
        self._token_payload = token_payload or {}
        self._token_expiration: datetime | None = self._extract_token_expiration(self._token_payload)
        self._absence_types: dict[int, dict[str, Any]] = {}
        self._language = _normalize_language(language)

    def set_language(self, language: str | None) -> None:
        """Update the preferred language for API requests."""

        self._language = _normalize_language(language)

    @property
    def identity(self) -> CrewmeisterIdentity | None:
        """Return the cached identity."""

        return self._identity

    def _build_url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self._base_url}{path}"

    async def async_login(self) -> tuple[str, dict[str, Any]]:
        """Authenticate and obtain a new JWT token."""

        payload = {"username": self._username, "password": self._password}
        try:
            async with async_timeout.timeout(30):
                response = await self._session.post(self._build_url(AUTH_ENDPOINT), json=payload)
        except aiohttp.ClientError as err:
            raise CrewmeisterConnectionError("Cannot connect to Crewmeister API") from err

        if response.status != 200:
            body = await self._safe_read_json(response)
            _LOGGER.debug("Authentication failed: status=%s body=%s", response.status, body)
            raise CrewmeisterAuthError("Authentication with Crewmeister API failed")

        data = await response.json()
        token = data.get("token")
        if not token:
            raise CrewmeisterAuthError("Crewmeister token missing in authentication response")

        payload = decode_jwt_payload(token)
        self._token = token
        self._token_payload = payload
        self._token_expiration = self._extract_token_expiration(payload)
        return token, payload

    async def async_ensure_logged_in(self) -> None:
        """Refresh the authentication token if needed."""

        if not self._token:
            await self.async_login()
            return

        if not self._token_expiration:
            # Token without exp claim - refresh periodically
            await self.async_login()
            return

        now = datetime.now(timezone.utc)
        if (self._token_expiration - now).total_seconds() < TOKEN_REFRESH_MARGIN:
            await self.async_login()

    async def async_api_request(
        self,
        method: str,
        path: str,
        *,
        retry_on_unauthorized: bool = True,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Perform an authorized API request."""

        await self.async_ensure_logged_in()
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {self._token}")
        headers.setdefault("Accept", "application/json")
        if self._language:
            headers.setdefault("Accept-Language", self._language)
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")
        url = self._build_url(path)

        try:
            async with async_timeout.timeout(30):
                response = await self._session.request(method, url, headers=headers, **kwargs)
        except aiohttp.ClientError as err:
            raise CrewmeisterConnectionError("Error communicating with Crewmeister API") from err

        if response.status == 401 and retry_on_unauthorized:
            _LOGGER.debug("Token rejected by API, attempting re-authentication")
            await self.async_login()
            return await self.async_api_request(method, path, retry_on_unauthorized=False, **kwargs)

        return response

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.async_api_request(method, path, **kwargs)
        if response.status >= 400:
            body = await self._safe_read_json(response)
            detail = _extract_error_detail(body)
            _LOGGER.debug(
                "Crewmeister API request failed: method=%s path=%s status=%s body=%s",
                method,
                path,
                response.status,
                body,
            )
            if detail:
                raise CrewmeisterError(
                    f"Crewmeister API returned {response.status}: {detail}"
                )
            raise CrewmeisterError(f"Crewmeister API returned {response.status}")
        return await response.json()

    async def async_get_latest_stamp(self, user_id: int | None = None) -> CrewmeisterStamp | None:
        """Return the most recent stamp for the authenticated user."""

        params: dict[str, Any] = {"pageSize": 1, "sort": "-timestamp"}
        if user_id:
            params["filter"] = f"userId=={user_id}"
        data = await self._request_json("GET", STAMPS_ENDPOINT, params=params)
        content = data.get("content", []) if isinstance(data, dict) else []
        if not content:
            return None
        return CrewmeisterStamp(content[0])

    async def async_get_absences(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        states: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch absences for the given time window."""

        filters = [
            f"userId=={user_id}",
            f"from<='{end.date().isoformat()}'",
            f"to>='{start.date().isoformat()}'",
        ]
        if states:
            state_filter = ",".join(f"'{state}'" for state in sorted(states))
            filters.append(f"state=in=({state_filter})")
        params = {
            "pageSize": 200,
            "sort": ["+from"],
            "filter": ";".join(filters),
        }
        data = await self._request_json("GET", ABSENCES_ENDPOINT, params=params)
        if isinstance(data, dict):
            return data.get("content", [])
        return []

    async def async_create_stamp(
        self,
        stamp_type: str,
        *,
        timestamp: datetime | None = None,
        note: str | None = None,
        location: str | None = None,
        chain_start_stamp_id: int | None = None,
        time_account_id: int | None = None,
        time_category_ids: dict[str, int | None] | None = None,
        allocation_date: str | None = None,
    ) -> CrewmeisterStamp:
        """Create a new stamp for the authenticated user."""

        if stamp_type not in STAMP_TYPES:
            raise ValueError(f"Unsupported stamp type: {stamp_type}")

        identity = await self.async_get_identity()
        timestamp = timestamp or datetime.now(timezone.utc)
        timestamp_utc = timestamp.astimezone(timezone.utc)

        payload: dict[str, Any] = {
            "@type": "com.crewmeister/Stamp",
            "crewId": identity.crew_id,
            "userId": identity.user_id,
            "stampType": stamp_type,
            "timestamp": timestamp_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "allocationDate": allocation_date or timestamp_utc.date().isoformat(),
        }
        if note:
            payload["note"] = note
        if location:
            payload["location"] = location
        # According to the Crewmeister API documentation, ``chainStartStampId`` must be
        # preserved for follow-up stamps that belong to an existing chain (e.g. breaks or
        # clock-out events). When provided we forward it, otherwise the backend assigns
        # the value automatically for new chains such as clock-in events.
        if chain_start_stamp_id is not None:
            payload["chainStartStampId"] = chain_start_stamp_id
        if time_account_id is not None:
            payload["timeAccountId"] = time_account_id
        if time_category_ids:
            for key, value in time_category_ids.items():
                if value is not None:
                    payload[key] = value

        data = await self._request_json("POST", STAMPS_ENDPOINT, json=payload)
        # The API returns a SyncWriteResponse structure with resourceAfterWrite
        if isinstance(data, dict):
            resource = data.get("resourceAfterWrite")
            if isinstance(resource, dict):
                return CrewmeisterStamp(resource)
        return CrewmeisterStamp(data)  # fallback

    async def async_get_identity(self) -> CrewmeisterIdentity:
        """Return or resolve the identity of the authenticated user."""

        if self._identity:
            return self._identity

        token_identity = _extract_identity_from_payload(self._token_payload)
        user_id = token_identity.get(CONF_USER_ID)
        crew_id = token_identity.get(CONF_CREW_ID)
        email = token_identity.get("email")
        full_name = token_identity.get("name")

        # Attempt to discover via latest stamp if necessary
        if not user_id or not crew_id:
            stamp = await self.async_get_latest_stamp()
            if stamp and isinstance(stamp.raw, dict):
                user_id = user_id or stamp.raw.get("userId")
                crew_id = crew_id or stamp.raw.get("crewId")

        if not user_id or not crew_id:
            raise CrewmeisterMissingIdentity("Unable to determine Crewmeister user identity")

        identity = CrewmeisterIdentity(user_id=int(user_id), crew_id=int(crew_id), email=email, full_name=full_name)
        self._identity = identity
        return identity

    async def async_get_absence_type(self, type_id: int) -> dict[str, Any] | None:
        """Return metadata for a specific absence type."""

        if type_id in self._absence_types:
            return self._absence_types[type_id]

        path = ABSENCE_TYPE_ENDPOINT.format(id=type_id)
        try:
            data = await self._request_json("GET", path)
        except CrewmeisterError:
            _LOGGER.debug("Could not fetch absence type %s", type_id)
            return None

        if isinstance(data, dict):
            self._absence_types[type_id] = data
            return data
        return None

    async def async_get_absence_type_name(self, type_id: int) -> str | None:
        """Return the display name for an absence type."""

        info = await self.async_get_absence_type(type_id)
        if not info:
            return None
        translation = _extract_translated_name(info, self._language)
        if translation:
            return translation
        return info.get("name") or info.get("displayName") or info.get("absenceTypeName")

    @staticmethod
    def _extract_token_expiration(payload: dict[str, Any]) -> datetime | None:
        exp = payload.get("exp")
        if exp is None:
            return None
        try:
            return datetime.fromtimestamp(int(exp), timezone.utc)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            _LOGGER.debug("Invalid exp claim in Crewmeister token: %s", exp)
            return None

    @staticmethod
    async def _safe_read_json(response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json()
        except aiohttp.ContentTypeError:
            return await response.text()
        except Exception:  # pragma: no cover - defensive
            return None


def _extract_error_detail(body: Any) -> str | None:
    """Return a readable error detail from a failed API response."""

    if not body:
        return None

    if isinstance(body, str):
        return body

    if isinstance(body, dict):
        for key in ("message", "error", "error_description", "detail", "title", "reason"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        errors = body.get("errors")
        if isinstance(errors, list):
            messages: list[str] = []
            for item in errors:
                if isinstance(item, str) and item:
                    messages.append(item)
                elif isinstance(item, dict):
                    message = item.get("message")
                    if isinstance(message, str) and message:
                        messages.append(message)
            if messages:
                return "; ".join(messages)
        if "errorCode" in body and isinstance(body["errorCode"], str):
            return body["errorCode"]

    if isinstance(body, list):
        parts = [str(item) for item in body if item]
        if parts:
            return "; ".join(parts)

    return None


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload of a JWT without verification."""

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64)
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return {}
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:  # pragma: no cover - defensive
        return {}


def _extract_identity_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract identity values from a JWT payload."""

    identity: dict[str, Any] = {}
    if not payload:
        return identity

    # Common claim names observed in Crewmeister tokens
    for key in ("userId", "user_id", "uid", "sub"):
        value = payload.get(key)
        if value:
            if isinstance(value, str) and value.isdigit():
                identity[CONF_USER_ID] = int(value)
            elif isinstance(value, str) and value.startswith("user:"):
                try:
                    identity[CONF_USER_ID] = int(value.split(":", 1)[1])
                except ValueError:  # pragma: no cover - defensive
                    continue
            elif isinstance(value, int):
                identity[CONF_USER_ID] = value
            break

    for key in ("crewId", "crew_id", "cid", "crew"):
        value = payload.get(key)
        if value:
            if isinstance(value, str) and value.isdigit():
                identity[CONF_CREW_ID] = int(value)
            elif isinstance(value, int):
                identity[CONF_CREW_ID] = value
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
    tag = language.replace("_", "-")
    return tag.strip() or None


def _extract_translated_name(data: dict[str, Any], language: str | None) -> str | None:
    """Best-effort extraction of a localized absence type name."""

    if not language:
        return None

    candidates: list[str] = []
    lang_lower = language.lower()
    lang_primary = lang_lower.split("-", 1)[0]

    translations = data.get("translations")
    if isinstance(translations, dict):
        candidates.extend(_iter_translation_matches(translations, lang_lower, lang_primary))

    name_translations = data.get("nameTranslations")
    if isinstance(name_translations, dict):
        candidates.extend(_iter_translation_matches(name_translations, lang_lower, lang_primary))

    localized = data.get("displayNameLocalized") or data.get("nameLocalized")
    if isinstance(localized, str) and localized:
        return localized

    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _iter_translation_matches(
    translations: dict[str, Any],
    lang_lower: str,
    lang_primary: str,
) -> list[str]:
    """Collect translation matches for the desired language codes."""

    matches: list[str] = []
    for key, value in translations.items():
        if not isinstance(value, str) or not value:
            continue
        key_lower = str(key).lower()
        if key_lower == lang_lower or key_lower.replace("_", "-") == lang_lower:
            matches.append(value)
        elif key_lower == lang_primary or key_lower.split("-", 1)[0] == lang_primary:
            matches.append(value)
    return matches
