# Story 22.1 Implementation Plan: Create client/sender.py

## Context

**Why this change:**
Currently, transaction sending logic is tightly coupled to the CLI (`btcmesh_cli.py`). This makes it impossible for the GUI (`btcmesh_gui.py`) or future iOS/Android apps to reuse this logic without duplicating code.

**Goal:**
Extract the transaction sending orchestration into a reusable `client/sender.py` module that:
- Works with any `BaseTransport` implementation (not just Meshtastic serial)
- Implements the stop-and-wait ARQ protocol in a testable, pure way
- Provides clear separation between business logic and I/O
- Enables CLI, GUI, and mobile apps to all use the same sender implementation

**Outcome:**
A `TransactionSender` class that can be imported by CLI, GUI, and tested independently without needing Meshtastic hardware.

---

## Architecture Overview

### What Gets Extracted

The CLI currently handles **all three concerns** in one blob:

```
btcmesh_cli.py:
├── Argument parsing (UI concern) ✅ STAYS in CLI
├── Meshtastic interface management (transport concern) ✅ STAYS in CLI (for now)
└── TRANSACTION SENDING ORCHESTRATION 🔨 MOVE TO client/sender.py
    ├── Session tracking (chunks sent, ACKs received, retry counts)
    ├── Stop-and-wait state machine (send chunk N, wait for ACK, next chunk)
    ├── Timeout and retry handling
    ├── Message routing (which ACK belongs to which chunk)
    └── Error handling and session cleanup
```

### What Already Exists (REUSE)

From exploration, these components are already available:

1. **core/protocol.py** - Protocol-level functions:
   - `create_session(tx_hex)` → chunked `TransactionSession`
   - `get_chunk_message(session, index)` → formatted `ChunkMessage` for sending
   - `parse_message(msg_str)` → dispatcher to parse `ChunkAckMessage`, `AckMessage`, `NackMessage`

2. **transport/base.py** - Abstract interface:
   - `send(message, destination)` - Send a message
   - `set_message_handler(callback)` - Register receive handler
   - Works with any transport backend

3. **Test patterns** - From existing `tests/test_btcmesh_cli.py`:
   - Dependency injection (inject mock transport + mock message generator)
   - Generator-based simulation of server responses
   - Mock verification of call order

### What's New in client/sender.py

Three new concepts:

1. **Session State Machine** - Track each transaction:
   ```python
   class SendSession:
       session_id: str
       total_chunks: int
       chunks_sent: set[int]           # {1, 2, 3}
       retry_counts: dict[int, int]    # {1: 0, 2: 1, ...}
       acks_received: dict[int, bool]  # {1: True, 2: False}
       all_chunks_received: bool
       error: Optional[str]
   ```

2. **TransactionSender Class** - Orchestrator:
   - Holds active sessions
   - Routes incoming ACK/NACK messages to correct session
   - Implements stop-and-wait: send chunk, wait for ACK, then next chunk
   - Handles timeouts and retries
   - **Pure code**: no print statements, no logging, no file I/O
   - Raises `ValueError`/`RuntimeError` on errors

3. **SendResult Dataclass** - Return value:
   ```python
   @dataclass
   class SendResult:
       success: bool
       session_id: str
       txid: Optional[str]    # Only set if success=True
       error: Optional[str]   # Only set if success=False
   ```

---

## Implementation Plan

### Phase 1: Data Structures (Low Risk)

#### 1.1 Create `SendResult` dataclass
- **File:** `client/sender.py`
- **Definition:**
  ```python
  @dataclass
  class SendResult:
      success: bool
      session_id: str
      txid: Optional[str] = None
      error: Optional[str] = None

      def __post_init__(self):
          # Validation: success=True requires txid, success=False requires error
          if self.success and not self.txid:
              raise ValueError("success=True requires txid")
          if not self.success and not self.error:
              raise ValueError("success=False requires error")
  ```

