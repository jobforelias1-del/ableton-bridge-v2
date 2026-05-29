# Known limitations

These are constraints of AbletonOSC (and OSC/UDP) that the bridge works around or exposes
honestly, rather than papering over. Read this before relying on the bridge in production.

## AbletonOSC version pinning

The OSC addresses and argument signatures used by this bridge were **read from the
AbletonOSC source**, not inferred. They were verified against:

- Repository: <https://github.com/ideoforms/AbletonOSC>
- Commit: **`0ca68214bd62c9b5cb641ca34006cfd70ba94430`** (2025-11-19)

Files read to verify the surface: `abletonosc/clip.py`, `abletonosc/clip_slot.py`,
`abletonosc/track.py`, `abletonosc/device.py`, `abletonosc/song.py`, `abletonosc/scene.py`,
`abletonosc/application.py`, `abletonosc/osc_server.py`, `abletonosc/handler.py`,
`abletonosc/constants.py`, and `manager.py` (for `/live/test`).

AbletonOSC adds and renames endpoints over time. If you run a different AbletonOSC build,
re-verify the addresses below before trusting them. Pin AbletonOSC to a known commit
alongside this bridge.

## Endpoints that do not exist as expected

- **No per-clip time signature.** `Clip` exposes no `signature_numerator` /
  `signature_denominator` over OSC at the pinned commit (only `Song` and `Scene` do —
  `/live/song/get/signature_numerator|denominator`, `/live/scene/get/time_signature_*`).
  Therefore `ClipInfo.time_signature` reports the **song** time signature as a documented
  best-effort fallback. If you need a true per-clip signature, it is not available over
  OSC at this version.

- **No note identity / in-place modify.** AbletonOSC has no endpoint to edit a note in
  place. `/live/clip/remove/notes` removes by **range** `(pitch_start, pitch_span,
  time_start, time_span)`, not by an id, and `/live/clip/get/notes` returns
  `pitch, start, duration, velocity, mute` (no id). The bridge therefore addresses a note
  by its `(pitch, start)` key and removes it with a narrow time window
  (`NOTE_MATCH_WINDOW = 1/256` beat) and a single-pitch span.

- **Send / return-track resolution by name is not available.** `/live/track/set/send`
  and `/live/track/get/send` address sends by **index** (0 = return A, 1 = return B, ...).
  AbletonOSC's track endpoints operate on `song.tracks`, which does not include return
  tracks, so there is no OSC call that maps a return-track *name* to a send index. The
  `configure_sends.py` example uses explicit send indices.

## Writes are unacknowledged (the source of v1's "silent failures")

AbletonOSC only sends a reply when a handler returns a value — i.e. for **reads**.
`set`, `create_clip`, `delete_clip`, `add/notes`, `remove/notes`, method calls, etc. are
**fire-and-forget**: there is no success reply, and — critically — **no error reply**.
If Live rejects an operation (audio track, occupied/group slot, out-of-range index), the
client sees nothing.

The bridge mitigates this by:

1. **Pre-validation.** MIDI operations check `/live/track/get/has_midi_input` first and
   raise `AudioTrackCannotHoldMidiError` rather than letting the write vanish.
2. **Idempotent + verified creation.** `create_clip` checks `has_clip` first (no-op if a
   clip exists) and, by default (`verify=True`), re-reads `has_clip` afterwards, raising
   `ClipNotFoundError` if the clip did not appear.
3. **Existence checks** before note writes (`ClipNotFoundError` if the slot is empty).

It cannot, however, confirm arbitrary `set` operations (e.g. `set_tempo`,
`set_parameter_value`) without a follow-up read. If you need certainty, read the value
back.

## `modify_notes` is atomic-as-possible, not transactional

Because there is no in-place modify, `modify_notes` performs, for each change, a
narrow-window remove of the old note and an add of the new note. To minimise the window
of inconsistency it sends **all removes plus a single batched add in one OSC bundle**
(one UDP datagram). AbletonOSC's `process_bundle` handles the contained messages **in
order**, so the guarantee is: *within the bundle, every remove is applied before the
batched add.*

Residual caveats:

- If the datagram is lost (UDP) or processing is interrupted mid-bundle, removed notes can
  be lost without their replacements being added. There is no rollback.
- Ordering across **separate** calls is only as reliable as UDP on loopback (in practice
  in-order, but not guaranteed by the protocol).
- `remove_notes` with multiple keys is likewise bundled; a single key is a lone message.

If you need stronger guarantees, read the clip back after a modify and reconcile.

## Octave convention (C3 vs C4)

MIDI 60 is labelled **C3** by Ableton Live but **C4** in strict scientific pitch notation.
The bridge defaults to Ableton's convention (`middle_c_octave=3`). Pass
`middle_c_octave=4` to `AbletonBridge` (or the `notes` helpers) for strict SPN. Pick one
convention and be consistent, or you will be an octave off.

## Transport / connection constraints

- **Single client per machine.** AbletonOSC replies to a fixed response port (11001). The
  bridge binds that port for receiving, so only one bridge (or other AbletonOSC client)
  can run against a given Live instance at a time.
- **Synchronous, serialized.** Requests are serialized by a lock; one request/reply
  completes before the next begins. The bridge is not designed for concurrent requests
  from multiple threads (concurrent replies on the same address cannot be disambiguated).
- **Large reads.** Replies are read with a 64 KiB datagram buffer. Extremely large clips
  (tens of thousands of notes) in a single `/live/clip/get/notes` reply could exceed this;
  read in pitch/time ranges if you hit that.
- **Loopback assumption.** Defaults target `127.0.0.1`. Remote use works but inherits
  UDP's lack of delivery/ordering guarantees.
