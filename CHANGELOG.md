# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-05-29

A ground-up rewrite of the AbletonOSC bridge. v2 keeps the same job — drive Ableton Live
over AbletonOSC — but fixes the rough edges that bit us in v1 and gives the wrapper a
clean, typed, tested public surface.

### Added
- **`AbletonBridge`**: a single high-level client class as the entry point, usable as a
  context manager, with dependency-injectable transport for testing.
- **Name → index resolution** for tracks, scenes, devices and parameters. Every
  track/scene/device/parameter argument now accepts an index **or** a name.
- **Typed exception hierarchy** rooted at `AbletonBridgeError`:
  `OSCTimeoutError`, `TrackNotFoundError`, `SceneNotFoundError`, `ClipNotFoundError`,
  `AudioTrackCannotHoldMidiError`, `DeviceNotFoundError`, `ParameterNotFoundError`.
- **`Note` dataclass** with scientific-notation conversion (`Note.from_name`, `.name`),
  and a configurable octave convention (`middle_c_octave`, default 3 = Ableton's C3).
- **Batched note writes**: `add_notes` sends all notes in a single OSC message.
- **Atomic-as-possible `modify_notes`**: remove-then-add issued as a single OSC **bundle**
  (one datagram, processed in order by AbletonOSC).
- **Device parameter read/write** (`get_parameter_value` / `set_parameter_value`),
  including resolving rack macros by name — used for `K_piano` and `S_808_clean` macro
  automation.
- **Send read/write** (`get_send` / `set_send`) for mixer send routing.
- **Structured `logging`**: INFO for production operations, DEBUG for all OSC traffic.
- **Test suite** (mock transport, no Ableton required) with >85% line coverage and a
  happy-path plus at least one failure-mode test per public method.
- **Docs**: `README.md`, this changelog, `KNOWN_LIMITATIONS.md`, and runnable `examples/`.

### Fixed (v1 issues)
- **Idempotent clip creation.** Re-creating an existing clip is now a no-op that returns
  `False`, instead of erroring or duplicating. `create_clip` also pre-checks the slot and
  (by default) post-verifies, since AbletonOSC does not acknowledge writes.
- **No more silent failures on audio tracks.** MIDI operations targeting an audio track
  now raise `AudioTrackCannotHoldMidiError` up front (via `has_midi_input`), rather than
  being dropped silently by Live.
- **Note `modify` ordering is defined.** v1 decomposed modify into a remove + add with a
  narrow window but left ordering and round-trips loose. v2 batches into a single bundle
  with a documented ordering guarantee (removes first, then a single batched add).
- **Robust request/reply.** The transport matches replies by OSC address and (where
  available) by echoed leading indices, drains stale datagrams before each request, and
  raises `OSCTimeoutError` on no reply instead of hanging.

### Known limitations
See `KNOWN_LIMITATIONS.md`. Headlines: AbletonOSC does not acknowledge writes; there is
no transactional note modify; there is no per-clip time signature endpoint
(`ClipInfo.time_signature` falls back to the song signature); and OSC addresses are
pinned to a specific AbletonOSC commit.
