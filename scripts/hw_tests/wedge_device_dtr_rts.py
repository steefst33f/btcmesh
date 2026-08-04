#!/usr/bin/env python3
"""Documented wedge-reproduction recipe (see project/plans/story_26_2.md):
rapidly toggling a device's DTR/RTS lines interrupts its boot sequence,
reliably reproducing a genuine mid-boot wedge - unlike a clean
disconnect/reconnect cycle, which does not.

Can be run against an idle port (device not otherwise connected) or
concurrently while another process holds the same port open, to test
whether that process notices/handles a wedge occurring mid-session.
Whether a concurrent open succeeds is platform/driver-dependent - if it
fails, stop whatever else holds the port first.

Usage:
    python scripts/hw_tests/wedge_device_dtr_rts.py /dev/cu.usbserial-0001
"""
import argparse
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Target device's serial port, e.g. /dev/cu.usbserial-0001")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--cycles", type=int, default=200, help="Number of DTR/RTS toggle cycles (default: 200)")
    args = parser.parse_args()

    print(f"Opening {args.port} for DTR/RTS toggle...")
    s = serial.Serial(args.port, args.baudrate, timeout=0.1)
    print(f"Opened OK. Toggling DTR/RTS rapidly ({args.cycles} cycles)...")
    for _ in range(args.cycles):
        s.setDTR(False)
        s.setRTS(True)
        time.sleep(0.01)
        s.setDTR(True)
        s.setRTS(False)
        time.sleep(0.01)
    s.close()
    print("Done toggling, closed our handle.")


if __name__ == "__main__":
    main()
