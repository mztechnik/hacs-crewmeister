"""Assistant automating stamping: presence detection, reminders and breaks.

Everything here is optional; without configuration the assistant stays passive.
"""

from .core import CrewmeisterAssistant, async_remove_assistant_store
from .util import WORK_LOCATIONS, StampResult

__all__ = [
    "WORK_LOCATIONS",
    "CrewmeisterAssistant",
    "StampResult",
    "async_remove_assistant_store",
]
