#!/usr/bin/env python3
"""Fire a single relay power-cycle directly, bypassing DeviceWatchdog -
for deterministically putting a device into a "just went offline" state
(e.g. to test a running server/client's own wedge detection against it).

Usage:
    python scripts/hw_tests/power_cycle_device.py /dev/cu.wchusbserial21340
    python scripts/hw_tests/power_cycle_device.py /dev/cu.wchusbserial21340 --channel 2 --off-seconds 20
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from transport.power_control import SerialRelayPowerControl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("relay_port", help="Relay board's serial port, e.g. /dev/cu.wchusbserial21340")
    parser.add_argument("--channel", type=int, default=1, help="Relay channel (default: 1)")
    parser.add_argument("--off-seconds", type=float, default=15.0, help="How long to cut power (default: 15)")
    args = parser.parse_args()

    pc = SerialRelayPowerControl(args.relay_port, args.channel)
    print(f"Cutting power for {args.off_seconds}s...")
    pc.power_cycle(off_seconds=args.off_seconds)
    print("power_cycle() returned - relay confirmed OK.")


if __name__ == "__main__":
    main()
