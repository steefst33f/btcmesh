# Alternative LoRa Mesh Network Analysis for BTCMesh

**Date:** August 2026
**Status:** MeshCore recommendation acted on - see EPIC 9 in `project/tasks.txt` for the actual implementation (`transport/meshcore_serial.py`). Reticulum/LXMF remains unimplemented research; the comparison below is otherwise historical context, not an open decision.

## Executive Summary

BTCMesh originally ran exclusively on Meshtastic firmware; MeshCore was added as a second transport in EPIC 9. This document captures the findings that led to that choice: an investigation into which other LoRa mesh network firmwares exist, run on the **same class of hardware** (ESP32 + Semtech SX126x/SX127x boards — Heltec, LILYGO T-Beam, RAK WisBlock, etc.), and could plausibly carry BTCMesh's chunked-transaction traffic if a device were reflashed with them instead.

Two live candidates were found: **MeshCore** and **Reticulum (RNS) + LXMF**. Both are real, actively-developed projects, not hardware questions — purely firmware/software ones. MeshCore was implemented (EPIC 9); Reticulum/LXMF remains a possible future candidate, not yet prioritized.

The codebase's own design doc already anticipated this: `architecture.md` describes the `transport/` layer as protocol-agnostic and explicitly names "Meshtastic, MeshCore, Reticulum, etc." as intended targets — but that was aspirational text only, with no design or code behind it until now.

---

## Comparison Table

