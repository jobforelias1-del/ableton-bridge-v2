"""Connect to AbletonOSC and confirm Ableton Live is reachable.

Run with Ableton Live open and AbletonOSC enabled as a Control Surface:

    python examples/ping.py

Set ``--debug`` to see the raw OSC traffic.
"""

from __future__ import annotations

import argparse
import logging

from ableton_bridge import AbletonBridge, OSCTimeoutError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true", help="log OSC traffic at DEBUG")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    with AbletonBridge(host=args.host) as live:
        try:
            ok = live.ping()
        except OSCTimeoutError as exc:
            print(f"Could not reach AbletonOSC: {exc}")
            print("Is Ableton Live running with AbletonOSC enabled as a Control Surface?")
            return 1
        print(f"AbletonOSC reachable: {ok}")
        print(f"Ableton Live version: {live.get_live_version()}")
        print(f"Tempo: {live.get_tempo()} BPM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
