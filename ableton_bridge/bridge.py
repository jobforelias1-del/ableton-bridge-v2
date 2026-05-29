"""High-level client for driving Ableton Live via AbletonOSC.

:class:`AbletonBridge` is the primary entry point. It wraps the verified
AbletonOSC OSC surface (see ``KNOWN_LIMITATIONS.md`` for the pinned version) and
adds the behaviour that production use at Silicon Click depends on:

* name -> index resolution for tracks, scenes, devices and parameters;
* refusal to put MIDI on an audio track (rather than AbletonOSC's silent fail);
* idempotent clip creation;
* batched note writes and an "atomic-as-possible" note modify via OSC bundles.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .exceptions import (
    AudioTrackCannotHoldMidiError,
    ClipNotFoundError,
    DeviceNotFoundError,
    ParameterNotFoundError,
    SceneNotFoundError,
    TrackNotFoundError,
)
from .notes import DEFAULT_MIDDLE_C_OCTAVE, Note, name_to_pitch, pitch_to_name
from .osc_client import (
    DEFAULT_HOST,
    DEFAULT_RECEIVE_PORT,
    DEFAULT_SEND_PORT,
    DEFAULT_TIMEOUT,
    OSCClient,
)

logger = logging.getLogger("ableton_bridge")

#: Width in beats of the time window used to target a note for removal by its
#: ``(pitch, start)`` key. AbletonOSC removes notes by *range*, not identity, so
#: a small non-zero window is needed to capture a note that starts exactly at a
#: given beat without catching neighbours. 1/256 beat is far smaller than any
#: musically meaningful note spacing.
NOTE_MATCH_WINDOW = 1.0 / 256.0

#: A track, scene, device or parameter may be referenced by integer index or by
#: name (string).
Ref = int | str

#: A note may be addressed for removal/modification by a :class:`Note` or by a
#: bare ``(pitch, start)`` tuple, where pitch is a MIDI int or a name like "C3".
NoteKey = Note | tuple[Ref, float]


@dataclass
class ClipInfo:
    """A snapshot of a MIDI clip's contents.

    Attributes:
        track_index: Index of the track holding the clip.
        clip_index: Index of the clip slot.
        name: The clip's name.
        length: The clip length in beats.
        notes: The notes in the clip, ordered as returned by Live.
        time_signature: The *song* time signature as ``(numerator, denominator)``.
            AbletonOSC does not expose a per-clip time signature, so this is a
            documented best-effort fallback; see ``KNOWN_LIMITATIONS.md``.
    """

    track_index: int
    clip_index: int
    name: str
    length: float
    notes: list[Note]
    time_signature: tuple[int, int]


class AbletonBridge:
    """A clean, typed wrapper around AbletonOSC.

    The bridge may be used as a context manager, which closes the transport on
    exit::

        with AbletonBridge() as live:
            live.ping()
            live.set_tempo(120)
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        transport=None,
        middle_c_octave: int = DEFAULT_MIDDLE_C_OCTAVE,
    ) -> None:
        """Create a bridge to a running AbletonOSC instance.

        Args:
            host: Hostname/IP where AbletonOSC is listening. Defaults to
                ``127.0.0.1``.
            send_port: UDP port AbletonOSC listens on. Defaults to 11000.
            receive_port: UDP port AbletonOSC sends replies to. Defaults to 11001.
            timeout: Seconds to wait for a reply before raising
                :class:`~ableton_bridge.exceptions.OSCTimeoutError`.
            transport: An optional pre-built transport implementing ``send``,
                ``send_bundle`` and ``request``. Mainly for testing; when omitted
                a real :class:`~ableton_bridge.osc_client.OSCClient` is created.
            middle_c_octave: Octave number for middle C in note names. Defaults to
                3 (Ableton convention); pass 4 for strict scientific pitch
                notation.
        """
        self._osc = (
            transport
            if transport is not None
            else OSCClient(host, send_port, receive_port, timeout)
        )
        self.middle_c_octave = middle_c_octave

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Close the underlying OSC transport."""
        self._osc.close()

    def __enter__(self) -> AbletonBridge:
        """Enter the context manager.

        Returns:
            This bridge.
        """
        return self

    def __exit__(self, *exc) -> None:
        """Close the transport on context-manager exit."""
        self.close()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _request(self, address: str, *send_args, echo: int = 0) -> list:
        """Send a read request and return the reply with echoed args stripped.

        Args:
            address: OSC address to query.
            *send_args: Arguments to send.
            echo: Number of leading arguments AbletonOSC echoes back in the reply
                (e.g. the track/clip indices). These are validated against the
                request and removed from the returned list.

        Returns:
            The reply parameters after the first ``echo`` echoed values.
        """
        params = self._osc.request(address, *send_args, match_leading=send_args[:echo])
        return params[echo:]

    def _resolve_track(self, track: Ref) -> int:
        """Resolve a track reference (index or name) to an index."""
        if isinstance(track, str):
            return self.get_track_index(track)
        return int(track)

    def _resolve_scene(self, scene: Ref) -> int:
        """Resolve a scene reference (index or name) to an index."""
        if isinstance(scene, str):
            return self.get_scene_index(scene)
        return int(scene)

    def _resolve_device(self, track_index: int, device: Ref) -> int:
        """Resolve a device reference (index or name) on a resolved track."""
        if isinstance(device, str):
            return self.get_device_index(track_index, device)
        return int(device)

    def _resolve_parameter(self, track_index: int, device_index: int, parameter: Ref) -> int:
        """Resolve a parameter reference (index or name) on a resolved device."""
        if isinstance(parameter, str):
            names = self.get_parameter_names(track_index, device_index)
            try:
                return names.index(parameter)
            except ValueError:
                raise ParameterNotFoundError(
                    f"No parameter named {parameter!r} on track {track_index} "
                    f"device {device_index}. Available: {names}"
                ) from None
        return int(parameter)

    def _require_midi_track(self, track_index: int) -> None:
        """Raise if the track cannot hold MIDI (i.e. has no MIDI input)."""
        if not self.track_has_midi_input(track_index):
            raise AudioTrackCannotHoldMidiError(
                f"Track {track_index} is an audio track and cannot hold MIDI clips"
            )

    @staticmethod
    def _note_to_args(note: Note) -> tuple[int, float, float, float, bool]:
        """Flatten a :class:`Note` to the OSC argument order add/notes expects."""
        return (
            int(note.pitch),
            float(note.start),
            float(note.duration),
            float(note.velocity),
            bool(note.mute),
        )

    def _key_to_pitch_start(self, key: NoteKey) -> tuple[int, float]:
        """Normalise a note key to ``(midi_pitch, start_beat)``."""
        if isinstance(key, Note):
            return key.pitch, key.start
        pitch, start = key
        if isinstance(pitch, str):
            pitch = name_to_pitch(pitch, self.middle_c_octave)
        return int(pitch), float(start)

    def _remove_message(self, track_index: int, clip_index: int, key: NoteKey):
        """Build a narrow-window ``/live/clip/remove/notes`` message for a key."""
        pitch, start = self._key_to_pitch_start(key)
        return (
            "/live/clip/remove/notes",
            (track_index, clip_index, pitch, 1, start, NOTE_MATCH_WINDOW),
        )

    def _read_notes(self, track_index: int, clip_index: int) -> list[Note]:
        """Read notes from a clip that is already known to exist."""
        # Reply: track, clip, then groups of 5: pitch, start, duration, velocity, mute.
        tail = self._request("/live/clip/get/notes", track_index, clip_index, echo=2)
        notes: list[Note] = []
        for offset in range(0, len(tail), 5):
            chunk = tail[offset : offset + 5]
            if len(chunk) < 5:  # pragma: no cover - defensive against a malformed reply
                break
            pitch, start, duration, velocity, mute = chunk
            notes.append(
                Note(
                    pitch=int(pitch),
                    start=float(start),
                    duration=float(duration),
                    velocity=float(velocity),
                    mute=bool(mute),
                )
            )
        return notes

    # ------------------------------------------------------------------ #
    # System / connection
    # ------------------------------------------------------------------ #
    def ping(self) -> bool:
        """Check that AbletonOSC is reachable.

        Sends ``/live/test`` and waits for the ``ok`` reply.

        Returns:
            ``True`` if AbletonOSC replied with ``ok``.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        logger.info("Pinging AbletonOSC")
        params = self._osc.request("/live/test")
        return bool(params) and params[0] == "ok"

    def get_live_version(self) -> tuple[int, int]:
        """Return the running Ableton Live version as ``(major, minor)``.

        Returns:
            The major and minor version numbers.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        params = self._osc.request("/live/application/get/version")
        return int(params[0]), int(params[1])

    def show_message(self, message: str) -> None:
        """Show a message in Live's status bar.

        Args:
            message: The text to display.
        """
        logger.info("Showing message in Live: %s", message)
        self._osc.send("/live/api/show_message", message)

    # ------------------------------------------------------------------ #
    # Song / transport
    # ------------------------------------------------------------------ #
    def get_tempo(self) -> float:
        """Return the current song tempo in BPM.

        Returns:
            The tempo in beats per minute.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        return float(self._request("/live/song/get/tempo")[0])

    def set_tempo(self, bpm: float) -> None:
        """Set the song tempo.

        Args:
            bpm: The tempo in beats per minute.
        """
        logger.info("Setting tempo to %.3f BPM", bpm)
        self._osc.send("/live/song/set/tempo", float(bpm))

    def is_playing(self) -> bool:
        """Return whether the song transport is currently playing.

        Returns:
            ``True`` if playing.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        return bool(self._request("/live/song/get/is_playing")[0])

    def start_playing(self) -> None:
        """Start song playback from the current position."""
        logger.info("Starting playback")
        self._osc.send("/live/song/start_playing")

    def stop_playing(self) -> None:
        """Stop song playback."""
        logger.info("Stopping playback")
        self._osc.send("/live/song/stop_playing")

    def continue_playing(self) -> None:
        """Continue song playback from where it was stopped."""
        logger.info("Continuing playback")
        self._osc.send("/live/song/continue_playing")

    def get_time_signature(self) -> tuple[int, int]:
        """Return the song time signature as ``(numerator, denominator)``.

        Returns:
            The time signature numerator and denominator.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        numerator = int(self._request("/live/song/get/signature_numerator")[0])
        denominator = int(self._request("/live/song/get/signature_denominator")[0])
        return numerator, denominator

    def set_time_signature(self, numerator: int, denominator: int) -> None:
        """Set the song time signature.

        Args:
            numerator: The time signature numerator (e.g. 4).
            denominator: The time signature denominator (e.g. 4).
        """
        logger.info("Setting time signature to %d/%d", numerator, denominator)
        self._osc.send("/live/song/set/signature_numerator", int(numerator))
        self._osc.send("/live/song/set/signature_denominator", int(denominator))

    # ------------------------------------------------------------------ #
    # Name resolution
    # ------------------------------------------------------------------ #
    def get_track_names(self) -> list[str]:
        """Return the names of all tracks in song order.

        Returns:
            A list of track names.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        return [str(name) for name in self._request("/live/song/get/track_names")]

    def get_track_index(self, name: str) -> int:
        """Resolve a track name to its index.

        Args:
            name: The exact track name. If several tracks share a name, the
                first match is returned.

        Returns:
            The zero-based track index.

        Raises:
            TrackNotFoundError: If no track has the given name.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        names = self.get_track_names()
        try:
            index = names.index(name)
        except ValueError:
            raise TrackNotFoundError(f"No track named {name!r}. Available: {names}") from None
        logger.info("Resolved track %r to index %d", name, index)
        return index

    def get_scene_names(self) -> list[str]:
        """Return the names of all scenes in song order.

        Returns:
            A list of scene names.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        return [str(name) for name in self._request("/live/song/get/scenes/name")]

    def get_scene_index(self, name: str) -> int:
        """Resolve a scene name to its index.

        Args:
            name: The exact scene name. If several scenes share a name, the first
                match is returned.

        Returns:
            The zero-based scene index.

        Raises:
            SceneNotFoundError: If no scene has the given name.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        names = self.get_scene_names()
        try:
            index = names.index(name)
        except ValueError:
            raise SceneNotFoundError(f"No scene named {name!r}. Available: {names}") from None
        logger.info("Resolved scene %r to index %d", name, index)
        return index

    def fire_scene(self, scene: Ref) -> None:
        """Fire (launch) a scene.

        Args:
            scene: Scene index or name.

        Raises:
            SceneNotFoundError: If a name is given that does not resolve.
        """
        index = self._resolve_scene(scene)
        logger.info("Firing scene %d", index)
        self._osc.send("/live/scene/fire", index)

    def track_has_midi_input(self, track: Ref) -> bool:
        """Return whether a track has MIDI input (i.e. can hold MIDI clips).

        Args:
            track: Track index or name.

        Returns:
            ``True`` for MIDI tracks, ``False`` for audio tracks.

        Raises:
            TrackNotFoundError: If a name is given that does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        index = self._resolve_track(track)
        value = self._request("/live/track/get/has_midi_input", index, echo=1)[0]
        return bool(value)

    # ------------------------------------------------------------------ #
    # Clip slots / clips
    # ------------------------------------------------------------------ #
    def has_clip(self, track: Ref, clip_index: int) -> bool:
        """Return whether a clip slot holds a clip.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.

        Returns:
            ``True`` if the slot holds a clip.

        Raises:
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        value = self._request("/live/clip_slot/get/has_clip", track_index, int(clip_index), echo=2)[
            0
        ]
        return bool(value)

    def create_clip(
        self, track: Ref, clip_index: int, length: float = 4.0, *, verify: bool = True
    ) -> bool:
        """Create an empty MIDI clip in a slot, idempotently.

        If the slot already holds a clip this is a no-op and returns ``False`` --
        re-running is safe and never raises. The target track must be a MIDI
        track.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.
            length: Length of the new clip in beats. Defaults to 4.0.
            verify: If ``True`` (default), re-read ``has_clip`` after creating to
                confirm it took effect, since AbletonOSC does not acknowledge
                writes.

        Returns:
            ``True`` if a clip was created, ``False`` if one already existed.

        Raises:
            AudioTrackCannotHoldMidiError: If the track has no MIDI input.
            ClipNotFoundError: If ``verify`` is set and the clip was not created.
            TrackNotFoundError: If a track name does not resolve.
            OSCTimeoutError: If a required reply does not arrive in time.
        """
        track_index = self._resolve_track(track)
        self._require_midi_track(track_index)
        if self.has_clip(track_index, clip_index):
            logger.info(
                "Clip already exists at track %d slot %d; create_clip is a no-op",
                track_index,
                clip_index,
            )
            return False
        logger.info(
            "Creating clip at track %d slot %d (length %.3f beats)",
            track_index,
            clip_index,
            length,
        )
        self._osc.send("/live/clip_slot/create_clip", track_index, int(clip_index), float(length))
        if verify and not self.has_clip(track_index, clip_index):
            raise ClipNotFoundError(
                f"create_clip on track {track_index} slot {clip_index} did not take effect "
                f"(the slot may be a group/return slot, or Live rejected the operation)"
            )
        return True

    def delete_clip(self, track: Ref, clip_index: int) -> None:
        """Delete the clip in a slot, if any.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.

        Raises:
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        logger.info("Deleting clip at track %d slot %d", track_index, clip_index)
        self._osc.send("/live/clip_slot/delete_clip", track_index, int(clip_index))

    def read_clip(self, track: Ref, clip_index: int) -> ClipInfo:
        """Read a clip's name, length, notes and (song-level) time signature.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.

        Returns:
            A :class:`ClipInfo` describing the clip.

        Raises:
            ClipNotFoundError: If the slot holds no clip.
            TrackNotFoundError: If a track name does not resolve.
            OSCTimeoutError: If a required reply does not arrive in time.
        """
        track_index = self._resolve_track(track)
        clip = int(clip_index)
        if not self.has_clip(track_index, clip):
            raise ClipNotFoundError(f"No clip at track {track_index} slot {clip}")
        name = str(self._request("/live/clip/get/name", track_index, clip, echo=2)[0])
        length = float(self._request("/live/clip/get/length", track_index, clip, echo=2)[0])
        notes = self._read_notes(track_index, clip)
        signature = self.get_time_signature()
        logger.info(
            "Read clip %r (%.3f beats, %d notes) at track %d slot %d",
            name,
            length,
            len(notes),
            track_index,
            clip,
        )
        return ClipInfo(
            track_index=track_index,
            clip_index=clip,
            name=name,
            length=length,
            notes=notes,
            time_signature=signature,
        )

    def get_notes(self, track: Ref, clip_index: int) -> list[Note]:
        """Return all notes in a clip.

        Pitches are MIDI integers; use :attr:`~ableton_bridge.notes.Note.name` or
        :meth:`pitch_to_name` for scientific notation.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.

        Returns:
            A list of :class:`~ableton_bridge.notes.Note`.

        Raises:
            ClipNotFoundError: If the slot holds no clip.
            TrackNotFoundError: If a track name does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        clip = int(clip_index)
        if not self.has_clip(track_index, clip):
            raise ClipNotFoundError(f"No clip at track {track_index} slot {clip}")
        notes = self._read_notes(track_index, clip)
        logger.info("Read %d notes from track %d slot %d", len(notes), track_index, clip)
        return notes

    # ------------------------------------------------------------------ #
    # Note write operations
    # ------------------------------------------------------------------ #
    def add_notes(self, track: Ref, clip_index: int, notes: Iterable[Note]) -> None:
        """Add MIDI notes to a clip in a single batched OSC message.

        All notes are sent in one ``/live/clip/add/notes`` datagram (a single
        round-trip). Notes are *added*; existing notes are left untouched.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.
            notes: An iterable of :class:`~ableton_bridge.notes.Note`.

        Raises:
            AudioTrackCannotHoldMidiError: If the track is not a MIDI track.
            ClipNotFoundError: If the slot holds no clip.
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        clip = int(clip_index)
        self._require_midi_track(track_index)
        if not self.has_clip(track_index, clip):
            raise ClipNotFoundError(
                f"No clip at track {track_index} slot {clip}; create it before adding notes"
            )
        notes = list(notes)
        if not notes:
            logger.info("add_notes called with no notes; nothing to do")
            return
        args: list = [track_index, clip]
        for note in notes:
            args.extend(self._note_to_args(note))
        logger.info("Adding %d notes to track %d slot %d", len(notes), track_index, clip)
        self._osc.send("/live/clip/add/notes", *args)

    def remove_notes(self, track: Ref, clip_index: int, keys: Iterable[NoteKey]) -> None:
        """Remove specific notes, identified by ``(pitch, start)``, from a clip.

        AbletonOSC removes notes by *range*, not identity, so each key is removed
        with a narrow time window (:data:`NOTE_MATCH_WINDOW`) around its start
        beat and a single-pitch span. When more than one key is given they are
        sent together in a single OSC bundle (one round-trip).

        Args:
            track: Track index or name.
            clip_index: Clip slot index.
            keys: An iterable of ``(pitch, start)`` tuples or
                :class:`~ableton_bridge.notes.Note` objects. Pitches may be MIDI
                ints or names such as ``"C3"``.

        Raises:
            AudioTrackCannotHoldMidiError: If the track is not a MIDI track.
            ClipNotFoundError: If the slot holds no clip.
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        clip = int(clip_index)
        self._require_midi_track(track_index)
        if not self.has_clip(track_index, clip):
            raise ClipNotFoundError(f"No clip at track {track_index} slot {clip}")
        messages = [self._remove_message(track_index, clip, key) for key in keys]
        if not messages:
            logger.info("remove_notes called with no keys; nothing to do")
            return
        logger.info("Removing %d notes from track %d slot %d", len(messages), track_index, clip)
        if len(messages) == 1:
            address, args = messages[0]
            self._osc.send(address, *args)
        else:
            self._osc.send_bundle(messages)

    def modify_notes(
        self, track: Ref, clip_index: int, changes: Iterable[tuple[NoteKey, Note]]
    ) -> None:
        """Modify notes by removing each old note and adding its replacement.

        AbletonOSC has no in-place note-modify endpoint, so each modification is a
        narrow-window remove of the old note followed by an add of the new note.
        To make this as atomic as possible, *all* removes and a *single* batched
        add are sent together in one OSC bundle (a single UDP datagram).
        AbletonOSC processes the messages in order within the bundle: every
        remove first, then the batched add.

        Ordering guarantee and caveat:
            Within the bundle, removes are applied before the add. Because
            AbletonOSC offers no transactional modify, if delivery or processing
            is interrupted mid-bundle the removed notes may be lost without their
            replacements being added. See ``KNOWN_LIMITATIONS.md``.

        Args:
            track: Track index or name.
            clip_index: Clip slot index.
            changes: An iterable of ``(old_key, new_note)`` pairs, where
                ``old_key`` is a ``(pitch, start)`` tuple or
                :class:`~ableton_bridge.notes.Note`, and ``new_note`` is the
                replacement :class:`~ableton_bridge.notes.Note`.

        Raises:
            AudioTrackCannotHoldMidiError: If the track is not a MIDI track.
            ClipNotFoundError: If the slot holds no clip.
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        clip = int(clip_index)
        self._require_midi_track(track_index)
        if not self.has_clip(track_index, clip):
            raise ClipNotFoundError(f"No clip at track {track_index} slot {clip}")
        changes = list(changes)
        if not changes:
            logger.info("modify_notes called with no changes; nothing to do")
            return
        messages: list[tuple[str, Sequence]] = []
        add_args: list = [track_index, clip]
        for old_key, new_note in changes:
            messages.append(self._remove_message(track_index, clip, old_key))
            add_args.extend(self._note_to_args(new_note))
        messages.append(("/live/clip/add/notes", tuple(add_args)))
        logger.info(
            "Modifying %d notes on track %d slot %d (remove-then-add bundle)",
            len(changes),
            track_index,
            clip,
        )
        self._osc.send_bundle(messages)

    # ------------------------------------------------------------------ #
    # Devices / parameters (rack macro automation)
    # ------------------------------------------------------------------ #
    def get_device_names(self, track: Ref) -> list[str]:
        """Return the names of the devices on a track, in chain order.

        Args:
            track: Track index or name.

        Returns:
            A list of device names.

        Raises:
            TrackNotFoundError: If a track name does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        return [
            str(name) for name in self._request("/live/track/get/devices/name", track_index, echo=1)
        ]

    def get_device_index(self, track: Ref, device_name: str) -> int:
        """Resolve a device name to its index on a track.

        Args:
            track: Track index or name.
            device_name: The exact device name.

        Returns:
            The zero-based device index.

        Raises:
            DeviceNotFoundError: If no device on the track has the given name.
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        names = self.get_device_names(track_index)
        try:
            return names.index(device_name)
        except ValueError:
            raise DeviceNotFoundError(
                f"No device named {device_name!r} on track {track_index}. Available: {names}"
            ) from None

    def get_parameter_names(self, track: Ref, device: Ref) -> list[str]:
        """Return the parameter names of a device, in index order.

        For a rack (instrument/audio-effect group) these include the macro
        controls used for automation.

        Args:
            track: Track index or name.
            device: Device index or name.

        Returns:
            A list of parameter names.

        Raises:
            TrackNotFoundError: If a track name does not resolve.
            DeviceNotFoundError: If a device name does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        device_index = self._resolve_device(track_index, device)
        return [
            str(name)
            for name in self._request(
                "/live/device/get/parameters/name", track_index, device_index, echo=2
            )
        ]

    def get_parameter_index(self, track: Ref, device: Ref, parameter_name: str) -> int:
        """Resolve a parameter name to its index on a device.

        Args:
            track: Track index or name.
            device: Device index or name.
            parameter_name: The exact parameter name (e.g. ``"Macro 1"``).

        Returns:
            The zero-based parameter index.

        Raises:
            ParameterNotFoundError: If no parameter has the given name.
            TrackNotFoundError: If a track name does not resolve.
            DeviceNotFoundError: If a device name does not resolve.
        """
        track_index = self._resolve_track(track)
        device_index = self._resolve_device(track_index, device)
        return self._resolve_parameter(track_index, device_index, parameter_name)

    def get_parameter_value(self, track: Ref, device: Ref, parameter: Ref) -> float:
        """Read a device parameter's current value.

        Args:
            track: Track index or name.
            device: Device index or name.
            parameter: Parameter index or name.

        Returns:
            The parameter's value (Live's native range for that parameter).

        Raises:
            TrackNotFoundError: If a track name does not resolve.
            DeviceNotFoundError: If a device name does not resolve.
            ParameterNotFoundError: If a parameter name does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        device_index = self._resolve_device(track_index, device)
        parameter_index = self._resolve_parameter(track_index, device_index, parameter)
        # Reply: track, device, parameter_index, value.
        tail = self._request(
            "/live/device/get/parameter/value",
            track_index,
            device_index,
            parameter_index,
            echo=3,
        )
        return float(tail[0])

    def set_parameter_value(self, track: Ref, device: Ref, parameter: Ref, value: float) -> None:
        """Set a device parameter's value (e.g. a rack macro for automation).

        Args:
            track: Track index or name.
            device: Device index or name.
            parameter: Parameter index or name (e.g. ``"Macro 1"``).
            value: The new value, in Live's native range for that parameter.

        Raises:
            TrackNotFoundError: If a track name does not resolve.
            DeviceNotFoundError: If a device name does not resolve.
            ParameterNotFoundError: If a parameter name does not resolve.
        """
        track_index = self._resolve_track(track)
        device_index = self._resolve_device(track_index, device)
        parameter_index = self._resolve_parameter(track_index, device_index, parameter)
        logger.info(
            "Setting track %d device %d parameter %d -> %s",
            track_index,
            device_index,
            parameter_index,
            value,
        )
        self._osc.send(
            "/live/device/set/parameter/value",
            track_index,
            device_index,
            parameter_index,
            float(value),
        )

    # ------------------------------------------------------------------ #
    # Sends (mixer routing)
    # ------------------------------------------------------------------ #
    def get_send(self, track: Ref, send_index: int) -> float:
        """Read a track's send level.

        Args:
            track: Track index or name.
            send_index: The send index (0 == the first return track, "A").

        Returns:
            The send level (0.0-1.0).

        Raises:
            TrackNotFoundError: If a track name does not resolve.
            OSCTimeoutError: If no reply arrives within the timeout.
        """
        track_index = self._resolve_track(track)
        # Reply: track, send_id, value.
        tail = self._request("/live/track/get/send", track_index, int(send_index), echo=2)
        return float(tail[0])

    def set_send(self, track: Ref, send_index: int, value: float) -> None:
        """Set a track's send level.

        Args:
            track: Track index or name.
            send_index: The send index (0 == the first return track, "A").
            value: The send level (0.0-1.0).

        Raises:
            TrackNotFoundError: If a track name does not resolve.
        """
        track_index = self._resolve_track(track)
        logger.info("Setting track %d send %d -> %s", track_index, send_index, value)
        self._osc.send("/live/track/set/send", track_index, int(send_index), float(value))

    # ------------------------------------------------------------------ #
    # Pitch helpers (respect this bridge's octave convention)
    # ------------------------------------------------------------------ #
    def pitch_to_name(self, pitch: int) -> str:
        """Convert a MIDI pitch to a name using this bridge's octave convention.

        Args:
            pitch: MIDI note number (0-127).

        Returns:
            The note name (e.g. ``"C3"``).
        """
        return pitch_to_name(pitch, self.middle_c_octave)

    def name_to_pitch(self, name: str) -> int:
        """Convert a note name to a MIDI pitch using this bridge's convention.

        Args:
            name: A note name in scientific notation (e.g. ``"C3"``).

        Returns:
            The MIDI note number (0-127).
        """
        return name_to_pitch(name, self.middle_c_octave)

    def make_note(
        self,
        pitch: Ref,
        start: float,
        duration: float,
        velocity: float = 100.0,
        mute: bool = False,
    ) -> Note:
        """Build a :class:`~ableton_bridge.notes.Note`, accepting a name or int pitch.

        Args:
            pitch: MIDI note number or a name such as ``"C3"`` (resolved with
                this bridge's octave convention).
            start: Start position in beats.
            duration: Note length in beats.
            velocity: MIDI velocity (0-127).
            mute: Whether the note is muted.

        Returns:
            A new :class:`~ableton_bridge.notes.Note`.
        """
        if isinstance(pitch, str):
            pitch = name_to_pitch(pitch, self.middle_c_octave)
        return Note(int(pitch), float(start), float(duration), float(velocity), bool(mute))
