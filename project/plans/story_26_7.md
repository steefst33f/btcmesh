# Story 26.7 Implementation Plan: DIY Relay-Based Power Control (ESP32/ESP8266)

## Context

**Why this change:**
EPIC 5 (Device Power-Cycle Recovery/Watchdog, see `project/plans/story_26_1.md`)
exists so a BTC Mesh Relay server can recover automatically from a wedged
Meshtastic USB device (Issue 12/16) without a human physically
unplugging/replugging it — important for anyone running the relay server
unattended who wants it to stay available and ready to receive incoming
transactions.

Story 26.1 built `UhubctlPowerControl` to do this via software-controlled
USB hub port power switching. Real-hardware testing found a real,
documented limitation of that approach (see `project/issues.txt` Issue
19): `uhubctl` can report a successful power-off, and the hub's own status
register can even reflect it, while the device never actually loses power
— many hub controller chips advertise power-switching support in their USB
descriptor without the PCB having a physical load switch wired to the
downstream VBUS line. This was confirmed directly by physically watching
connected devices' status LEDs stay lit through a held "off" state, on two
different hubs (one bus-powered, one with its own independent power
supply) in a real test setup — neither actually cut power, despite both
reporting success. Whether a given hub genuinely works can't be assumed;
it has to be individually verified, and suitable independently-verified
replacement hubs can be expensive or hard to reliably source.

**Goal:** offer a power-cycle mechanism that works regardless of what hub
an operator has, by not depending on the hub at all. A small microcontroller
(ESP32 or ESP8266, e.g. a NodeMCU V2 - either works, see below), wired to a
small relay module, physically interrupts a Meshtastic device's own USB
**VBUS wire only** (data lines untouched), driven over a serial command
from the host.

**Outcome:** `SerialRelayPowerControl` (implementing the existing
`BasePowerControl` ABC from Story 26.1, alongside `UhubctlPowerControl`)
talks over a serial connection to a companion microcontroller running
custom firmware, which drives a relay module to cut/restore power to a
Meshtastic device. This gives any operator — regardless of their USB hub
— a verified, hardware-independent way to recover a wedged device
automatically, which is what actually keeps a relay server (or client)
available to send/receive transactions. Confirmed on real hardware, this
time with an actual LED-off check (not just software signals) as the
acceptance bar, given what Story 26.1's testing revealed.

Note on channel count: the server and client each run on their own
machine in a typical deployment, each managing a single local Meshtastic
device, so **one relay channel per machine is the normal case**. The
protocol and firmware support multiple channels from one ESP32 (useful if
someone runs several Meshtastic devices from a single machine, e.g. a
local development/test setup), but that's the exception, not the
default — see the shopping list and Key Design Decisions below.

---

## Architecture

```
transport/power_control.py   (existing file from Story 26.1)
├── PowerControlError                  (existing, reused)
├── BasePowerControl                   (existing ABC, reused)
├── UhubctlPowerControl                (existing — kept; valid for anyone
│                                        who has verified their hub supports
│                                        real VBUS switching)
└── SerialRelayPowerControl (NEW)      — talks to the ESP32 over pyserial

core/config_loader.py (existing file)
└── get_relay_serial_port(), load_relay_serial_baud()   (NEW getters)

hardware/                    (NEW, non-Python)
└── power_relay_firmware/
    ├── platformio.ini       — PlatformIO project file (build/flash from
    │                          VS Code, no Arduino IDE needed)
    ├── .gitignore           — excludes PlatformIO's .pio/ build cache
    └── src/
        └── power_relay.ino  — Arduino-framework firmware (ESP32/ESP8266)
```

### Serial protocol (host ↔ ESP32)

Plain text lines, one command/response pair per power cycle:

```
→ CYCLE <channel> <off_seconds>\n     e.g. "CYCLE 1 15\n"
← OK\n                                 (relay cycled successfully)
← ERR <reason>\n                       (bad channel, bad command, etc.)
```

