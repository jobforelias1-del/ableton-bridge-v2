"""List tracks and scenes and resolve them by name.

    python examples/name_resolution.py

Demonstrates name -> index resolution and audio-vs-MIDI detection, which the rest of the
API builds on (any track/scene argument accepts a name or an index).
"""

from __future__ import annotations

import logging

from ableton_bridge import AbletonBridge, OSCTimeoutError, TrackNotFoundError


def main() -> int:
    logging.basicConfig(level=logging.INFO)

    with AbletonBridge() as live:
        try:
            track_names = live.get_track_names()
            scene_names = live.get_scene_names()
        except OSCTimeoutError as exc:
            print(f"Timed out talking to AbletonOSC: {exc}")
            return 1

        print("Tracks:")
        for index, name in enumerate(track_names):
            kind = "MIDI " if live.track_has_midi_input(index) else "audio"
            print(f"  [{index}] {kind}  {name}")

        print("Scenes:")
        for index, name in enumerate(scene_names):
            print(f"  [{index}] {name}")

        # Resolve a name to an index (raises TrackNotFoundError if absent).
        if track_names:
            target = track_names[0]
            try:
                print(f"\nResolved track {target!r} -> index {live.get_track_index(target)}")
            except TrackNotFoundError as exc:
                print(exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
