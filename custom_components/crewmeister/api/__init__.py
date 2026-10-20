"""Crewmeister API client package."""

from .client import CrewmeisterClient
from .errors import (
    CrewmeisterAuthError,
    CrewmeisterConnectionError,
    CrewmeisterError,
    CrewmeisterMissingIdentity,
)
from .models import (
    Absence,
    CrewmeisterIdentity,
    InvalidTransitionError,
    Stamp,
    StampStatus,
    StampType,
    WorkStatus,
    derive_status,
    validate_transition,
)

__all__ = [
    "Absence",
    "CrewmeisterAuthError",
    "CrewmeisterClient",
    "CrewmeisterConnectionError",
    "CrewmeisterError",
    "CrewmeisterIdentity",
    "CrewmeisterMissingIdentity",
    "InvalidTransitionError",
    "Stamp",
    "StampStatus",
    "StampType",
    "WorkStatus",
    "derive_status",
    "validate_transition",
]
