#!/usr/bin/env python3
"""Real-hardware test for Story 28.1's send() timeout fix (Issue 21).

Connects to a real device, cuts its power via the relay (a reliable way
to put it into an unresponsive state - see Issue 20's findings), then
immediately calls transport.send() against the now-dead connection and
times how long it takes / confirms it raises TransportSendError instead
of hanging.

Usage:
    python scripts/hw_tests/send_timeout_test.py /dev/cu.usbserial-0001 /dev/cu.wchusbserial21340
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportSendError
from transport.power_control import SerialRelayPowerControl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh_port", help="Meshtastic device's serial port, e.g. /dev/cu.usbserial-0001")
    parser.add_argument("relay_port", help="Relay board's serial port, e.g. /dev/cu.wchusbserial21340")
    parser.add_argument("--channel", type=int, default=1, help="Relay channel (default: 1)")
    parser.add_argument("--off-seconds", type=float, default=15.0, help="How long to cut power (default: 15)")
    args = parser.parse_args()

    print(f"Connecting to {args.mesh_port} ...")
    transport = MeshtasticSerialTransport()
    transport.connect(args.mesh_port)
    print(f"Connected. local_node_id={transport.local_node_id}")

    pc = SerialRelayPowerControl(args.relay_port, args.channel)
    print(f"Cutting power for {args.off_seconds}s (device will go dark)...")
    pc.power_cycle(off_seconds=args.off_seconds)
    print("power_cycle() returned - relay confirmed OK. Device should now be gone/unresponsive.")

    print(f"Calling transport.send() against the now-dead connection "
          f"(timeout bound: {transport._SEND_TIMEOUT_SECONDS}s)...")
    t0 = time.time()
    try:
        transport.send("test message from send-timeout hw test", "!ffffffff")
        print(f"UNEXPECTED: send() returned normally after {time.time()-t0:.1f}s")
    except TransportSendError as e:
        elapsed = time.time() - t0
        print(f"send() raised TransportSendError after {elapsed:.1f}s: {e}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"send() raised unexpected {type(e).__name__} after {elapsed:.1f}s: {e}")

    transport.disconnect()
    print("Done, disconnected.")


if __name__ == "__main__":
    main()