`SerialRelayPowerControl` is instantiated **per channel** (one instance per
Meshtastic device), mirroring how `UhubctlPowerControl` is already
constructed per hub/port — e.g. `SerialRelayPowerControl(port="/dev/tty...",
channel=1)`. `power_cycle(off_seconds)` writes the `CYCLE` line, blocks for
the ESP32's line response (with a read timeout comfortably longer than
`off_seconds`), and raises `PowerControlError` on `ERR`, timeout, or any
`pyserial` exception.

### Physical wiring (per device being controlled)

- A cheap USB extension/pass-through cable is cut open; only the **VBUS
  (red) wire** is spliced through one channel of the relay module's
  NO/COM contacts. GND/D+/D- (black/white/green) are spliced straight
  through, untouched.
- Relay module IN pin(s) ← ESP32 GPIO pin(s), one per device being
  controlled from that machine (typically just one, per the note above).
- Relay module VCC/GND ← the board's own 5V/GND pins, so the relay module
  runs off the same USB power as the microcontroller itself - no separate
  PSU needed. **Which pin actually carries 5V varies by board**: on
  several NodeMCU (ESP8266) clones, `VIN` is only a regulator *input* for
  external 5-12V and does **not** reflect the USB rail, while a separate
  `VU` pin (where present) is the true USB-5V passthrough - verify with a
  multimeter rather than assume either name is correct for a given board.
  Either way, the microcontroller itself must stay continuously powered
  from a **separate, unswitched** USB port on the host — it must never be
  on a circuit it itself can cut.
- The relay's COM side connects to whatever "always-on" 5V the device
  already gets today from its upstream hub/port; NO side connects onward
  to the device. This makes the DIY relay the *only* power switch that
  matters — whatever the upstream hub does or doesn't support becomes
  irrelevant.

### Firmware (`power_relay.ino`)

Arduino-framework sketch. Uses only plain Arduino core APIs
(`Serial`/`pinMode`/`digitalWrite`), nothing platform-specific, so it
builds for either an **ESP32** or an **ESP8266** board (e.g. a NodeMCU
V2) — just select the matching board profile in the Arduino IDE before
flashing. Default GPIO pins are chosen per-platform automatically via
`#if defined(ARDUINO_ARCH_ESP32) / ARDUINO_ARCH_ESP8266` (NodeMCU uses
D1/D2 - GPIO5/GPIO4 - which have no boot-mode constraints, unlike
D0/D3/D4/D8), overridable if wired differently. Reads lines from
`Serial`, parses `CYCLE <channel> <seconds>`, drives the
matching GPIO through the module's trigger level (most cheap relay
modules are **active-LOW** — verify against the actual module once
bought; kept as a single `#define ACTIVE_LOW` flag for an easy flip) low
for `<seconds>`, then high, then writes `OK`. Malformed commands or an
out-of-range channel get `ERR <reason>`. A blocking `delay()` for the
off-duration is fine here — the host's own `power_cycle()` call blocks for
the same duration anyway (matches `UhubctlPowerControl`'s existing
behavior/interface contract). The firmware supports more than one channel
(useful for a multi-device machine), but a single-device machine only
needs one wired up — the second GPIO simply goes unused.

### Why the host never auto-detects the relay's serial port

`core/meshtastic_utils.py::scan_meshtastic_devices()` filters ports by a
small **blacklist** of known non-Meshtastic VIDs, not a whitelist — a
commodity ESP32/ESP8266 dev board's VID (CP2102 `0x10C4`, CH340 `0x1A86` -
common on both, including most NodeMCU boards - or ESP32's native USB
`0x303A`) isn't in that blacklist, so it would show up as a false
"Meshtastic candidate" if the relay were ever auto-scanned for. To avoid
this, `SerialRelayPowerControl`'s port is **always** explicit — a new
`RELAY_SERIAL_PORT` env var, never auto-detected — and nothing in this
story touches `scan_meshtastic_devices()` at all.

### Explicit non-goal

Wiring this into `DeviceWatchdog` is Story 26.4/26.5/26.6 (not yet built).
This story only builds and hardware-verifies the standalone
`SerialRelayPowerControl` backend, matching how Story 26.1 was scoped.

---

## Implementation Steps

