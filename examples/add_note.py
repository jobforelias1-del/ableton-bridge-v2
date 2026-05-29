"""Idempotently create a MIDI clip and add a C-major triad, then read it back.

    python examples/add_note.py --track K_piano --clip 0

The target track must be a MIDI track; the bridge refuses audio tracks. Re-running is
safe: ``create_clip`` is idempotent and the chord is added on top.
"""

from __future__ import annotations

import argparse
import logging

from ableton_bridge import (
    AbletonBridge,
    AudioTrackCannotHoldMidiError,
    Note,
    OSCTimeoutError,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", default="K_piano", help="track name or index")
    parser.add_argument("--clip", type=int, default=0, help="clip slot index")
    parser.add_argument("--debug", action="store_true", help="log OSC traffic at DEBUG")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    # A track name is passed straight through; an all-digit value is treated as an index.
    track: str | int = int(args.track) if args.track.isdigit() else args.track

    chord = [
        Note.from_name("C3", start=0.0, duration=1.0, velocity=100),
        Note.from_name("E3", start=0.0, duration=1.0, velocity=100),
        Note.from_name("G3", start=0.0, duration=1.0, velocity=100),
    ]

    with AbletonBridge() as live:
        try:
            created = live.create_clip(track, args.clip, length=4.0)
            print("Created new clip" if created else "Clip already existed (no-op)")
            live.add_notes(track, args.clip, chord)
            clip = live.read_clip(track, args.clip)
        except AudioTrackCannotHoldMidiError as exc:
            print(f"Refused: {exc}")
            return 1
        except OSCTimeoutError as exc:
            print(f"Timed out talking to AbletonOSC: {exc}")
            return 1

    numerator, denominator = clip.time_signature
    print(f"Clip {clip.name!r}: {clip.length} beats, {numerator}/{denominator}")
    for note in clip.notes:
        print(f"  {note.name:>3}  start={note.start}  dur={note.duration}  vel={note.velocity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
