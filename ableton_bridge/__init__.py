"""ableton_bridge: a clean Python wrapper around AbletonOSC.

The primary entry point is :class:`AbletonBridge`. See ``README.md`` for usage
and ``KNOWN_LIMITATIONS.md`` for the pinned AbletonOSC version and caveats.

Example:
    >>> from ableton_bridge import AbletonBridge, Note
    >>> with AbletonBridge() as live:
    ...     live.ping()
    ...     live.create_clip("K_piano", 0, length=4.0)
    ...     live.add_notes("K_piano", 0, [Note.from_name("C3", 0.0, 1.0)])
"""

from __future__ import annotations

from .bridge import NOTE_MATCH_WINDOW, AbletonBridge, ClipInfo
from .exceptions import (
    AbletonBridgeError,
    AudioTrackCannotHoldMidiError,
    ClipNotFoundError,
    DeviceNotFoundError,
    OSCTimeoutError,
    ParameterNotFoundError,
    SceneNotFoundError,
    TrackNotFoundError,
)
from .notes import DEFAULT_MIDDLE_C_OCTAVE, Note, name_to_pitch, pitch_to_name
from .osc_client import OSCClient

__version__ = "2.0.0"

__all__ = [
    # Core
    "AbletonBridge",
    "ClipInfo",
    "Note",
    "OSCClient",
    "NOTE_MATCH_WINDOW",
    # Pitch helpers
    "name_to_pitch",
    "pitch_to_name",
    "DEFAULT_MIDDLE_C_OCTAVE",
    # Exceptions
    "AbletonBridgeError",
    "AudioTrackCannotHoldMidiError",
    "ClipNotFoundError",
    "DeviceNotFoundError",
    "OSCTimeoutError",
    "ParameterNotFoundError",
    "SceneNotFoundError",
    "TrackNotFoundError",
    "__version__",
]