1. **Firmware** — write `hardware/power_relay_firmware/src/power_relay.ino`
   (plus a `platformio.ini` alongside it for building/flashing from VS
   Code's PlatformIO extension, no Arduino IDE needed) implementing the
   protocol above. Supports both ESP32 and ESP8266
   (e.g. NodeMCU V2) boards via `#if defined(ARDUINO_ARCH_...)`; GPIO
   pin numbers are `#define` constants with per-platform defaults,
   overridable if wired differently.
2. **`transport/power_control.py`** — add `SerialRelayPowerControl`, using
   `pyserial` directly (`import serial`), matching `UhubctlPowerControl`'s
   existing error-wrapping conventions (`PowerControlError` on
   `serial.SerialException`, `OSError`, timeout, or an `ERR` response).
3. **`requirements.txt`** — add `pyserial` explicitly (currently only a
   transitive dependency via `meshtastic`).
4. **`core/config_loader.py`** — add `get_relay_serial_port()` (mirrors
   `get_meshtastic_serial_port()`) and a baud-rate getter (mirrors
   `load_reassembly_timeout()`'s int-with-default-and-logging pattern).
5. **`tests/test_power_control.py`** — new test class for
   `SerialRelayPowerControl`, patching `transport.power_control.serial.Serial`
   (module-qualified, matching the existing `subprocess.run` patch style):
   command formatting, `OK`/`ERR`/timeout/exception handling.
6. **Physical build** — shopping list below, wire per the Architecture
   section.
7. **Real hardware verification** — flash the firmware, wire it up, run
   `power_cycle()` against each channel, and **physically confirm the LED
   actually goes dark** (the check that caught Issue 19's gap in the first
   place) before declaring success. Confirm re-enumeration/reconnect
   afterward the same way Story 26.1's verification did.
8. **Update docs** — mark Issue 19 resolved and update
   `project/plans/story_26_1.md` once hardware-verified.

### Shopping list (cheap, no special hardware required beyond a dev board)

For the normal case — a single Meshtastic device on this machine (e.g. a
server or client each on its own host):

- 1× ESP32 **or** ESP8266 dev board (e.g. a NodeMCU V2) — any variant with
  enough free GPIO pins; the firmware's pin numbers are `#define`
  constants with sensible per-platform defaults, adjustable if wired
  differently
- 1× single-channel **5V** relay module (~$2-5, ubiquitous on Amazon/AliExpress
  — no specific brand required, but check the relay coil's rated VCC before
  buying: many cheap "HW-xxx" modules are 12V-coil boards (e.g. the HW-307),
  which need a separate power supply for the coil - a 5V-VCC module (e.g.
  the HW-482) runs entirely off the same USB 5V as the microcontroller
  board, no extra PSU needed. Confirm active-low vs active-high trigger
  from its datasheet/silkscreen (or by testing) once it arrives - bare,
  non-opto-isolated boards like the HW-482 are typically active-HIGH,
  while opto-isolated boards are typically active-LOW)
- 1× cheap USB 2.0 extension cable (to cut and splice the VBUS wire)
- Basic jumper wires

If a single machine is managing more than one Meshtastic device (e.g. a
local development/test setup, not the typical deployment), use a
multi-channel relay module instead and wire one channel per device —
the firmware and `SerialRelayPowerControl`'s `channel` parameter already
support this.

---

## Critical Files

| File | Change |
|------|--------|
| `transport/power_control.py` | Add `SerialRelayPowerControl` |
| `core/config_loader.py` | Add `get_relay_serial_port()`, relay baud getter |
| `requirements.txt` | Add `pyserial` |
| `tests/test_power_control.py` | New test class for `SerialRelayPowerControl` |
| `hardware/power_relay_firmware/src/power_relay.ino` | New — ESP32/ESP8266 firmware |
| `hardware/power_relay_firmware/platformio.ini` | New — PlatformIO build config (VS Code) |
| `project/issues.txt` | Mark Issue 19 resolved once hardware-verified |
| `project/plans/story_26_1.md` | Update epic status once this story lands |

---

## Key Design Decisions

1. **Relay module, not a bare MOSFET** — cheap, ubiquitous, beginner-safe,
   galvanically isolated, and the standard hobbyist choice for exactly this
   USB-power-switching use case; no need for a hand-designed MOSFET
   gate-drive circuit for a project whose actual goal is reliability
   infrastructure, not hardware novelty.
2. **One relay channel per device, not ganged** — matches how the server
   and client actually get deployed: each typically runs on its own
   machine managing a single local Meshtastic device, so a single-channel
   relay module is the normal, cheapest choice. This still avoids Story
   26.1's ganged-switching problem (a ganged switch can't recover one
   wedged device without bouncing a healthy one on the same hub) for the
   less common case of one machine managing several devices — just use a
   multi-channel module and one `SerialRelayPowerControl` instance per
   channel in that case.
3. **Serial (USB), not WiFi, to the ESP32** — wired and simple; avoids
   adding a network dependency to something whose entire job is recovering
   from *other* reliability failures.
4. **Relay's own controller (ESP32) is never on a switched circuit** — it
   must stay powered independently (a separate, always-on USB port) so it
   can always respond to cycle commands, including immediately after
   cycling a device.
5. **Explicit-only serial port config, no auto-detect** — protects against
   `scan_meshtastic_devices()`'s VID-blacklist approach false-positiving on
   the ESP32's own serial port (see Architecture section).
6. **Kept alongside `UhubctlPowerControl`, not a replacement for it** —
   anyone who has independently verified their hub genuinely cuts VBUS
   power can still use the simpler, no-extra-hardware `uhubctl` path;
   this story adds an option for everyone else (or anyone who'd rather not
   depend on hub compatibility at all).

---

## Verification

- **Unit tests** (mocked `serial.Serial`, no hardware): command formatting,
  `OK` success path, `ERR <reason>` handling, timeout handling, serial
  exception handling — mirroring `tests/test_power_control.py`'s existing
  `UhubctlPowerControl` test style.
- **Real hardware** (required before closing Issue 19): flash firmware,
  wire up each device's channel, run `power_cycle()` per channel, and
  **visually confirm the LED actually goes dark** this time (not just
  software signals) — then confirm the device re-enumerates and
  reconnects successfully afterward, same method already used for Story
  26.1's (invalidated) hub-based verification.
- **Regression check**: full suite (`python -m unittest discover -s tests
  -p 'test_*.py'`) still passes — this story only adds new code, no
  existing behavior changes.

---

## Implementation Completion

**Status:** Done. Real-hardware verification passed with the rigor Issue
19 called for: the target Meshtastic device's own LED (not the relay's
indicator LED) was physically confirmed to go dark during a
`power_cycle()` call, and the device reconnected cleanly afterward
(~4.5s, correct node ID) via a real `MeshtasticSerialTransport.connect()`
call - not just path-visibility.