#### 1.2 Create `SendSession` (internal state tracker)
- **File:** `client/sender.py`
- **Definition:**
  ```python
  class SendSession:
      def __init__(self, session_id: str, total_chunks: int, my_node_id: str):
          self.session_id = session_id
          self.total_chunks = total_chunks
          self.my_node_id = my_node_id
          self.chunks_sent = set()                    # {1, 2, 3}
          self.chunks_acked = set()                   # {1, 2}
          self.retry_counts = {}                      # {1: 0, 2: 1}
          self.sent_timestamps = {}                   # {1: time.time()}
          self.current_chunk_index = 0                # 1-indexed
          self.all_chunks_received = False
          self.final_txid = None
          self.error = None
          self.failed = False
  ```
- **Methods:**
  - `needs_resend(chunk_num, timeout) -> bool` - Check if chunk is stalled
  - `mark_chunk_acked(chunk_num)` - Record successful ACK
  - `increment_retry(chunk_num)` - Track retry attempts
  - `is_complete() -> bool`

---

### Phase 2: TransactionSender Core (Medium Risk)

#### 2.1 Constructor & Initialization
- **Method:** `__init__(self, transport: BaseTransport, timeout_seconds: int = 30, max_retries: int = 3)`
- **Initialize:**
  - Store transport reference
  - Store timeout_seconds and max_retries as instance variables
  - Create empty sessions dict
  - Call `_setup_message_handler()` to register callback with transport
- **Design note:** Timeout values are class-level defaults used for all send calls (can override per-call if needed later)

#### 2.2 Message Handler Setup
- **Method:** `_setup_message_handler()`
- **Action:** Register `self._on_message` callback:
  ```python
  def _setup_message_handler(self):
      handler = lambda msg, sender_id: self._on_message(msg, sender_id)
      self.transport.set_message_handler(handler)
  ```

#### 2.3 Main Send Method
- **Method:** `send_transaction(tx_hex: str, destination: str, on_progress: Optional[Callable] = None) -> SendResult`
- **Signature notes:**
  - `on_progress(chunk_num, total_chunks) -> None` - called after each chunk send
  - Optional: if not provided, no progress callback
  - Returns immediately with SendResult (blocking inside for orchestration)
- **Flow:**
  1. Validate tx_hex using `core/protocol.validate_transaction_hex()`
  2. Create session: `session = create_session(tx_hex)`
  3. Create `SendSession(session_id)` and store in `self.sessions[session_id]`
  4. Call `_send_all_chunks(destination, session, timeout, max_retries, on_progress)`
  5. Wait for completion (use threading event or similar)
  6. Return `SendResult`
- **Concurrency note:** Multiple concurrent calls to `send_transaction()` are supported via session isolation
- **Error cases:**
  - InvalidHex → `SendResult(success=False, error="Invalid hex")`
  - Transport not connected → `SendResult(success=False, error="Transport not connected")`
  - Max retries exceeded → `SendResult(success=False, error="Max retries exceeded")`

#### 2.4 Stop-and-Wait Sender
- **Method:** `_send_all_chunks(destination, session, timeout, max_retries) -> None`
- **Pseudocode:**
  ```python
  send_session = self.sessions[session.session_id]

  for chunk_index in range(len(session.chunks)):
      current_chunk_num = chunk_index + 1
      max_attempts = max_retries

      while max_attempts > 0:
          # Send
          msg = session.chunks[chunk_index]
          self.transport.send(msg, destination)
          send_session.chunks_sent.add(current_chunk_num)
          send_session.sent_timestamps[current_chunk_num] = time.time()

          # Wait for ACK (blocking wait, max timeout seconds)
          if self._wait_for_chunk_ack(session.session_id, current_chunk_num, timeout):
              break  # Got ACK, move to next chunk
          else:
              max_attempts -= 1
              if max_attempts == 0:
                  send_session.error = f"Chunk {current_chunk_num}: timeout after 3 retries"
                  send_session.failed = True
                  return

  # All chunks sent, wait for final BTC_ACK
  if self._wait_for_final_ack(session.session_id, timeout * 2):
      # Success!
      send_session.final_txid = <extracted from BTC_ACK>
  else:
      send_session.error = "No final ACK from relay"
      send_session.failed = True
  ```

#### 2.5 ACK Waiting
- **Method:** `_wait_for_chunk_ack(session_id: str, chunk_num: int, timeout_seconds: int) -> bool`
- **Implementation:** Use `threading.Event` or `queue.Queue` to block until message arrives
- **Returns:** `True` if ACK received, `False` if timeout

