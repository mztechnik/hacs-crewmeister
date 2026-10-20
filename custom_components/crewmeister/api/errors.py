"""Exceptions raised by the Crewmeister API client."""

from __future__ import annotations


class CrewmeisterError(Exception):
    """Base exception for Crewmeister errors."""


class CrewmeisterAuthError(CrewmeisterError):
    """Raised when authentication fails."""


class CrewmeisterConnectionError(CrewmeisterError):
    """Raised when the API cannot be reached or answers with a server error."""


class CrewmeisterMissingIdentity(CrewmeisterError):
    """Raised when user identity data cannot be determined."""
