"""MIDI note representation and pitch <-> name conversion.

AbletonOSC represents a note's pitch as a raw MIDI integer (0-127). This module
converts to and from scientific pitch notation (e.g. ``"C3"``) so callers can
work with human-readable note names.

Octave convention
------------------
There are two competing conventions for naming MIDI pitches:

* **Ableton Live** displays MIDI note 60 (middle C) as ``C3``.
* **Scientific pitch notation (SPN)** names MIDI note 60 as ``C4``.

This module defaults to **Ableton's convention** (``middle_c_octave=3``) because
the bridge wraps Ableton, but every conversion accepts a ``middle_c_octave``
argument so callers can switch to strict SPN (``middle_c_octave=4``) if needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Default octave number assigned to middle C (MIDI 60). ``3`` matches Ableton
#: Live's on-screen labelling; pass ``4`` for strict scientific pitch notation.
DEFAULT_MIDDLE_C_OCTAVE = 3

#: Lowest and highest valid MIDI pitch values.
MIN_PITCH = 0
MAX_PITCH = 127

_NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Every accepted spelling (naturals, sharps and flats) mapped to its pitch class.
_PITCH_CLASSES = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "F": 5,
    "E#": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}

_NOTE_RE = re.compile(r"^([A-Ga-g])([#bB]?)(-?\d+)$")


def pitch_to_name(pitch: int, middle_c_octave: int = DEFAULT_MIDDLE_C_OCTAVE) -> str:
    """Convert a MIDI pitch integer to scientific pitch notation.

    Args:
        pitch: MIDI note number in the range 0-127.
        middle_c_octave: Octave number to assign to middle C (MIDI 60). Defaults
            to 3 (Ableton Live convention); pass 4 for strict SPN.

    Returns:
        The note name using sharps, e.g. ``"C3"`` or ``"F#5"``.

    Raises:
        ValueError: If ``pitch`` is outside 0-127.
    """
    if not MIN_PITCH <= pitch <= MAX_PITCH:
        raise ValueError(f"MIDI pitch must be in {MIN_PITCH}-{MAX_PITCH}, got {pitch}")
    octave = (pitch // 12) - (5 - middle_c_octave)
    return f"{_NOTE_NAMES_SHARP[pitch % 12]}{octave}"


def name_to_pitch(name: str, middle_c_octave: int = DEFAULT_MIDDLE_C_OCTAVE) -> int:
    """Convert scientific pitch notation to a MIDI pitch integer.

    Args:
        name: A note name such as ``"C3"``, ``"f#5"`` or ``"Bb4"``. The note
            letter is case insensitive and both sharps (``#``) and flats (``b``)
            are accepted. An octave number is required and may be negative.
        middle_c_octave: Octave number that middle C (MIDI 60) is assigned to.
            Defaults to 3 (Ableton Live convention); pass 4 for strict SPN.

    Returns:
        The MIDI note number in the range 0-127.

    Raises:
        ValueError: If the name cannot be parsed or maps outside 0-127.
    """
    match = _NOTE_RE.match(name.strip())
    if match is None:
        raise ValueError(f"Cannot parse note name {name!r} (expected e.g. 'C3', 'F#5', 'Bb4')")
    letter, accidental, octave_str = match.groups()
    key = (letter + accidental).upper()
    if key not in _PITCH_CLASSES:  # pragma: no cover - regex only admits known spellings
        raise ValueError(f"Unknown note name {name!r}")
    pitch = _PITCH_CLASSES[key] + 12 * (int(octave_str) + (5 - middle_c_octave))
    if not MIN_PITCH <= pitch <= MAX_PITCH:
        raise ValueError(
            f"Note {name!r} maps to MIDI pitch {pitch}, outside {MIN_PITCH}-{MAX_PITCH}"
        )
    return pitch


@dataclass(frozen=True)
class Note:
    """A single MIDI note, as used by clip read/write operations.

    Attributes:
        pitch: MIDI note number (0-127).
        start: Start position in beats from the clip origin.
        duration: Note length in beats.
        velocity: MIDI velocity (0-127). May be fractional.
        mute: Whether the note is muted.
    """

    pitch: int
    start: float
    duration: float
    velocity: float = 100.0
    mute: bool = False

    @property
    def name(self) -> str:
        """The pitch in scientific notation using Ableton's octave convention.

        For a non-default octave base, call :func:`pitch_to_name` directly or use
        :meth:`ableton_bridge.bridge.AbletonBridge.pitch_to_name`.
        """
        return pitch_to_name(self.pitch)

    @classmethod
    def from_name(
        cls,
        name: str,
        start: float,
        duration: float,
        velocity: float = 100.0,
        mute: bool = False,
        *,
        middle_c_octave: int = DEFAULT_MIDDLE_C_OCTAVE,
    ) -> Note:
        """Create a :class:`Note` from a pitch name such as ``"C3"``.

        Args:
            name: Pitch name in scientific notation (e.g. ``"C3"``, ``"F#5"``).
            start: Start position in beats.
            duration: Note length in beats.
            velocity: MIDI velocity (0-127).
            mute: Whether the note is muted.
            middle_c_octave: Octave number for middle C. Defaults to 3 (Ableton).

        Returns:
            A new :class:`Note`.
        """
        return cls(name_to_pitch(name, middle_c_octave), start, duration, velocity, mute)

    def key(self) -> tuple[int, float]:
        """Return the ``(pitch, start)`` identity used to locate this note.

        AbletonOSC has no note identity, so a note is addressed for removal or
        modification by its pitch and start beat.

        Returns:
            A ``(pitch, start)`` tuple.
        """
        return (self.pitch, self.start)
