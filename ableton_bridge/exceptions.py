"""Typed exception hierarchy for the Ableton bridge.

Every error raised by :class:`ableton_bridge.bridge.AbletonBridge` derives from
:class:`AbletonBridgeError`, so callers can catch the whole family with a single
``except AbletonBridgeError`` while still being able to distinguish individual
failure modes when they care.
"""

from __future__ import annotations


class AbletonBridgeError(Exception):
    """Base class for all errors raised by the Ableton bridge."""


class OSCTimeoutError(AbletonBridgeError):
    """Raised when an OSC request does not receive a reply within the timeout.

    A timeout usually means Ableton Live is not running, AbletonOSC is not
    installed/enabled as the active Control Surface, or the configured ports are
    wrong.
    """


class TrackNotFoundError(AbletonBridgeError):
    """Raised when a track cannot be resolved by name."""


class SceneNotFoundError(AbletonBridgeError):
    """Raised when a scene cannot be resolved by name."""


class ClipNotFoundError(AbletonBridgeError):
    """Raised when an operation targets a clip slot that holds no clip."""


class AudioTrackCannotHoldMidiError(AbletonBridgeError):
    """Raised when a MIDI operation targets an audio track.

    Audio tracks have no MIDI input and cannot hold MIDI clips. AbletonOSC fails
    *silently* server-side in this case (no error reply is sent), so the bridge
    refuses the operation up front rather than letting it disappear.
    """


class DeviceNotFoundError(AbletonBridgeError):
    """Raised when a device cannot be resolved by name on a track."""


class ParameterNotFoundError(AbletonBridgeError):
    """Raised when a device parameter cannot be resolved by name."""
