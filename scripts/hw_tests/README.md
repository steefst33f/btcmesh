# Real-Hardware Test Scripts

Ad-hoc scripts for manually verifying behavior against real Meshtastic
devices and the Story 26.7 DIY relay board - things that can't be
exercised by the mocked unit test suite (genuine device wedges, real
power cycles, real send timeouts).

These are not run automatically anywhere. They exist so a real-hardware
test done once (e.g. while investigating a bug or verifying a fix) can
be re-run later without having to reconstruct the script from scratch.

## Scripts

- **`power_cycle_device.py`** - fires a single relay power-cycle
  directly (bypassing `DeviceWatchdog`), for deterministically putting a
  device into a "just went offline" state.
- **`wedge_device_dtr_rts.py`** - the documented DTR/RTS toggle recipe
  (see `project/plans/story_26_2.md`) that reliably reproduces a genuine
  mid-boot device wedge, as opposed to a clean disconnect/reconnect.
- **`send_timeout_test.py`** - connects to a device, cuts its power via
  the relay, then calls `transport.send()` against the now-dead
  connection and times how long it takes / confirms it raises
  `TransportSendError` instead of hanging (Story 28.1 / Issue 21).

All scripts take the relevant serial port(s) as command-line arguments
(no hardcoded paths) - use `python <script>.py --help` for usage; the
right port names to use are almost always different per machine/session,
found via:

```bash
python -c "
from core.meshtastic_utils import scan_meshtastic_devices_detailed
for d in scan_meshtastic_devices_detailed():
    print(d)
"
```
