"""Port of v1's send-routing: resolve source tracks by name and set their sends.

    python examples/configure_sends.py            # apply the routing below
    python examples/configure_sends.py --dry-run  # print what would change

AbletonOSC addresses sends by index (0 = return A, 1 = return B, ...); there is no OSC
call to map a return-track *name* to a send index (see KNOWN_LIMITATIONS.md), so the
routing table uses explicit send indices. Source tracks are resolved by name, which is
the part that made v1's routing fragile when tracks were reordered.
"""

from __future__ import annotations

import argparse
import logging

from ableton_bridge import AbletonBridge, OSCTimeoutError, TrackNotFoundError

# Send indices into the return tracks (0 = A = e.g. Reverb, 1 = B = e.g. Delay).
REVERB, DELAY = 0, 1

# Desired routing: source track name -> {send index: level in 0.0-1.0}.
ROUTING: dict[str, dict[int, float]] = {
    "K_piano": {REVERB: 0.25, DELAY: 0.10},
    "S_808_clean": {REVERB: 0.00, DELAY: 0.05},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, don't apply")
    parser.add_argument("--debug", action="store_true", help="log OSC traffic at DEBUG")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    with AbletonBridge() as live:
        for track_name, sends in ROUTING.items():
            try:
                track_index = live.get_track_index(track_name)
            except TrackNotFoundError as exc:
                print(f"Skipping: {exc}")
                continue
            except OSCTimeoutError as exc:
                print(f"Timed out talking to AbletonOSC: {exc}")
                return 1

            for send_index, level in sends.items():
                if args.dry_run:
                    current = live.get_send(track_index, send_index)
                    print(
                        f"{track_name} (track {track_index}) send {send_index}: "
                        f"{current:.3f} -> {level:.3f}"
                    )
                else:
                    live.set_send(track_index, send_index, level)
                    print(f"{track_name} (track {track_index}) send {send_index} = {level:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
