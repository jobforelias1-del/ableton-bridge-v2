"""A faithful in-memory AbletonOSC fake used across the bridge tests.

The bridge talks to a transport with three methods: ``request``, ``send`` and
``send_bundle``. :class:`FakeAbleton` implements that interface against an
in-memory song model, reproducing the exact reply shapes read from the pinned
AbletonOSC source (commit 0ca6821):

* reads reply with the echoed leading indices, then the value(s);
* writes (set / create / delete / add / remove) are fire-and-forget and mutate
  state with no reply -- mirroring AbletonOSC, where a failed write is silent;
* bundles are processed message-by-message, in order.

This lets the bridge tests exercise real round-trip behaviour (idempotent clip
creation, narrow-window note removal, remove-then-add modify) without a running
Ableton Live.
"""

from __future__ import annotations

from ableton_bridge import AbletonBridge
from ableton_bridge.exceptions import OSCTimeoutError


class FakeClip:
    """An in-memory MIDI clip."""

    def __init__(self, name: str = "", length: float = 4.0) -> None:
        self.name = name
        self.length = length
        # Each note is [pitch, start, duration, velocity, mute].
        self.notes: list[list] = []


class FakeDevice:
    """An in-memory device with named parameters."""

    def __init__(self, name: str, parameters: list[tuple]) -> None:
        self.name = name
        # Each parameter is [name, value].
        self.parameters: list[list] = [[n, v] for n, v in parameters]


class FakeTrack:
    """An in-memory track."""

    def __init__(
        self,
        name: str,
        has_midi_input: bool = True,
        devices: list[FakeDevice] | None = None,
        num_sends: int = 2,
    ) -> None:
        self.name = name
        self.has_midi_input = has_midi_input
        self.devices = devices or []
        self.sends = [0.0] * num_sends
        self.clip_slots: dict[int, FakeClip] = {}