#### 2.6 Incoming Message Handler
- **Method:** `_on_message(message_text: str, sender_id: str)`
- **Logic:**
  1. Parse message: `msg = parse_message(message_text)` (may raise ValueError)
  2. Find session: `session = self.sessions.get(msg.session_id)` (ignore if not found)
  3. Route by message type:
     - **ChunkAckMessage** → `_handle_chunk_ack(session, msg)`
     - **AckMessage** → `_handle_final_ack(session, msg)`
     - **NackMessage** → `_handle_nack(session, msg)`

#### 2.7 Response Handlers
- **Method:** `_handle_chunk_ack(session: SendSession, msg: ChunkAckMessage)`
  - Mark chunk as acked: `session.mark_chunk_acked(msg.chunk_number)`
  - Signal waiting thread via event

- **Method:** `_handle_final_ack(session: SendSession, msg: AckMessage)`
  - Extract TXID from msg.txid_field
  - Set `session.final_txid = txid`
  - Signal completion

- **Method:** `_handle_nack(session: SendSession, msg: NackMessage)`
  - Set `session.error = msg.error_detail`
  - Set `session.failed = True`
  - Signal completion

---

### Phase 3: Result Compilation (Low Risk)

#### 3.1 Build SendResult
- **Method:** `_build_result(send_session: SendSession) -> SendResult`
- **Logic:**
  ```python
  if not send_session.failed and send_session.final_txid:
      return SendResult(
          success=True,
          session_id=send_session.session_id,
          txid=send_session.final_txid
      )
  else:
      return SendResult(
          success=False,
          session_id=send_session.session_id,
          error=send_session.error or "Unknown error"
      )
  ```

#### 3.2 Cleanup
- **Method:** `_cleanup_session(session_id: str)`
- **Action:** Remove from `self.sessions` dict (optional, can let GC handle)

---

### Phase 4: Comprehensive Tests (High Risk)

#### 4.1 Test Structure
- **File:** `tests/test_client_sender.py`
- **Pattern:** Use dependency injection (mock transport + mock message generator)
- **Example test:**
  ```python
  def test_single_chunk_transaction(self):
      # Setup
      mock_transport = Mock(spec=BaseTransport)
      sent_messages = []
      mock_transport.send = lambda msg, dest: sent_messages.append((msg, dest))

      sender = TransactionSender(mock_transport)

      # Simulate server responses via message_handler callback
      handler = mock_transport.set_message_handler.call_args[0][0]

      # Send
      task = threading.Thread(
          target=lambda: sender.send_transaction("abcd" * 100, "!deadbeef"),
          daemon=True
      )
      task.start()

      # Simulate server responses
      time.sleep(0.1)  # Let sender send chunk
      handler("BTC_CHUNK_ACK|abc123|1|ALL_CHUNKS_RECEIVED", "!aabbccdd")
      time.sleep(0.1)  # Let sender process
      handler("BTC_ACK|abc123|TXID:mytxid", "!aabbccdd")

      task.join(timeout=5)

      # Verify
      self.assertEqual(len(sent_messages), 1)
      result = sender.sessions["abc123"]
      self.assertTrue(result.success)
      self.assertEqual(result.txid, "mytxid")
  ```

#### 4.2 Test Cases (Comprehensive Coverage)

**Happy path:**
- Single-chunk transaction
- Multi-chunk transaction (3 chunks)
- Verify chunk order is correct
- Verify TXID extracted correctly

**Error handling:**
- Invalid hex (non-hex chars)
- Empty hex
- Timeout on chunk (retry 3x then fail)
- Server NACK on chunk
- Server NACK on final ACK
- All retries exhausted

**Message filtering:**
- Ignore messages for wrong session ID
- Ignore messages from wrong sender
- Ignore malformed chunk messages

**Retry logic:**
- Send chunk, timeout, resend → success
- Send chunk, timeout, timeout, timeout → fail after 3 attempts

---

## Critical Files & Functions to Reference