**Hardware used for verification:** ESP8266 (NodeMCU V2) + a 5V,
jumper-configurable relay module, spliced into one Meshtastic device's
USB extension cable's VBUS wire only (data lines untouched), powered
entirely from the same USB 5V as the microcontroller (no separate PSU).

**Notable findings during bring-up, relevant to anyone repeating this:**
- On some NodeMCU boards, `VIN` is only a regulator *input* for external
  5-12V and does **not** reflect the USB 5V rail - a separate `VU` pin
  (where present) is the actual USB-5V passthrough. Verify with a
  multimeter rather than assume either pin.
- A relay's trigger polarity can't be fully trusted from a jumper label
  or even a manual "touch IN to 3.3V/GND" test - one module tested here
  responded correctly to a manual touch test in one jumper position, but
  only toggled correctly in response to an actual `power_cycle()` call in
  the *other* jumper position. **The only fully reliable check is a real
  end-to-end test**: send an actual cycle command from the host and watch
  the relay respond, not just probe the input pin by hand.
- When something doesn't work, isolate methodically: bench-test the
  relay/firmware alone first (serial protocol round-trip, LED response)
  before wiring it into a real device, and when the real-device test
  still fails, check that the GPIO is actually toggling (multimeter on
  the pin itself) before assuming the fault is in polarity or firmware
  logic - it narrows down "host/firmware," "GPIO-to-relay wiring," and
  "relay/jumper configuration" as independent failure points instead of
  guessing across all three at once.

**Issue 19 status:** resolved via this story - see `project/issues.txt`.