| | **Meshtastic** (current) | **MeshCore** | **Reticulum (RNS) + LXMF** |
|---|---|---|---|
| **Maturity** | Est. 2020, large community | Launched early 2025, smaller community | Est. 2016, moderate community |
| **Hardware** | Heltec, T-Beam, RAK WisBlock, T-Echo, T-Deck | Same boards (Heltec, T-Beam, T-Echo, T-Deck, RAK) | Same boards, via RNode firmware |
| **Routing model** | Flood routing — zero-config mesh | Route discovery, routes toward infrastructure | Configurable (multi-hop over any interface Reticulum supports) |
| **Infra requirement** | None — any two devices in range/hops just work | Needs dedicated **Repeater** nodes for range beyond direct radio contact | None beyond the radio itself; a host PC per node (see below) |
| **Node roles** | All devices equal | Companion / Repeater / Room Server | N/A — identity-based, not role-based |
| **Where routing logic runs** | On the LoRa device (firmware) | On the LoRa device (firmware) | On a **host computer** — RNode firmware is just a LoRa "modem"; RNS/LXMF run as a Python library over USB |
| **Usable payload/chunk** | ~85 bytes (170 hex chars, BTCMesh's current chunk size) | ~133–184 bytes/packet | Up to ~500 bytes MTU (RNode split-packet framing across two 255-byte LoRa frames); LXMF adds ~111 bytes overhead |
| **Addressing** | Short node ID (`!abcdef12`) | Contact public-key prefix | Cryptographic destination hash |
| **Delivery ACK** | Implicit/explicit ACK via mesh | Built-in (`PACKET_MSG_SENT` / `PACKET_ACK`, 4–6 byte codes) | Built-in via LXMF (opportunistic + confirmed delivery) |
| **Encryption** | Optional (channel PSK) | Present | Built-in, first-class (identity-based E2E) |
| **Python integration** | `meshtastic` pip package, serial/BLE companion protocol (what BTCMesh uses today) | `meshcore`/`meshcore_py` pip package, serial/BLE/TCP companion protocol — structurally similar to Meshtastic's | `rns` pip package — native Python API, **no serial protocol to parse at all** |
| **Biggest downside for BTCMesh** | N/A (baseline) | Range depends on deployed repeater infrastructure | Different addressing model — `core/protocol.py`'s destination validation would need real rework, not a tweak |

---

## Candidate Details

### MeshCore — closest architectural match

Open-source LoRa mesh firmware, launched early 2025 as a direct Meshtastic alternative, running on identical hardware. It differs from Meshtastic's flood routing by doing route discovery and routing traffic toward infrastructure, distinguishing **Companion** (end-user device), **Repeater** (relay-only), and **Room Server** (persistent group chat host) roles. Companion devices only relay their own traffic — extending range beyond direct radio contact requires someone to have deployed dedicated repeater nodes, unlike Meshtastic's "turn it on and it just works" mesh.

Its "Companion Radio" protocol over serial/BLE/TCP is structurally similar to how BTCMesh already talks to Meshtastic devices (request/response framing), and there's an existing Python client library (`meshcore`/`meshcore_py`) analogous to the `meshtastic` package BTCMesh already depends on. Payload is capped around 133–184 bytes depending on message type — in the same ballpark as today's chunk size. It has a built-in packet ACK system (`PACKET_MSG_SENT` / `PACKET_ACK`), conceptually close to BTCMesh's own `BTC_CHUNK_ACK` flow, though it would still ride *underneath* BTCMesh's application-level ACK protocol rather than replace it.

### Reticulum (RNS) + LXMF — biggest technical upside, more rework

Reticulum is a general-purpose, cryptography-first networking stack (not LoRa-specific) that runs over many transports, including LoRa via **RNode firmware**, which flashes onto the same boards (Heltec, T-Beam, etc.). RNode firmware itself is just a LoRa "modem" — the actual mesh/routing/message logic (RNS + LXMF) runs as a Python library on a host computer connected to the radio over USB. This sounds like a downside, but BTCMesh's client and server already assume a host computer running Python next to the radio — that's exactly today's architecture with Meshtastic — so it isn't actually extra burden.

It has a native Python API (`rns` package) with no serial companion-protocol parsing needed at all, architecturally simpler to integrate than either Meshtastic's or MeshCore's request/response framing. Its effective payload is bigger: Reticulum's MTU is 500 bytes, transparently split across two 255-byte LoRa frames by RNode. LXMF (the messaging layer on top) adds ~111 bytes of overhead per message but still leaves meaningfully more room per hop than Meshtastic's ~85-byte-per-chunk budget — meaning **fewer chunks per transaction**, a real efficiency win for large raw txs. It also has built-in end-to-end encryption and delivery confirmation (opportunistic and confirmed modes) as first-class LXMF features, rather than something BTCMesh has to layer on itself.

The addressing model is the bigger departure: destinations are cryptographic identity hashes, not short node IDs like Meshtastic's `!abcdef12`. `core/protocol.py`'s `validate_destination()` (currently hard-coded to that Meshtastic format) would need real rework, not just a tweak, if this were ever implemented.

### Ruled out

- **Disaster Radio** (sudomesh) — the project itself is explicitly paused/inactive; its own docs point people to Meshtastic or Reticulum instead. Not a live option.
- **LoRaWAN** (The Things Network, Helium, etc.) — fundamentally a star topology to internet-connected gateways, not a peer-to-peer multi-hop mesh. Requires gateway infrastructure with internet backhaul, which conflicts with BTCMesh's "no/censored internet, LoRa-only" premise, and typical LoRaWAN duty-cycle/payload limits are tighter than a raw point-to-point LoRa link.

---

## Fit With the Existing Codebase

`transport/base.py`'s `BaseTransport` abstraction (`connect`, `disconnect`, `send`, `set_message_handler`, `check_alive`, `scan_for_reconnect_candidates`, `is_connected`, `local_node_id`) was already genuinely protocol-agnostic in its method signatures — no Meshtastic-specific concepts leak into the interface itself. A second transport implementation was exactly the shape of extension this layer was built for.

Three coupling points outside `transport/` assumed Meshtastic and needed generalizing before a second transport could plug in - all three were resolved during EPIC 9's implementation, confirming this analysis correctly predicted the real friction points:

1. `core/protocol.py`'s `validate_destination()` was Meshtastic-specific, hard-coding the `!hex8` node-ID format. **Resolved** (Story 30.2): moved to `BaseTransport.validate_destination()`, an abstract method each transport implements for its own addressing scheme; the free function was deleted.
2. `core/meshtastic_utils.py` (device scanning/node listing) had no transport-agnostic equivalent. **Resolved**: candidate-port scanning (no protocol content) moved to `core/device_scan.py`, shared by both transports; each transport keeps its own `probe_device_identity()` (`core/meshtastic_utils.py` / `core/meshcore_utils.py`) for the genuinely protocol-specific identity handshake.
3. All four entry points hardcoded `MeshtasticSerialTransport()` directly, with no factory/registry. **Resolved** across all four via `transport/factory.py`'s `get_transport(name)` - a `--transport` flag on both CLIs, a transport dropdown on both GUIs (`project/tasks.txt`'s Story 30.4 checkbox is stale and doesn't reflect this).

## Bottom Line

MeshCore is the smaller lift — its companion-protocol-over-serial shape mirrors what BTCMesh already does for Meshtastic — but depends on deployed repeater infrastructure for range. Reticulum/LXMF is a bigger design change (different addressing model, no serial protocol to parse at all) but offers a larger per-message payload and gets encryption/delivery-confirmation for free.

---

## References

**MeshCore**
- Project repo: https://github.com/meshcore-dev/MeshCore
- Companion Radio protocol docs: https://docs.meshcore.io/companion_protocol/
- Payload format docs: https://docs.meshcore.io/payloads/
- Python client library (PyPI): https://pypi.org/project/meshcore/

**Reticulum / LXMF**
- Reticulum Network Stack repo: https://github.com/markqvist/reticulum
- "Understanding Reticulum" manual: https://reticulum.network/manual/understanding.html
- Interfaces configuration (incl. LoRa/RNode): https://reticulum.network/manual/interfaces.html
- Communications hardware guide: https://reticulum.network/manual/hardware.html
- LXMF messaging protocol repo: https://github.com/markqvist/LXMF
- `rns` Python package (PyPI): https://pypi.org/project/rns/
- RNode Firmware (community edition, actively maintained): https://github.com/liberatedsystems/RNode_Firmware_CE
- RNode Firmware (original): https://github.com/markqvist/RNode_Firmware

**Ruled out**
- Disaster Radio (paused project): https://github.com/sudomesh/disaster-radio

**Comparison write-ups consulted**
- Mesh America — "Meshtastic vs MeshCore: which firmware fits your network": https://meshamerica.com/2026/04/26/meshtastic-vs-meshcore-which-firmware-fits-your-network/
- Hexaspot — "Meshtastic vs MeshCore Explained: Same Hardware, Different Firmware": https://hexaspot.com/blogs/news/meshtastic-vs-meshcore-explained-same-hardware-different-firmware
- LavX News — "Mesh Networking Showdown: Meshtastic, MeshCore, and Reticulum Compared": https://news.lavx.hu/article/mesh-networking-showdown-meshtastic-meshcore-and-reticulum-compared
