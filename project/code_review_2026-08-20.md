# Code Review — 2026-08-20

Full-codebase senior-engineer review covering correctness, performance, readability, error handling/edge cases, and security, conducted by exploring `core/`, `transport/`, `client/`, `server/`, and the CLI/GUI/tests layers. Each finding is rated Critical/High/Medium/Low with file:line citations and a concrete fix. The highest-severity claims (findings #1, #2, #3, #5, #9) were independently verified by reading the source directly and, for #1, running a live interpreter check of the exception hierarchy in question.

---

## HIGH severity

### 1. RPC retry logic is dead code — never actually retries
**File:** [core/rpc_client.py:74](../core/rpc_client.py#L74)
```python
except (ConnectionError, TimeoutError) as e:
```
`requests.post()` ([core/rpc_client.py:68](../core/rpc_client.py#L68)) raises `requests.exceptions.ConnectionError` / `requests.exceptions.Timeout`, which do **not** inherit from the Python builtins `ConnectionError`/`TimeoutError` — verified directly:
```
issubclass(requests.exceptions.ConnectionError, ConnectionError)  ->  False
requests.exceptions.ConnectionError.__mro__ = (..., RequestException, OSError, Exception, BaseException, object)
```
Every real network failure to Bitcoin Core falls into the generic `except Exception as e: ... raise` at [lines 82-85](../core/rpc_client.py#L82-L85) and is re-raised on the *first* attempt. The docstring's "automatic connection retry logic" ([line 45](../core/rpc_client.py#L45)) never fires for the failure mode it was written for.
**Fix:** catch `(requests.exceptions.ConnectionError, requests.exceptions.Timeout)` instead of the builtins.

### 2. Transaction sanity-check module is wired up nowhere — dead validation
**File:** [core/transaction_parser.py](../core/transaction_parser.py) (`decode_raw_transaction_hex`, `basic_sanity_check`)
Confirmed via repo-wide grep: these two functions are referenced only from `tests/test_transaction_parser.py`. The path from reassembled hex to broadcast (`core/reassembler.py` → `server/receiver.py:276` → `rpc_client.broadcast_transaction`) never calls them. The module's own docstring says it exists for pre-broadcast sanity checking ("Story 3.1"), but a malformed/garbage transaction is only rejected after the full multi-chunk LoRa round-trip completes and Bitcoin Core's RPC rejects it — the exact wasted-round-trip cost this module looks like it was built to avoid.
**Fix:** call `decode_raw_transaction_hex` + `basic_sanity_check` on the reassembled hex in `server/receiver.py` before invoking `broadcast_transaction`, and NACK locally on failure with the concise message these functions already produce instead of Bitcoin Core's raw RPC error text.

---

## MEDIUM severity

### 3. Client-side hex validation is more permissive than what's actually required downstream
**File:** [core/protocol.py:38-49](../core/protocol.py#L38-L49)
```python
def is_valid_hex(s: str) -> bool:
    if not s:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False
```
`int(s, 16)` accepts underscore digit separators (`"de_ad"`), leading/trailing whitespace, and a leading `0x`/`+`/`-` — none of which `bytes.fromhex()` (used by `transaction_parser`) or Bitcoin Core's own hex decoder accept. Since `validate_transaction_hex()` ([core/protocol.py:52-63](../core/protocol.py#L52-L63)) is the sole client-side gate before chunking and sending across the mesh (`client/sender.py`), a string like `"0xdeadbeef..."` passes validation and triggers a full multi-chunk LoRa transfer that only fails at the very end.
**Fix:** validate with a strict character-class check (`re.fullmatch(r'[0-9a-fA-F]+', s)`) instead of `int(s, 16)`.

### 4. No bound on reassembly session size or count — unbounded memory growth
**File:** [core/reassembler.py:79-134](../core/reassembler.py#L79-L134) (`_parse_chunk`), [lines 136-253](../core/reassembler.py#L136-L253) (`add_chunk`)
The only check on `total_chunks` is `> 0` ([line 129](../core/reassembler.py#L129)) — no upper bound, and no cap on the number of concurrent open sessions per sender. A sender declaring `total_chunks=999999`, or opening many distinct `tx_session_id`s, grows `active_sessions` unbounded until the 300s timeout sweeps it. LoRa bandwidth limits the practical severity, but it's a real memory-growth vector against the server process with no cap today.
**Fix:** add a sane max `total_chunks` (derivable from a reasonable max tx size ÷ `DEFAULT_CHUNK_SIZE`) and/or a max concurrent-sessions-per-sender cap, rejecting/NACKing chunks that exceed it.

### 5. `_abort_event` is shared across all sessions despite the "session isolation" claim
**File:** [client/sender.py:199](../client/sender.py#L199) (docstring), [line 231](../client/sender.py#L231) (`self._abort_event = threading.Event()`), [line 300](../client/sender.py#L300) (`self._abort_event.clear()`)
The class docstring claims "Supports concurrent sends via session isolation," but there is exactly one `threading.Event` shared by the whole `TransactionSender` instance. Every call to `send_transaction()` unconditionally clears it at the start ([line 300](../client/sender.py#L300)). If two sends run concurrently on the same instance, starting a second session silently un-aborts the first (if `abort()` was just called on it), or `abort()` called for one session aborts the other.
**Fix:** key `_abort_event` per-session (e.g. store it on `SendSession`, or a `Dict[str, threading.Event]`) and check the session's own event in `_send_all_chunks`.

### 6. RPC credentials embedded unescaped in URL; diagnostic logging is unreachable in production
**File:** [core/rpc_client.py:31](../core/rpc_client.py#L31)
```python
self.uri = f"http://{user}:{password}@{host}:{port}"
```
No URL-encoding — special characters in the password (`@`, `:`, `/`, `#`) corrupt the URI. Separately, nearly every log call in this file is `.debug()` ([lines 37, 42, 67, 75, 77, 80, 84, 100, 104, 108, 111, 114](../core/rpc_client.py)), but `server_logger` is fixed at `INFO` ([core/logger_setup.py:15](../core/logger_setup.py#L15)) with no env/config override — so none of this diagnostic detail (including the retry attempts from finding #1) is ever visible in normal operation. `str(e)` from `requests` exceptions frequently embeds the full request URL including plaintext credentials, so if DEBUG is ever turned on for troubleshooting, credentials can land directly in the log file.
**Fix:** `urllib.parse.quote(user, safe='')` / `quote(password, safe='')` when building the URI; promote key RPC error logs to `.warning()`/`.error()` so they're visible at the default level, and scrub the URI from any logged exception text.

### 7. Server GUI can't start with cookie-based RPC auth; CLI can
**File:** [btcmesh_server_gui.py:706-739](../btcmesh_server_gui.py#L706-L739) vs [core/config_loader.py:114-145](../core/config_loader.py#L114-L145) (`load_bitcoin_rpc_config`)
The CLI path builds its RPC config via `load_bitcoin_rpc_config()`, which supports `BITCOIN_RPC_COOKIE`-based auth. The GUI instead builds its own dict straight from four text fields and hard-requires all four (`host`, `port`, `user`, `password`) to be non-empty before allowing "Start Server":
```python
if not host or not port or not user or not password:
    self.status_log.add_message("Cannot start: Please fill in all RPC settings fields", COLOR_ERROR)
    return
```
An operator using cookie auth (no static RPC password — the more secure setup) can run the relay via CLI but cannot start it from the GUI at all.
**Fix:** route the GUI's RPC config construction through `load_bitcoin_rpc_config()` (or a shared helper), and let the field-completeness check accept "cookie configured" as an alternative to "user+password filled in."

### 8. Client CLI has no validation on `--destination`; GUI does
**File:** [btcmesh_client_cli.py:108-120](../btcmesh_client_cli.py#L108-L120) vs [btcmesh_client_gui.py:297-335](../btcmesh_client_gui.py#L297-L335)
The CLI validates only `--tx`. The GUI's `validate_send_inputs` separately checks that `dest` is non-empty, starts with `!`, and isn't the sender's own node — but this logic lives only in the GUI, not in `client/sender.py` (the layer both UIs delegate to). Running `btcmesh_client_cli.py -d "" -tx <hex>` gets no CLI-level or shared-layer feedback; whatever the Meshtastic library eventually raises is the only signal.
**Fix:** move destination validation into `client/sender.py::send_transaction()` (or a small shared `validate_destination()` in `core/protocol.py`) so both UIs get it for free — this is the CLAUDE.md "no duplicated logic" rule pointing the other way (logic that should exist once, shared, rather than once, per-UI).

---

## LOW severity

### 9. Three independent parsers of the same `BTC_TX|...` wire format, with a confirmed behavioral divergence
`core/protocol.py::parse_chunk`, `core/reassembler.py::_parse_chunk`, and `server/receiver.py::_on_message`'s ad-hoc pre-parse (built only to construct the ACK reply string) all parse the identical format independently. Confirmed divergence: `core/reassembler.py::_parse_chunk` ([lines 109-116](../core/reassembler.py#L109-L116)) allows an empty payload with just a `warning` log, while `core/protocol.py::parse_chunk` raises `ValueError` for the same input. `reassembler.py`'s own comment already flags this as a known TODO.
**Fix:** consolidate on `core/protocol.py::parse_chunk` as the single source of truth; have `reassembler.py` and `receiver.py` call it instead of re-implementing.

### 10. Node-ID formatting duplicated three ways, one instance has an actual bug
`transport/meshtastic_serial.py:397` and `core/meshtastic_utils.py:107` both correctly zero-pad: `f"!{node_num:08x}"`. `btcmesh_client_gui.py:556` does it inline, **without** zero-padding: `f"!{iface.myInfo.my_node_num:x}"`. For a node number like `0x00abcd12` this produces `!abcd12` instead of `!00abcd12`, inconsistent with every other place in the codebase. The existing test (`tests/test_btcmesh_client_gui.py:656-687`) uses a node number that happens to already be 8 hex digits, so the bug is untested and invisible today. Notably, the correctly-formatted value is already available at [btcmesh_client_gui.py:547-548](../btcmesh_client_gui.py#L547-L548) via `transport.local_node_id` — the GUI just doesn't use it here.
**Fix:** replace the inline f-string with the already-computed `transport.local_node_id`.

### 11. Non-atomic JSON writes in transaction history — corruption silently resets history to empty
**File:** `core/transaction_history.py` `_save_data()` (plain `open(...,'w')` + `json.dump()`) and `_load_data()`'s `except (json.JSONDecodeError, FileNotFoundError): return {"version": 1, "transactions": []}`.
A crash or concurrent writer (GUI + CLI pointed at the same history file) mid-write can corrupt the JSON file; the next read doesn't surface this — it silently resets history to empty.
**Fix:** write to a temp file in the same directory and `os.replace()` into place for atomicity.

### 12. Server orchestration/wiring logic duplicated near-verbatim between CLI and GUI
`btcmesh_server_cli.py:27-32`/`49-99`/`152-171` and `btcmesh_server_gui.py:96-101`/`811-890`/`915-936` define identical constants (with an identical copy-pasted comment) and wire up the same set of receiver callbacks (`on_chunk_received`, `on_broadcast`, `on_error`, watchdog hooks) and the same polling loop — only the output sink differs (logger vs. GUI queue). Both files' docstrings claim "all business logic lives in server/receiver.py," but this wiring exists only in the two UI entrypoints, copy-pasted. Similarly, `btcmesh_server_gui.py:585-622` implements a Tor-reachability pre-check (`socket` connect to `127.0.0.1:9050`) that exists nowhere else — real server startup in both CLI and GUI skips it, so a misconfigured Tor host only surfaces as a raw low-level exception at real startup instead of the friendly message the GUI's "Test Connection" button gives.
**Fix:** extract the callback-wiring + polling loop into a shared `server/` helper (e.g. `server/run_loop.py`) that both entrypoints call with a sink-callback parameter; move the Tor pre-check into `core/rpc_client.py` or a `server/` helper so real startup benefits from it too.

### 13. Misc smaller findings (grouped — each independently low-impact)
- **[core/rpc_client.py:13-14](../core/rpc_client.py#L13-L14)** — `BitcoinRPCException.__str__` does `'%d: %s' % (self.code, self.message)`; if `error_info` lacks a `'code'` key, `self.code` falls back to the string `'Unknown code'` ([line 9](../core/rpc_client.py#L9)), and `%d` on a string raises `TypeError` — an edge case that crashes while formatting the error itself. Fix: use `'%s: %s'`.
- **[server/receiver.py:26](../server/receiver.py#L26)** — `_MAX_NACK_LEN = 200` duplicates `core/constants.py:38`'s `MAX_NACK_LENGTH = 200` as a separate literal instead of importing it.
- **[core/config_loader.py:124-125, 138-139](../core/config_loader.py)** — `load_bitcoin_rpc_config()` reads the same `user`/`password` env vars twice (once unconditionally, again in the cookie-absent branch) — dead duplication, not a bug, but confusing.
- **`core/gui_common.py`** imports Kivy directly, which conflicts with CLAUDE.md's description of `core/` as "pure business logic, no I/O" — structural placement smell (belongs under a `gui/` package), not a logic bug.
- **`requirements.txt`** pins no version numbers at all for any dependency, and two listed dependencies (`python-bitcoinrpc`, `stem`) are never imported anywhere in the codebase (confirmed via grep) — pure unused supply-chain surface.
- **`btcmesh_client_gui.py:13-15`** imports `argparse`, `io`, `sys` — unused anywhere in the file (verified via grep), leftover from an earlier design.
- **`btcmesh_client_gui.py`** `process_result()` — the `'print'`, `'cli_finished'`, `'tx_success'`, and `'aborted'` branches are unreachable dead code, explicitly marked "kept for backwards compatibility, will be removed in Step 7" — worth finishing that cleanup.
- **`core/gui_common.py:35`** — `COLOR_SECUNDARY` is a misspelling of "SECONDARY," baked into the shared module's public API and used ~15+ times across both GUIs.
- **`btcmesh_client_cli.py:33-35`** — `-tx`/`--tx` is a two-character short option, unconventional next to `-d`/`--destination`.
- Three stray `test_*.py` scripts sit at repo root outside `tests/` (`test_bitcoin_connection.py`, `test_active_sessions_visual.py`, `test_popup_visual.py`); the first still references a `btcmesh_server.py` file that no longer exists under that name.

---

## What's done well (worth naming, not just gaps)

- `server/receiver.py`'s "grace period cache" (`_completed_sessions`) that resends the final ACK/NACK if a client retransmits after losing it is a thoughtful, non-obvious design choice.
- `transport/meshtastic_serial.py` has deliberate hardening: explicit self-message filtering, explicit "must be addressed to us" filtering with a documented security rationale, and a reimplementation of `getMetadata()` to avoid unwanted stdout side effects.
- `core/device_watchdog.py` / `transport/power_control.py` are well-designed and defensively coded (cooldowns to avoid power-cycle thrashing, identity verification via `local_node_id` rather than trusting OS paths).
- `core.device_watchdog.build_device_watchdog()` is correctly reused identically by all three of the client GUI, server CLI, and server GUI — the pattern the server-orchestration duplication (finding #12) should have followed.
- Test coverage is structurally broad — nearly every module in `core/`, `client/`, `server/`, `transport/` has a matching test file; the architectural duplication findings above are things that are well *unit-tested in place*, not untested code.
- `core/protocol.py`'s chunk/ACK/NACK parsing and `chunk_transaction`/session-ID generation are clean, pure, consistently raise `ValueError`, and have no I/O — a good example of the intended core-layer pattern.
