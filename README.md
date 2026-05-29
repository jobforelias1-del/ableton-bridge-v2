# ableton-bridge v2

A clean, typed Python wrapper around [AbletonOSC](https://github.com/ideoforms/AbletonOSC)
for driving Ableton Live over OSC. Used in production at Silicon Click to create and edit
MIDI clips, resolve tracks/scenes by name, and automate rack-macro and send parameters.

AbletonOSC is a Live "User Remote Script" that exposes Live's Object Model over OSC on
UDP `127.0.0.1:11000` (Live listens) / `11001` (Live replies). This library is the
client side: it speaks that protocol and adds the safety and ergonomics that scripting a
real set needs.

> **v2 highlights:** idempotent clip creation, audio-track refusal instead of silent
> failure, batched note writes, an atomic-as-possible note `modify`, name → index
> resolution, a typed exception hierarchy, and structured logging. See
> [`CHANGELOG.md`](CHANGELOG.md) and [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

---

## Install

```bash
# In Ableton Live: install AbletonOSC and select it as a Control Surface first.
#   (Preferences -> Link/Tempo/MIDI -> Control Surface -> AbletonOSC)
# See KNOWN_LIMITATIONS.md for the AbletonOSC version this release was verified against.

pip install -e .          # from a checkout of this repo
# or, with dev tooling (pytest, ruff, black):
pip install -e ".[dev]"
```

Requires Python 3.10+. The only runtime dependency is
[`python-osc`](https://pypi.org/project/python-osc/).

---

## Quick start

```python
import logging
from ableton_bridge import AbletonBridge, Note

logging.basicConfig(level=logging.INFO)  # INFO = ops; set DEBUG to see OSC traffic

with AbletonBridge() as live:           # 127.0.0.1, send 11000 / receive 11001
    # 1. Is Live reachable?
    assert live.ping()                  # raises OSCTimeoutError if not
    print("Live version:", live.get_live_version())

    # 2. Tempo / transport
    live.set_tempo(120.0)

    # 3. Add a note. Tracks may be referenced by name or index.
    #    create_clip is idempotent: safe to re-run, a no-op if the clip exists.
    live.create_clip("K_piano", clip_index=0, length=4.0)
    live.add_notes("K_piano", 0, [Note.from_name("C3", start=0.0, duration=1.0, velocity=100)])

    # 4. Read it back (pitches expose scientific notation via Note.name)
    clip = live.read_clip("K_piano", 0)
    print(clip.name, clip.length, [n.name for n in clip.notes])
```

If Live is not running (or AbletonOSC is not enabled), the first call that expects a
reply raises `OSCTimeoutError` after `timeout` seconds (default 5).

---

## Octave convention (C3 vs C4) — read this

Pitch is a raw MIDI integer on the wire. Names are converted by this library:

* **Default (`middle_c_octave=3`):** MIDI 60 = **C3** — matches Ableton Live's on-screen
  labelling. This is the default because the bridge wraps Ableton.
* **Strict scientific pitch notation (`middle_c_octave=4`):** MIDI 60 = C4.

```python
AbletonBridge(middle_c_octave=4)   # if you prefer SPN everywhere
live.pitch_to_name(60)             # -> "C3" (default) / "C4" (middle_c_octave=4)
Note.from_name("C4", 0, 1, middle_c_octave=4).pitch   # -> 60
```

---

## Public API reference

Construct `AbletonBridge(host="127.0.0.1", send_port=11000, receive_port=11001,
timeout=5.0, *, transport=None, middle_c_octave=3)`. It is a context manager
(`with AbletonBridge() as live: ...`) and has a `close()` method. Inject `transport=` to
unit-test against a fake (see `tests/`).

### System
| Method | Returns | Notes |
| --- | --- | --- |
| `ping()` | `bool` | Sends `/live/test`; `True` on `ok`. |
| `get_live_version()` | `(major, minor)` | |
| `show_message(text)` | `None` | Status-bar message in Live. |

### Song / transport
| Method | Returns |
| --- | --- |
| `get_tempo()` / `set_tempo(bpm)` | `float` / `None` |
| `is_playing()` | `bool` |
| `start_playing()` / `stop_playing()` / `continue_playing()` | `None` |
| `get_time_signature()` / `set_time_signature(num, den)` | `(int, int)` / `None` |

### Name resolution
| Method | Returns |
| --- | --- |
| `get_track_names()` | `list[str]` |
| `get_track_index(name)` | `int` — raises `TrackNotFoundError` |
| `get_scene_names()` | `list[str]` |
| `get_scene_index(name)` | `int` — raises `SceneNotFoundError` |
| `fire_scene(scene)` | `None` — index or name |
| `track_has_midi_input(track)` | `bool` — `False` for audio tracks |

Anywhere a `track`, `scene`, `device` or `parameter` is accepted, you may pass an integer
index or a name (string).

### Clips
| Method | Returns | Notes |
| --- | --- | --- |
| `has_clip(track, clip_index)` | `bool` | |
| `create_clip(track, clip_index, length=4.0, *, verify=True)` | `bool` | **Idempotent.** `True` if created, `False` if it already existed. Refuses audio tracks. |
| `delete_clip(track, clip_index)` | `None` | |
| `read_clip(track, clip_index)` | `ClipInfo` | name, length, notes, time signature. Raises `ClipNotFoundError`. |
| `get_notes(track, clip_index)` | `list[Note]` | Raises `ClipNotFoundError`. |

`ClipInfo` is a dataclass: `track_index, clip_index, name, length, notes, time_signature`.
(`time_signature` is the **song** signature — see Known limitations.)

### Notes (write)
| Method | Notes |
| --- | --- |
| `add_notes(track, clip_index, notes)` | All notes sent in **one** `/live/clip/add/notes` message (a single round-trip). |
| `remove_notes(track, clip_index, keys)` | `keys` are `(pitch, start)` tuples or `Note`s. Removed by a narrow time window; multiple keys go in one OSC bundle. |
| `modify_notes(track, clip_index, changes)` | `changes` are `(old_key, new_note)` pairs. Remove-then-add in **one OSC bundle** (atomic-as-possible — see Known limitations). |

All three refuse audio tracks (`AudioTrackCannotHoldMidiError`) and require an existing
clip (`ClipNotFoundError`).

### `Note`
`Note(pitch, start, duration, velocity=100.0, mute=False)` — a frozen dataclass.
`Note.from_name("C3", start, duration, ...)`, the `.name` property, and `.key()`
(`(pitch, start)`) are provided. `AbletonBridge.make_note("C3", start, duration, ...)`
builds one using the bridge's octave convention.

### Devices / parameters (rack-macro automation)
| Method | Returns |
| --- | --- |
| `get_device_names(track)` | `list[str]` |
| `get_device_index(track, name)` | `int` — raises `DeviceNotFoundError` |
| `get_parameter_names(track, device)` | `list[str]` |
| `get_parameter_index(track, device, name)` | `int` — raises `ParameterNotFoundError` |
| `get_parameter_value(track, device, parameter)` | `float` |
| `set_parameter_value(track, device, parameter, value)` | `None` |

### Sends
| Method | Returns |
| --- | --- |
| `get_send(track, send_index)` | `float` |
| `set_send(track, send_index, value)` | `None` |

### Exceptions
All derive from `AbletonBridgeError`:
`OSCTimeoutError`, `TrackNotFoundError`, `SceneNotFoundError`, `ClipNotFoundError`,
`AudioTrackCannotHoldMidiError`, `DeviceNotFoundError`, `ParameterNotFoundError`.

### Logging
The library logs under the `ableton_bridge` logger tree. Production operations log at
**INFO**; every OSC send/request/reply logs at **DEBUG** (`ableton_bridge.osc`). The
library installs no handlers — configure logging in your application.

---

## Examples

Runnable scripts in [`examples/`](examples/) (each needs a live Ableton + AbletonOSC):

* `ping.py` — connect and confirm reachability.
* `add_note.py` — idempotent clip creation + a chord, read back.
* `name_resolution.py` — list and resolve tracks/scenes by name.
* `configure_sends.py` — a port of v1's send-routing: resolve tracks by name and set sends.

---

## Known limitations

A short list (full detail in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)):

* **Audio tracks cannot hold MIDI.** The bridge refuses up front rather than failing
  silently like raw AbletonOSC.
* **Writes are unacknowledged.** AbletonOSC sends no reply (and no error) for
  set/create/add/remove. The bridge pre-validates and, for `create_clip`, post-verifies.
* **`modify` is not transactional.** AbletonOSC has no in-place modify; the bridge does
  remove-then-add in a single bundle, which is atomic-as-possible but not guaranteed.
* **No per-clip time signature** is exposed by AbletonOSC; `ClipInfo.time_signature`
  reports the **song** signature as a documented fallback.
* **Version pinning.** OSC addresses are verified against a specific AbletonOSC commit.

## Development

```bash
pip install -e ".[dev]"
pytest --cov=ableton_bridge --cov-report=term-missing   # tests run with a mock transport
ruff check .
black --check .
```

The test suite mocks the OSC transport, so it needs **no** running Ableton Live.

## License

MIT.