| File | What to Use |
|------|-------------|
| `core/protocol.py` | `create_session()`, `get_chunk_message()`, `parse_message()` |
| `core/message_types.py` | `ChunkMessage`, `ChunkAckMessage`, `AckMessage`, `NackMessage`, dataclasses |
| `core/constants.py` | `DEFAULT_CHUNK_SIZE`, `DEFAULT_ACK_TIMEOUT`, protocol delimiters |
| `transport/base.py` | `BaseTransport`, `TransportSendError`, `TransportConnectionError` |
| `tests/test_btcmesh_cli.py` | Mock patterns, generator-based message simulation |

---

## Key Design Decisions

### 1. **Threading Model**
- Use `threading.Event()` to block sender on ACK wait
- Keep handler callback simple (just signal events, don't block)
- **Alternative considered:** Use `queue.Queue()` — rejected (Events simpler for binary wait)

### 2. **Concurrency Model**
- Support multiple concurrent `send_transaction()` calls
- Each call gets a unique session_id (from `create_session()`)
- Message handler routes ACK/NACK to correct session via session_id + sender_id
- **Why:** Enables parallel sends if UI needs them (though CLI/GUI likely sequential)
- **Thread-safe:** Message handler uses `dict.get()` which is atomic in Python

### 3. **Progress Tracking**
- Optional `on_progress(chunk_num, total_chunks)` callback
- Called after each chunk sent successfully (not on retries)
- Callback is simple reporting: no blocking, no state changes
- **Alternative considered:** Return list of all ACKs — rejected (YAGNI)

### 4. **Configuration Model**
- Timeout and retry values set at class init time
- Applied to all `send_transaction()` calls
- Example: `sender = TransactionSender(transport, timeout_seconds=60, max_retries=5)`
- **Why:** Simpler than per-call config; future-extensible if needed

### 5. **Error Model**
- Raise `ValueError` for bad input (invalid hex)
- Raise `RuntimeError` for runtime failures (transport error)
- Return `SendResult` for application-level failures (timeout, NACK)
- **Rationale:** Errors that can't be retried → exceptions; errors that are handled → return objects

### 6. **Pure Code** (No I/O except via transport)
- `TransactionSender` is pure: no print(), no logging, no file I/O
- Call site (CLI/GUI) can add logging around `send_transaction()` result
- **Why:** Makes it testable without mocking print/logging

---

## Implementation Order (Recommended)

1. **Data structures first** (SendResult, SendSession classes)
2. **Constructor + handler setup** (lowest risk)
3. **Message parsing callback** (_on_message)
4. **Stop-and-wait orchestration** (complex, test heavily)
5. **Tests** (at every step)
6. **Integration verification** (run with real CLI)

---

## Verification & Testing

### Unit Tests (tests/test_client_sender.py)
- ✅ Happy path: single chunk, multi-chunk
- ✅ Retry logic: timeout → resend → success
- ✅ Error cases: invalid hex, NACK, all retries exhausted
- ✅ Message filtering: wrong session, wrong sender
- Target: 100% coverage of TransactionSender class

### Integration Test
- Refactor CLI to use `TransactionSender` (Story 22.2)
- Verify CLI behavior unchanged: same exit codes, same output
- Run existing CLI tests: `python -m unittest tests.test_btcmesh_cli`

### Manual Verification (Optional)
- Run against dry-run mode first
- Then test with real Meshtastic server (if available)

---

## Files to Create/Modify

| File | Action | Notes |
|------|--------|-------|
| `client/__init__.py` | Create (empty) | New package |
| `client/sender.py` | Create | Main implementation (200-300 LOC) |
| `tests/test_client_sender.py` | Create | Comprehensive tests (400-500 LOC) |
| `btcmesh_cli.py` | Modify later (Story 22.2) | Remove send logic, use TransactionSender |

---

## Success Criteria

✅ `client/sender.py` exists with `TransactionSender` class
✅ Handles stop-and-wait ARQ correctly (verified by tests)
✅ Works with any `BaseTransport` backend
✅ Pure code: no print/logging/I/O (verified by code review)
✅ 100% test coverage of TransactionSender
✅ Existing CLI tests still pass after integration (Story 22.2)