class FakeAbleton:
    """A faithful, in-memory stand-in for an AbletonOSC server."""

    def __init__(
        self,
        tracks: list[FakeTrack] | None = None,
        scenes: list[str] | None = None,
        tempo: float = 120.0,
        signature=(4, 4),
        is_playing: bool = False,
        version=(12, 1),
    ) -> None:
        self.tracks = tracks if tracks is not None else [FakeTrack("default")]
        self.scenes = scenes if scenes is not None else ["Intro", "Verse", "Chorus"]
        self.tempo = tempo
        self.signature = list(signature)
        self.is_playing = is_playing
        self.version = version
        # Set False to simulate Live silently rejecting create_clip.
        self.create_clip_enabled = True
        # Recorded traffic, for assertions.
        self.sent: list[tuple] = []
        self.bundles: list[list[tuple]] = []
        self.messages: list[str] = []
        self.closed = False

    # -- transport interface ------------------------------------------- #
    def request(self, address: str, *args, match_leading=()) -> list:
        """Return the reply AbletonOSC would send for a read address."""
        handler = self._read_handlers().get(address)
        if handler is None:
            raise OSCTimeoutError(f"FakeAbleton has no read handler for {address}")
        return handler(list(args))

    def send(self, address: str, *args) -> None:
        """Apply a fire-and-forget write."""
        self.sent.append((address, tuple(args)))
        self._apply_write(address, list(args))

    def send_bundle(self, messages) -> None:
        """Apply a bundle of writes in order (as AbletonOSC processes them)."""
        materialised = [(address, tuple(args)) for address, args in messages]
        self.bundles.append(materialised)
        for address, args in materialised:
            self.sent.append((address, tuple(args)))
            self._apply_write(address, list(args))

    def close(self) -> None:
        """Mark the transport closed."""
        self.closed = True

    # -- reads ---------------------------------------------------------- #
    def _read_handlers(self):
        return {
            "/live/test": lambda a: ["ok"],
            "/live/application/get/version": lambda a: [self.version[0], self.version[1]],
            "/live/song/get/tempo": lambda a: [self.tempo],
            "/live/song/get/is_playing": lambda a: [self.is_playing],
            "/live/song/get/signature_numerator": lambda a: [self.signature[0]],
            "/live/song/get/signature_denominator": lambda a: [self.signature[1]],
            "/live/song/get/track_names": lambda a: [t.name for t in self.tracks],
            "/live/song/get/scenes/name": lambda a: list(self.scenes),
            "/live/track/get/has_midi_input": self._get_has_midi_input,
            "/live/track/get/devices/name": self._get_device_names,
            "/live/track/get/send": self._get_send,
            "/live/clip_slot/get/has_clip": self._get_has_clip,
            "/live/clip/get/name": self._get_clip_name,
            "/live/clip/get/length": self._get_clip_length,
            "/live/clip/get/notes": self._get_notes,
            "/live/device/get/parameters/name": self._get_parameter_names,
            "/live/device/get/parameter/value": self._get_parameter_value,
        }

    def _get_has_midi_input(self, args):
        track_index = int(args[0])
        return [track_index, self.tracks[track_index].has_midi_input]

    def _get_device_names(self, args):
        track_index = int(args[0])
        return [track_index] + [d.name for d in self.tracks[track_index].devices]

    def _get_send(self, args):
        track_index, send_index = int(args[0]), int(args[1])
        return [track_index, send_index, self.tracks[track_index].sends[send_index]]

    def _get_has_clip(self, args):
        track_index, clip_index = int(args[0]), int(args[1])
        has = clip_index in self.tracks[track_index].clip_slots
        return [track_index, clip_index, has]

    def _clip(self, args) -> FakeClip:
        track_index, clip_index = int(args[0]), int(args[1])
        slots = self.tracks[track_index].clip_slots
        if clip_index not in slots:
            # AbletonOSC would error server-side and send no reply -> timeout.
            raise OSCTimeoutError(f"No clip at track {track_index} slot {clip_index}")
        return slots[clip_index]

    def _get_clip_name(self, args):
        return [int(args[0]), int(args[1]), self._clip(args).name]

    def _get_clip_length(self, args):
        return [int(args[0]), int(args[1]), self._clip(args).length]

    def _get_notes(self, args):
        track_index, clip_index = int(args[0]), int(args[1])
        clip = self._clip(args)
        flat: list = []
        for pitch, start, duration, velocity, mute in clip.notes:
            flat += [pitch, start, duration, velocity, mute]
        return [track_index, clip_index] + flat

    def _get_parameter_names(self, args):
        track_index, device_index = int(args[0]), int(args[1])
        device = self.tracks[track_index].devices[device_index]
        return [track_index, device_index] + [p[0] for p in device.parameters]

    def _get_parameter_value(self, args):
        track_index, device_index, parameter_index = int(args[0]), int(args[1]), int(args[2])
        device = self.tracks[track_index].devices[device_index]
        return [
            track_index,
            device_index,
            parameter_index,
            device.parameters[parameter_index][1],
        ]

    # -- writes --------------------------------------------------------- #
    def _apply_write(self, address: str, args: list) -> None:
        if address == "/live/song/set/tempo":
            self.tempo = args[0]
        elif address == "/live/song/start_playing":
            self.is_playing = True
        elif address == "/live/song/stop_playing":
            self.is_playing = False
        elif address == "/live/song/continue_playing":
            self.is_playing = True
        elif address == "/live/song/set/signature_numerator":
            self.signature[0] = args[0]
        elif address == "/live/song/set/signature_denominator":
            self.signature[1] = args[0]
        elif address == "/live/api/show_message":
            self.messages.append(args[0])
        elif address == "/live/track/set/send":
            track_index, send_index, value = int(args[0]), int(args[1]), args[2]
            self.tracks[track_index].sends[send_index] = value
        elif address == "/live/device/set/parameter/value":
            track_index, device_index, parameter_index, value = (
                int(args[0]),
                int(args[1]),
                int(args[2]),
                args[3],
            )
            self.tracks[track_index].devices[device_index].parameters[parameter_index][1] = value
        elif address == "/live/scene/fire":
            pass
        elif address == "/live/clip_slot/create_clip":
            self._create_clip(args)
        elif address == "/live/clip_slot/delete_clip":
            self.tracks[int(args[0])].clip_slots.pop(int(args[1]), None)
        elif address == "/live/clip/add/notes":
            self._add_notes(args)
        elif address == "/live/clip/remove/notes":
            self._remove_notes(args)
        # Any other write is accepted silently, like AbletonOSC.

    def _create_clip(self, args):
        track_index, clip_index, length = int(args[0]), int(args[1]), args[2]
        track = self.tracks[track_index]
        # AbletonOSC silently does nothing for audio tracks, occupied slots, or
        # when create is disabled (our hook to simulate Live rejecting it).
        if not self.create_clip_enabled or not track.has_midi_input:
            return
        if clip_index in track.clip_slots:
            return
        track.clip_slots[clip_index] = FakeClip(name="", length=length)

    def _add_notes(self, args):
        track_index, clip_index = int(args[0]), int(args[1])
        clip = self.tracks[track_index].clip_slots[clip_index]
        rest = args[2:]
        for offset in range(0, len(rest), 5):
            pitch, start, duration, velocity, mute = rest[offset : offset + 5]
            clip.notes.append(
                [int(pitch), float(start), float(duration), float(velocity), bool(mute)]
            )

    def _remove_notes(self, args):
        track_index, clip_index = int(args[0]), int(args[1])
        pitch_start, pitch_span, time_start, time_span = args[2], args[3], args[4], args[5]
        clip = self.tracks[track_index].clip_slots[clip_index]
        kept = []
        for note in clip.notes:
            pitch, start = note[0], note[1]
            in_pitch = pitch_start <= pitch < pitch_start + pitch_span
            in_time = time_start <= start < time_start + time_span
            if not (in_pitch and in_time):
                kept.append(note)
        clip.notes = kept


class FailingTransport:
    """A transport whose every operation raises, for failure-mode tests."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or OSCTimeoutError("simulated transport failure")

    def request(self, address, *args, match_leading=()):
        raise self.exc

    def send(self, address, *args):
        raise self.exc

    def send_bundle(self, messages):
        raise self.exc

    def close(self):
        pass


def default_song() -> FakeAbleton:
    """A default song: MIDI tracks 'K_piano' (with a macro rack) and
    'S_808_clean', plus an audio track 'Vocals'."""
    rack = FakeDevice("K_piano", [("Macro 1", 0.0), ("Macro 2", 0.5), ("Volume", 1.0)])
    tracks = [
        FakeTrack("K_piano", has_midi_input=True, devices=[rack], num_sends=2),
        FakeTrack("S_808_clean", has_midi_input=True, num_sends=2),
        FakeTrack("Vocals", has_midi_input=False, num_sends=2),  # audio track
    ]
    return FakeAbleton(tracks=tracks, scenes=["Intro", "Verse", "Chorus"])


def make_bridge(fake: FakeAbleton) -> AbletonBridge:
    """Build a bridge wired to a :class:`FakeAbleton`."""
    return AbletonBridge(transport=fake)
