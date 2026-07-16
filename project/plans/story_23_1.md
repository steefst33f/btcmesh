# Story 23.1 Implementation Plan: Create server/receiver.py

## Context

**Why this change:**
`btcmesh_server.py` mixes three concerns in one 809-line file: direct Meshtastic/pubsub wiring (`initialize_meshtastic_interface`, raw `pub.subscribe`), the actual receive/reassemble/broadcast business logic (`on_receive_text_message`, `send_meshtastic_reply`), and process orchestration (`main()`'s loop, stop_event, session_update_callback). `btcmesh_server_gui.py` currently calls `btcmesh_server.main()` directly in a background thread and captures its behavior via a log-scraping `QueueLogHandler` — the exact same coupling pattern `btcmesh_gui.py` had with `cli_main()` before Story 22.2.

**Goal:**
Extract the receive/reassemble/broadcast orchestration into a reusable `server/receiver.py` module — the server-side counterpart to `client/sender.py` (Story 22.1) — that works with any `BaseTransport` and any `BitcoinRPCClient`, with typed callbacks instead of log-scraping.

**Outcome:**
A `TransactionReceiver` class that can be constructed with an already-connected transport and RPC client, registers itself as the transport's message handler, and exposes `check_timeouts()` (caller-driven periodic maintenance) and `get_active_sessions()` for UI display. `btcmesh_server.py` and `btcmesh_server_gui.py` are **not modified in this story** — mirrors Story 22.1, which only created `client/sender.py` without touching `btcmesh_cli.py`/`btcmesh_gui.py` (that wiring came in 22.2). This story also fixes a destination-filtering gap in `transport/meshtastic_serial.py` discovered during exploration (see Key Design Decision 1).

---

## Current Flow (in btcmesh_server.py, unchanged by this story)

```
main(stop_event, rpc_config, serial_port, reassembly_timeout, session_update_callback)
  → initialize_meshtastic_interface(port)                           [direct meshtastic.serial_interface import]
  → pub.subscribe(on_receive_text_message, "meshtastic.receive")    [direct pubsub import]
  → while True:
      → session_update_callback(reassembler.get_active_sessions_info())   [every 1s]
      → reassembler.cleanup_stale_sessions() → NACK timed-out sessions    [every 10s]
      → time.sleep(1.0)

on_receive_text_message(packet, interface, send_reply_func, logger):
  → manually filters: has "decoded"? from == self (ignore)? to == self (else ignore)?
  → extracts TEXT_MESSAGE_APP text
  → if BTC_TX chunk: reassembler.add_chunk() → ACK/REQUEST_CHUNK
  → if reassembled: bitcoin_rpc.broadcast_transaction() → BTC_ACK/BTC_NACK
  → transaction_history.add(...)
```

## New Flow (server/receiver.py, this story only)

```
receiver = TransactionReceiver(transport, rpc_client,
    on_chunk_received=..., on_broadcast=..., on_error=...)
  → registers self._on_message as transport's message handler

# Driven by transport (no polling needed for receiving):
transport delivers (message_text, sender_id) — already filtered for
TEXT_MESSAGE_APP + self-messages + (after this story's transport fix) destination
  → receiver._on_message(message_text, sender_id)
      → not a BTC_TX chunk? ignore
      → reassembler.add_chunk() → ACK/REQUEST_CHUNK via transport.send()
      → on_chunk_received(ChunkReceived(...))
      → if reassembled: rpc_client.broadcast_transaction() → BTC_ACK/BTC_NACK via transport.send()
                         → on_broadcast(BroadcastResult(...))
      → reassembly/unexpected errors → NACK via transport.send() → on_error(session_id, sender_id, message)

# Driven by caller's own timer (GUI's Clock, a CLI's sleep loop, or test code):
receiver.check_timeouts()
  → reassembler.cleanup_stale_sessions() → NACK via transport.send() → on_error(...)

receiver.get_active_sessions()  → reassembler.get_active_sessions_info(), for UI display
```

Note there is no `receiver.start()`/blocking call — unlike `TransactionSender.send_transaction()` (one blocking call per transaction), the receiver is purely reactive (message-handler-driven) plus one on-demand maintenance method. This intentionally avoids putting a background thread/sleep loop inside the "pure" receiver class; the caller's own event loop (Kivy `Clock.schedule_interval` for the GUI, a plain loop for a future CLI) drives `check_timeouts()` on whatever cadence it wants — exactly mirroring how `btcmesh_server.py`'s current `main()` loop already drives `cleanup_stale_sessions()` externally today.

---

## Architecture Overview

### What Gets Extracted (new, in server/receiver.py)

```
btcmesh_server.py's on_receive_text_message() + send_meshtastic_reply():
├── BTC_TX chunk detection/parsing              🔨 → TransactionReceiver._on_message()
├── reassembler.add_chunk() orchestration        🔨 → TransactionReceiver._on_message()
├── ACK/REQUEST_CHUNK reply formatting           🔨 → TransactionReceiver._on_message()
├── RPC broadcast + BTC_ACK/BTC_NACK formatting  🔨 → TransactionReceiver._broadcast()
├── Concise error-message mapping (20+ elif chain) 🔨 → server/receiver.py's _concise_error_message()
└── Stale-session NACK logic (from main()'s loop) 🔨 → TransactionReceiver.check_timeouts()
```

### What Stays in btcmesh_server.py (for now — Story 23.2/23.3 territory)

```
btcmesh_server.py (UNCHANGED this story):
├── initialize_meshtastic_interface()   — direct meshtastic import; becomes MeshtasticSerialTransport
│                                          usage only when 23.3 creates the thin CLI
├── main()'s process orchestration      — stop_event, config loading, the polling loop itself
├── transaction_history recording       — stays a caller-layer concern (see Key Design Decision 2)
└── raw pub.subscribe() wiring          — replaced by transport.set_message_handler() only when
                                           23.2/23.3 actually swap in TransactionReceiver
```

### What Already Exists (REUSE, unchanged)

1. **`core/reassembler.py`** — `TransactionReassembler`: `add_chunk()`, `cleanup_stale_sessions()`, `get_active_sessions_info()`, plus `InvalidChunkFormatError`/`MismatchedTotalChunksError`/`ReassemblyError`, `CHUNK_PREFIX`/`CHUNK_PARTS_DELIMITER` constants.
2. **`core/rpc_client.py`** — `BitcoinRPCClient.broadcast_transaction(raw_tx_hex)` → `(txid, error)`.
3. **`transport/base.py`** — `BaseTransport.send(message, destination)`, `set_message_handler(callback)` — same interface `TransactionSender` already uses.
4. **`transport/meshtastic_serial.py`** — `MeshtasticSerialTransport._on_meshtastic_receive()` already filters TEXT_MESSAGE_APP + self-messages and delivers clean `(message_text, sender_id)` — the same interface the client side already relies on.

---

## Implementation Steps

### Step 1: Fix destination filtering in `transport/meshtastic_serial.py`

`_on_meshtastic_receive()` currently only filters by packet type (TEXT_MESSAGE_APP) and sender (excludes self). It does **not** check that the packet is actually addressed to this node — so it would currently pass through broadcasts or messages meant for a different node on the same mesh channel. The current server's `on_receive_text_message()` explicitly checks `destination_node_id == my_node_id` and ignores anything else; without this fix, `TransactionReceiver` built on top of the transport would be *more* promiscuous than today's server (a real regression risk for any deployment with more than one relay server on the same channel).

**Revised during implementation:** the old server's exact logic is `dest_val = packet.get("to") or packet.get("toId")`, then drops the message if the formatted result doesn't equal `my_node_id` — critically, if **both** `to` and `toId` are absent, `dest_val` stays `None`, which never equals `my_node_id`, so **the message is dropped**, not allowed through. An initial draft of this fix treated "no destination field at all" as "allow through" (to avoid touching existing test fixtures that omit `to`), which was backwards — real Meshtastic DM packets always carry an explicit destination (even broadcasts use an explicit broadcast address rather than omitting it), so missing destination info should be treated the same as "not addressed to us." Fixed to match the old behavior exactly: require `to` (or `toId` as a string fallback) to be present **and** match this node; otherwise drop.

```python
def _on_meshtastic_receive(
    self, packet: dict, interface: Any = None, **kwargs: Any
) -> None:
    if self._handler is None:
        return

    decoded = packet.get("decoded")
    if not decoded:
        return

    if str(decoded.get("portnum")) != "TEXT_MESSAGE_APP":
        return

    sender_num = packet.get("from")
    if sender_num is not None and sender_num == self._my_node_num:
        return

    # Filter: messages not explicitly addressed to this node. Real
    # Meshtastic DM packets always carry a destination (even broadcasts use
    # an explicit broadcast address rather than omitting it), so missing
    # destination info means this isn't a direct message to us - drop
    # broadcasts, messages meant for another node, and anything with no
    # destination info at all (matches the old server's exact behavior).
    dest_num = packet.get("to")
    if dest_num is None:
        dest_id = packet.get("toId")
        if dest_id is None:
            return
        if dest_id != self._format_node_id(self._my_node_num):
            return
    elif dest_num != self._my_node_num:
        return

    message_text = self._extract_text_from_packet(decoded)
    if not message_text:
        return

    sender_id = packet.get("fromId")
    if sender_id is None and sender_num is not None:
        sender_id = self._format_node_id(sender_num)
    if sender_id is None:
        sender_id = "!00000000"

    try:
        self._handler(message_text, sender_id)
    except Exception:
        logger.exception("Error in message handler")
```

Existing tests in `tests/test_meshtastic_serial_transport.py` that expect the handler to fire didn't set a `to` field in their packet fixtures, so with the corrected (stricter) behavior they needed a matching `'to': 0xDEADBEEF` (the shared `MockSerialInterface` default node) added — 3 fixtures updated (`test_receive_text_message_calls_handler`, `test_receive_payload_fallback_to_bytes`, `test_receive_handles_handler_exception`). Added 3 new tests: mismatched destination dropped, no-destination-info-at-all dropped, and the `toId` string-fallback still working when it matches.

### Step 2: Create `server/receiver.py`

```python
"""TransactionReceiver: reusable server-side orchestration for receiving,
reassembling, and broadcasting chunked Bitcoin transactions.

Extracted from btcmesh_server.py's on_receive_text_message()/
send_meshtastic_reply()/main() loop. Pure aside from the injected
transport/rpc_client: no direct Meshtastic or Bitcoin RPC library imports,
no print, no logging, no file I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.reassembler import (
    CHUNK_PARTS_DELIMITER,
    CHUNK_PREFIX,
    InvalidChunkFormatError,
    MismatchedTotalChunksError,
    ReassemblyError,
    TransactionReassembler,
)
from core.rpc_client import BitcoinRPCClient
from transport.base import BaseTransport

_MAX_NACK_LEN = 200

# Concise error-message mapping for common Bitcoin Core RPC rejection
# reasons, kept short enough to fit LoRa payload constraints in a NACK.
_CONCISE_ERROR_MAP = (
    ("Transaction outputs already in utxo set", "TX already in UTXO set"),
    ("Transaction already in block chain", "TX already in chain"),
    ("insufficient fee", "Insufficient fee"),
    ("missing inputs", "Missing inputs"),
    ("bad-txns-inputs-spent", "Inputs spent"),
    ("bad-txns-in-belowout", "Input < Output"),
    ("too-long-mempool-chain", "Chain too long"),
    ("mempool full", "Mempool full"),
    ("replacement transaction", "RBF disabled"),
    ("non-mandatory-script-verify-flag", "Script verify failed"),
    ("transaction already abandoned", "TX abandoned"),
    ("bad-txns-nonstandard-inputs", "Non-std inputs"),
    ("bad-txns-oversize", "TX too large"),
    ("dust", "Dust output"),
    ("fee is too high", "Fee too high"),
    ("absurdly-high-fee", "Absurd fee"),
)


def _concise_error_message(error: str) -> str:
    """Map a verbose Bitcoin Core RPC error to a short NACK-friendly string."""
    lowered = error.lower()
    for needle, short in _CONCISE_ERROR_MAP:
        if needle.lower() in lowered:
            return short
    if "version" in lowered and "reject" in lowered:
        return "Version rejected"
    return error


@dataclass
class ChunkReceived:
    """A single valid chunk was received, reassembled-into, and ACKed."""
    session_id: str
    sender_id: str
    chunk_num: int
    total_chunks: int


@dataclass
class BroadcastResult:
    """Result of a completed reassembly + RPC broadcast attempt."""
    session_id: str
    sender_id: str
    success: bool
    txid: Optional[str] = None
    error: Optional[str] = None
    raw_tx: Optional[str] = None


class TransactionReceiver:
    """Orchestrates receiving, reassembling, and broadcasting transactions.

    Registers itself as the transport's message handler on construction.
    Callers must periodically invoke check_timeouts() (e.g. from a GUI's
    Clock or a CLI's own loop) to NACK stale reassembly sessions - this
    class does not run its own background thread.
    """

    def __init__(
        self,
        transport: BaseTransport,
        rpc_client: BitcoinRPCClient,
        reassembler: Optional[TransactionReassembler] = None,
        on_chunk_received: Optional[Callable[[ChunkReceived], None]] = None,
        on_broadcast: Optional[Callable[[BroadcastResult], None]] = None,
        on_error: Optional[Callable[[str, str, str], None]] = None,
        # on_error(session_id, sender_id, error_message) - fires for
        # reassembly errors, unexpected processing errors, AND stale-session
        # timeouts (all are just "this session failed with error X" from a
        # caller's perspective).
    ):
        self.transport = transport
        self.rpc_client = rpc_client
        self.reassembler = reassembler or TransactionReassembler()
        self._on_chunk_received = on_chunk_received
        self._on_broadcast = on_broadcast
        self._on_error = on_error
        self.transport.set_message_handler(self._on_message)

    def _on_message(self, message_text: str, sender_id: str) -> None:
        if not message_text.startswith(CHUNK_PREFIX):
            return

        # Best-effort pre-parse, only to get chunk_num/total_chunks for the
        # ACK reply below. reassembler.add_chunk() (called in the try block
        # below) is the actual authority on format validity - if this parse
        # fails, leave the defaults and let add_chunk() raise the properly
        # categorized error instead of masking it with a parse error here.
        #
        # Found during testing: an earlier version let this pre-parse's own
        # ValueError (e.g. int("notanumber")) propagate into the same
        # try/except as add_chunk() below, where it was caught by the
        # generic `except Exception` branch - which fires on_error but never
        # sends a NACK. A malformed chunk with non-numeric chunk/total info
        # would then fail silently instead of NACKing. Matches the old
        # server's exact approach: silently default on parse failure, let
        # add_chunk() be the sole validator.
        session_id = "UNKNOWN"
        chunk_num, total_chunks = 1, 1
        try:
            parts = message_text[len(CHUNK_PREFIX):].split(CHUNK_PARTS_DELIMITER)
            session_id = parts[0] if parts and parts[0] else "UNKNOWN"
            chunk_info = parts[1] if len(parts) > 1 else ""
            if "/" in chunk_info:
                chunk_num_s, total_s = chunk_info.split("/")
                chunk_num, total_chunks = int(chunk_num_s), int(total_s)
        except Exception:
            pass

        try:
            reassembled_hex = self.reassembler.add_chunk(sender_id, message_text)

            if chunk_num < total_chunks:
                ack = f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|REQUEST_CHUNK|{chunk_num + 1}"
            else:
                ack = f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|ALL_CHUNKS_RECEIVED"
            self.transport.send(ack, sender_id)

            if self._on_chunk_received:
                self._on_chunk_received(
                    ChunkReceived(session_id, sender_id, chunk_num, total_chunks)
                )

            if reassembled_hex:
                self._broadcast(session_id, sender_id, reassembled_hex)

        except (InvalidChunkFormatError, MismatchedTotalChunksError) as e:
            error_type = type(e).__name__.replace("Error", "").replace("Invalid", "Invalid ")
            detail = f"{error_type}: {e}"
            self._send_nack(session_id, sender_id, detail)
            if self._on_error:
                self._on_error(session_id, sender_id, detail)
        except ReassemblyError as e:
            if self._on_error:
                self._on_error(session_id, sender_id, str(e))
        except Exception as e:
            if self._on_error:
                self._on_error(session_id, sender_id, str(e))

    def _broadcast(self, session_id: str, sender_id: str, raw_tx: str) -> None:
        txid, error = self.rpc_client.broadcast_transaction(raw_tx)
        if txid:
            self.transport.send(f"BTC_ACK|{session_id}|TXID:{txid}", sender_id)
            if self._on_broadcast:
                self._on_broadcast(
                    BroadcastResult(session_id, sender_id, True, txid=txid, raw_tx=raw_tx)
                )
        else:
            concise = _concise_error_message(str(error))
            self._send_nack(session_id, sender_id, concise)
            if self._on_broadcast:
                self._on_broadcast(
                    BroadcastResult(session_id, sender_id, False, error=str(error), raw_tx=raw_tx)
                )

    def _send_nack(self, session_id: str, sender_id: str, detail: str) -> None:
        msg = f"BTC_NACK|{session_id}|{detail}"
        if len(msg) > _MAX_NACK_LEN:
            msg = msg[: _MAX_NACK_LEN - 3] + "..."
        self.transport.send(msg, sender_id)

    def check_timeouts(self) -> None:
        """Check for and NACK stale reassembly sessions. Call periodically."""
        for session_info in self.reassembler.cleanup_stale_sessions():
            self._send_nack(
                session_info["tx_session_id"],
                session_info["sender_id_str"],
                session_info["error_message"],
            )
            if self._on_error:
                self._on_error(
                    session_info["tx_session_id"],
                    session_info["sender_id_str"],
                    session_info["error_message"],
                )

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Active reassembly sessions, for UI display."""
        return self.reassembler.get_active_sessions_info()
```

### Step 3: Create `tests/test_server_receiver.py`

Mirrors `tests/test_client_sender.py`'s structure and mocking style (a fake `BaseTransport`, a mocked `BitcoinRPCClient`). Coverage:

- Construction registers `_on_message` as the transport's handler.
- Single-chunk and multi-chunk messages: correct ACK/REQUEST_CHUNK sequence, `on_chunk_received` fires with correct values.
- Full reassembly triggers `rpc_client.broadcast_transaction()`; success → `BTC_ACK` sent + `on_broadcast(success=True, txid=...)`.
- Broadcast failure → `BTC_NACK` sent with concise mapped error + `on_broadcast(success=False, error=...)`.
- `_concise_error_message()` mapping for each of the ~16 known error substrings, plus an unmapped error passed through unchanged.
- Mismatched total_chunks (`MismatchedTotalChunksError`, e.g. chunk `1/2` then a later chunk `1/3` for the same session) → NACK sent + `on_error(...)` fires; a session *is* created by the first chunk then discarded by the reassembler's own error handling — asserted via `get_active_sessions()` being non-empty after the first chunk and empty again after the second (mismatched) one.
- Genuinely invalid chunk format (`InvalidChunkFormatError`, e.g. non-numeric chunk/total like `"notanumber/2"`) → NACK sent + `on_error(...)` fires; distinct from the mismatched-chunks case above because this one is *never* added to the reassembler at all — asserted via `get_active_sessions()` staying empty throughout.
- Non-`BTC_TX`-prefixed message → ignored entirely: no ACK **and no NACK** (both share the single `transport.send()` channel, so one `assert_not_called()` proves neither fired), `reassembler.add_chunk()` never invoked, and `get_active_sessions()` stays empty — proving it wasn't just "not acked" but never handed to the reassembler at all.
- `check_timeouts()`: stale session → NACK sent to the right sender + `on_error(...)` fires; no stale sessions → no-op.
- `get_active_sessions()` delegates to `reassembler.get_active_sessions_info()`.
- All callbacks are optional — receiver works fine with none provided.

Note: `core/reassembler.py` itself is untouched by this story (see Issue 15
in `project/issues.txt` for a discovered-but-deferred robustness gap around
out-of-order chunk arrival — a follow-up, not in scope here).

### Step 4: (folded into Step 1) — destination-filter tests already added alongside the fix

### Step 5: Full test suite run

No changes to `btcmesh_server.py`/`btcmesh_server_gui.py` in this story, so their existing tests are unaffected. See Verification below.

---

## Critical Files

| File | Change |
|---|---|
| `server/receiver.py` | **New** — `TransactionReceiver`, `ChunkReceived`, `BroadcastResult`, `_concise_error_message()` |
| `tests/test_server_receiver.py` | **New** — full coverage of the receiver in isolation |
| `transport/meshtastic_serial.py` | Add destination-address filtering to `_on_meshtastic_receive()` |
| `tests/test_meshtastic_serial_transport.py` | Add regression test for the new destination filter |
| `btcmesh_server.py`, `btcmesh_server_gui.py` | **Unchanged** — wiring happens in Story 23.2/23.3 |

---

## Key Design Decisions

### 1. Destination filtering added to `transport/meshtastic_serial.py`
See Step 1 above for the full rationale — without it, `TransactionReceiver` would be more promiscuous than today's server (would process chunks broadcast/addressed to other nodes on the same channel). Fixed at the transport layer since that's shared by both client and server, and is the correct layer to know about packet-level addressing; the client already tolerates extra noise gracefully (filters by known session ID), so this change only makes behavior *stricter*, never breaking the client.

### 2. Transaction history recording is NOT part of the receiver
Story 23.1's own scenario list only names "a transport, RPC client, and configuration" as receiver dependencies - no history store. Recording to `TransactionHistory` (which does file I/O) is left to the caller's `on_broadcast`/`on_error` callback implementations (wired up in Story 23.2 for the GUI), keeping `TransactionReceiver` itself free of file I/O — consistent with the "no I/O in receiver" scenario and mirroring how `TransactionSender` doesn't know anything about GUI logging either.

### 3. No background thread/polling inside `TransactionReceiver`
Unlike `TransactionSender.send_transaction()` (one blocking call that must wait for chunk ACKs), the receiver is purely reactive to incoming messages plus one on-demand `check_timeouts()` method the caller invokes on its own schedule. This avoids embedding a sleep-loop/thread inside a class meant to be simple and directly unit-testable (call `check_timeouts()` once in a test, assert on the result — no need to mock `time.sleep` or manage a background thread in tests).

### 4. Callback shape: three targeted callbacks over the story's literal `on_chunk`/`on_broadcast`/`on_error` names
Kept the story's three callback *names* essentially as-is, but gave them dataclass payloads (`ChunkReceived`, `BroadcastResult`) rather than positional args, mirroring `SendResult`'s style from `client/sender.py`. `on_error` is intentionally reused for reassembly errors, unexpected exceptions, *and* stale-session timeouts — from a caller's perspective these are all "this session failed with error X," matching how `btcmesh_server.py`'s existing `transaction_history.add(status="failed", ...)` already treats them uniformly today.

### 5. Concise error-message mapping moved verbatim
The ~16-branch if/elif chain mapping verbose Bitcoin Core RPC errors to short NACK-friendly strings moves into `server/receiver.py` as a data table (`_CONCISE_ERROR_MAP`) + `_concise_error_message()` function, rather than being reimplemented as a long conditional — same behavior, more testable (one test per mapping entry), and removed from the eventual thin `btcmesh_server.py` replacement's scope entirely.

---

## Verification

1. Run the full suite: `python -m unittest discover -s tests -p 'test_*.py'` — all existing tests continue to pass unchanged (no existing file is behaviorally modified except the additive transport filter), plus new tests for `server/receiver.py` and the transport destination filter.
2. Confirm `server/receiver.py` has zero direct imports of `meshtastic.*` or Bitcoin RPC libraries — only `core.reassembler`, `core.rpc_client` (the injected client's *type*, not a live connection), and `transport.base`.
3. Manually exercise `TransactionReceiver` against real hardware in isolation (no GUI/CLI wiring yet, since that's Story 23.2/23.3): connect a `MeshtasticSerialTransport`, construct a `TransactionReceiver` with a real `BitcoinRPCClient`, send a real chunked transaction from the existing `btcmesh_client_cli.py`, and confirm the receiver ACKs each chunk, broadcasts, and returns `BTC_ACK`/`BTC_NACK` correctly — proving behavioral parity with the current `btcmesh_server.py` before it gets swapped in.
4. Confirm `btcmesh_server.py` and `btcmesh_server_gui.py` are byte-for-byte unchanged (`git diff` shows no hits for either file).

---

## Implementation Completion

**Status:** ✅ **COMPLETE** (July 16, 2026)

**Test results:** 628 tests passing (18 new for `server/receiver.py`, 3 new for the transport destination filter), 10 skipped.

**Deviations from initial plan:**
- Step 1's destination filter was corrected mid-implementation to match the old server's exact "no destination info at all → drop" behavior, rather than an initial draft that (wrongly) allowed such messages through — see Key Design Decision 1 / Step 1 for the full trace through the old code's logic.
- `_on_message`'s own pre-parse of `chunk_num`/`total_chunks` (needed only to format the ACK reply) was found to shadow `reassembler.add_chunk()`'s proper error categorization when the pre-parse itself threw a plain `ValueError` — fixed to silently default and let `add_chunk()` be the sole format-validity authority, matching the old server's structure.
- Test coverage was strengthened beyond the original plan to explicitly prove non-chunk/invalid messages are never added to the reassembler at all (via `get_active_sessions()`), not just "not ACKed" — distinguishing the "never added" case (invalid format) from "added then discarded" (mismatched total_chunks).
- **Issue 14** (known-nodes `lastHeard` not reflecting direct-message traffic) and **Issue 15** (reassembler doesn't enforce strict in-order chunk arrival) were discovered/discussed during this story's work and documented in `project/issues.txt` as deliberate follow-ups, not folded into this story's scope.

**Manual verification against real hardware:**
- Connected `TransactionReceiver` (real `MeshtasticSerialTransport` + real testnet `BitcoinRPCClient`) on one device, sent a real chunked transaction via `btcmesh_client_cli.py` from the other device.
- Confirmed: chunk received and ACKed, `on_chunk_received` fired with correct values, reassembly completed, RPC broadcast attempted against the real (testnet) node, `on_broadcast` fired with the real RPC rejection error (`'TX decode failed...'` for the intentionally-invalid test hex), and the client received the exact NACK end-to-end.
- Confirmed `btcmesh_server.py`/`btcmesh_server_gui.py` untouched (`git diff` shows no hits for either file).

**Files changed:**

| File | Change |
|---|---|
| `server/__init__.py`, `server/receiver.py` | New — `TransactionReceiver`, `ChunkReceived`, `BroadcastResult`, `_concise_error_message` |
| `tests/test_server_receiver.py` | New — 18 tests |
| `transport/meshtastic_serial.py` | Added destination-address filtering to `_on_meshtastic_receive()` |
| `tests/test_meshtastic_serial_transport.py` | 3 new tests, 3 existing fixtures updated with a `to` field |
| `project/issues.txt` | Documented Issues 14 and 15 |

**Next steps:**
- Story 23.2: Refactor `btcmesh_server_gui.py` to use `TransactionReceiver` (parallel to Story 22.2's GUI refactor)
- Story 23.3: Create `btcmesh_server_cli.py` as a thin CLI entry point, then delete `btcmesh_server.py` (parallel to Story 22.3)
