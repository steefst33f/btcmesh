# BTCMesh Protocol Specification

Version 1.0 — February 2026

## Overview

BTCMesh uses a stop-and-wait ARQ protocol to reliably transmit Bitcoin raw transactions over LoRa Meshtastic direct messages. Transactions are chunked into small pieces that fit within LoRa payload limits, sent one at a time with acknowledgment, and reassembled by the server for broadcast to the Bitcoin network.

## Protocol Flow

<img src="images/btc_mesh_protocol_flow.png" width="500" alt="BTCMesh Protocol Flow">

## Message Types

### 1. BTC_TX (Client → Server)

Transaction chunk containing a fragment of the raw transaction hex.

**Format:** `BTC_TX|<session_id>|<chunk_number>/<total_chunks>|<hex_payload>`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | 5-character hex session identifier |
| `chunk_number` | integer | 1-indexed chunk number |
| `total_chunks` | integer | Total number of chunks in session |
| `hex_payload` | string | Fragment of raw transaction hex |

**Example:** `BTC_TX|a1b2c|1/3|02000000000108bf2c7d...`

### 2. BTC_CHUNK_ACK (Server → Client)

Server acknowledges receipt of a chunk and requests the next, or confirms all chunks received.

**Format (intermediate):** `BTC_CHUNK_ACK|<session_id>|<chunk_number>|REQUEST_CHUNK|<next_chunk>`

**Format (final):** `BTC_CHUNK_ACK|<session_id>|<chunk_number>|ALL_CHUNKS_RECEIVED`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session being acknowledged |
| `chunk_number` | integer | Chunk that was received |
| `command` | string | `REQUEST_CHUNK` or `ALL_CHUNKS_RECEIVED` |
| `next_chunk` | integer | Next expected chunk (only with `REQUEST_CHUNK`) |

**Examples:**
- `BTC_CHUNK_ACK|a1b2c|1|REQUEST_CHUNK|2`
- `BTC_CHUNK_ACK|a1b2c|3|ALL_CHUNKS_RECEIVED`

### 3. BTC_ACK (Server → Client)

Confirms transaction was successfully broadcast to the Bitcoin network.

**Format:** `BTC_ACK|<session_id>|TXID:<txid>`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session that was broadcast |
| `txid` | string | Bitcoin transaction ID returned by the node |

**Example:** `BTC_ACK|a1b2c|TXID:abc123def456789...`

### 4. BTC_NACK (Server → Client)

Reports an error during reassembly, validation, or broadcast.

**Format:** `BTC_NACK|<session_id>|<error_detail>`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session that failed |
| `error_detail` | string | Condensed error message (to make sure it fits within payload and protocol) |

**Example:** `BTC_NACK|a1b2c|Insufficient fee`

Total NACK message length is capped at 200 characters to fit LoRa payload constraints.

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| Chunk size | 170 hex chars (85 bytes) | Maximum hex payload per chunk |
| Session ID length | 5 hex chars | Random UUID-derived identifier |
| ACK timeout | 30 seconds | Client waits this long for server ACK |
| Max retries | 3 | Maximum retry attempts per chunk |
| Reassembly timeout | 300 seconds (5 min) | Server discards incomplete sessions after this |

## Session ID

- Created by the client and send with each message
- 5-character lowercase hex string
- Generated from `uuid4().hex[:5]`
- Unique per transaction attempt
- Used to correlate chunks, ACKs, and final result across the session

Without session IDs, chunks from different transactions would be impossible to distinguish, especially in a mesh network where messages can arrive out of order or from multiple sources.

## Stop-and-Wait ARQ

The client uses a stop-and-wait Automatic Repeat Request protocol:

1. Send chunk N
2. Wait up to 30 seconds for `BTC_CHUNK_ACK` with matching session and chunk number
3. If ACK received with `REQUEST_CHUNK|N+1`: send chunk N+1
4. If ACK received with `ALL_CHUNKS_RECEIVED`: wait for final `BTC_ACK` or `BTC_NACK`
5. If no ACK received within timeout: retry (up to 3 times)
6. If max retries exceeded: abort session

## Error Condensing

The server condenses RPC error messages for LoRa size constraints. Common mappings:

| Bitcoin Core Error | Condensed |
|-------------------|-----------|
| Transaction outputs already in utxo set | TX already in UTXO set |
| Transaction already in block chain | TX already in chain |
| insufficient fee | Insufficient fee |
| missing inputs | Missing inputs |
| bad-txns-inputs-spent | Inputs spent |
| bad-txns-in-belowout | Input < Output |
| too-long-mempool-chain | Chain too long |
| mempool full | Mempool full |
| replacement transaction | RBF disabled |
| non-mandatory-script-verify-flag | Script verify failed |
| bad-txns-nonstandard-inputs | Non-std inputs |
| bad-txns-oversize | TX too large |
| dust | Dust output |
| fee is too high | Fee too high |
| absurdly-high-fee | Absurd fee |

For reassembly errors (InvalidChunkFormat, MismatchedTotalChunks), the error type and detail are included, truncated to fit the 200-character NACK limit.

## Chunk Sizing

Each Meshtastic text message has a payload limit. The chunk format includes overhead:

```
BTC_TX|<5 chars>|<digits>/<digits>|<payload>
```

With a 5-char session ID and typical chunk numbering (e.g. `12/15`), overhead is ~20 characters. The 170 hex-char payload keeps total message size well within Meshtastic payload limits.

## Multiple Concurrent Sessions

The server supports multiple concurrent sessions from different senders. Sessions are keyed by `(sender_node_id, session_id)`. Each session independently tracks received chunks and timeouts.

---

## UML Diagrams

### 1. Message Class Diagram

```mermaid
classDiagram
    class ChunkMessage {
        -session_id: str
        -chunk_number: int
        -total_chunks: int
        -payload: str
        +format() str
    }

    class ChunkAckMessage {
        -session_id: str
        -chunk_number: int
        -request_next_chunk: int | None
        -all_received: bool
        +format() str
    }

    class AckMessage {
        -session_id: str
        -txid: str
        +format() str
    }

    class NackMessage {
        -session_id: str
        -error_detail: str
        +format() str
    }

    class TransactionSession {
        -session_id: str
        -chunks: List~str~
        +total_chunks: int
    }
```

**Message Types:**

| Class | Direction | Purpose | Wire Format |
|-------|-----------|---------|-------------|
| `ChunkMessage` | Client→Server | Send transaction chunk | `BTC_TX\|session\|chunk/total\|payload` |
| `ChunkAckMessage` | Server→Client | Acknowledge chunk or signal all received | `BTC_CHUNK_ACK\|session\|chunk\|...` |
| `AckMessage` | Server→Client | Broadcast success with TXID | `BTC_ACK\|session\|TXID:txid` |
| `NackMessage` | Server→Client | Error response | `BTC_NACK\|session\|error` |
| `TransactionSession` | Internal only | Holds session ID + chunked TX list | Not sent (used by sender) |

**First 4 are wire messages, last is internal use only.**

### 2. Client State Machine

```mermaid
stateDiagram-v2
    [*] --> INIT

    INIT --> VALIDATE: Validate transaction hex
    VALIDATE --> ERROR_INVALID: If invalid

    VALIDATE --> CREATE_SESSION: If valid - create session
    CREATE_SESSION --> SEND_CHUNK: Session created with chunks

    SEND_CHUNK --> WAITING_ACK: Send BTC_TX (30s timer)

    WAITING_ACK --> ACK_RECEIVED: BTC_CHUNK_ACK received
    WAITING_ACK --> TIMEOUT: No response
    WAITING_ACK --> NACK_RECEIVED: BTC_NACK

    ACK_RECEIVED --> MORE_CHUNKS: Check if more

    MORE_CHUNKS --> SEND_CHUNK: Yes - send next
    MORE_CHUNKS --> WAITING_FINAL: No - all sent

    TIMEOUT --> RETRY: Check retries

    RETRY --> SEND_CHUNK: < 3 attempts
    RETRY --> ERROR_TIMEOUT: >= 3 attempts

    WAITING_FINAL --> FINAL_RESULT: Wait for result

    FINAL_RESULT --> SUCCESS: BTC_ACK received
    FINAL_RESULT --> ERROR_NACK: BTC_NACK received

    NACK_RECEIVED --> ERROR_NACK

    SUCCESS --> CLEANUP: End session
    ERROR_INVALID --> CLEANUP: End session
    ERROR_TIMEOUT --> CLEANUP: End session
    ERROR_NACK --> CLEANUP: End session

    CLEANUP --> [*]

    style SUCCESS fill:#90EE90,color:#000
    style ERROR_INVALID fill:#FFB6C6,color:#000
    style ERROR_TIMEOUT fill:#FFB6C6,color:#000
    style ERROR_NACK fill:#FFB6C6,color:#000
    style CLEANUP fill:#DDD,color:#000
```

### 3. Server State Machine

```mermaid
stateDiagram-v2
    [*] --> LISTENING

    LISTENING --> RECEIVE_MSG: Message arrives

    RECEIVE_MSG --> MSG_TYPE: Check type

    MSG_TYPE --> SESSION: If BTC_TX
    MSG_TYPE --> LISTENING: Else

    SESSION --> CREATE_BUFFER: New session
    SESSION --> APPEND: Existing session

    CREATE_BUFFER --> APPEND: Add chunk

    APPEND --> SEND_ACK: Send BTC_CHUNK_ACK

    SEND_ACK --> ALL_CHUNKS: Check complete

    ALL_CHUNKS --> CHECK_TIMEOUT: If incomplete
    ALL_CHUNKS --> REASSEMBLE: If complete

    CHECK_TIMEOUT --> LISTENING: Not expired
    CHECK_TIMEOUT --> TIMEOUT_DISCARD: Expired (>300s)

    REASSEMBLE --> VALIDATE: Validate format

    VALIDATE --> IS_VALID: Check validity

    IS_VALID --> BROADCAST: If valid
    IS_VALID --> SEND_NACK: If invalid

    BROADCAST --> BCAST_OK: Check result

    BCAST_OK --> SEND_FINAL_ACK: If success
    BCAST_OK --> SEND_NACK: If failed

    SEND_NACK --> END_SESSION: Cleanup
    SEND_FINAL_ACK --> END_SESSION: Cleanup
    TIMEOUT_DISCARD --> END_SESSION: Cleanup

    END_SESSION --> LISTENING

    style SEND_FINAL_ACK fill:#90EE90,color:#000
    style SEND_NACK fill:#FFB6C6,color:#000
    style TIMEOUT_DISCARD fill:#FFB6C6,color:#000
```

### 4. Complete Protocol Sequence (Happy Path - Success)

```mermaid
sequenceDiagram
    participant C as Client
    participant M as Mesh
    participant S as Server
    participant B as Bitcoin RPC

    C->>C: Validate TX hex
    C->>C: Create session (generates ID, chunks TX)

    loop Send each chunk i of n
        C->>M: BTC_TX|abc12|i/n|payload
        M->>S: [LoRa]
        S->>S: Buffer chunk i
        S->>M: BTC_CHUNK_ACK|abc12|i|REQUEST|i+1
        M->>C: [LoRa]
        C->>C: Got ACK, continue
    end

    S->>S: All n chunks received
    S->>S: Reassemble transaction
    S->>S: Validate protocol format

    S->>B: broadcast_transaction()
    B->>B: Add to mempool
    B-->>S: TXID: beef00cafe...

    S->>M: BTC_ACK|abc12|TXID:beef00...
    M->>C: [LoRa]
    C->>C: ✓ Success!
```

### 4b. Error Scenarios During Chunk Sending

```mermaid
sequenceDiagram
    participant C as Client
    participant M as Mesh
    participant S as Server

    C->>C: Validate TX hex
    C->>C: Create session

    loop Attempt to send chunk i
        C->>M: BTC_TX|abc12|i/n|payload
        M->>S: [LoRa]

        alt NACK received
            S->>M: BTC_NACK|abc12|Invalid payload format
            M->>C: [LoRa]
            C->>C: ✗ Session failed (no retry)
        else Timeout (no ACK for 30s)
            C->>C: Timeout! Retry count++
            alt Retries < 3
                C->>C: Continue loop (resend chunk)
            else Retries >= 3
                C->>C: ✗ Max retries exceeded, fail
            end
        end
    end

    C->>C: Cleanup session
```

**Key differences:**
- **NACK during chunks**: Session fails immediately (no retry)
- **Timeout**: Retried up to 3 times within the loop
- Both paths lead to session cleanup

### 4c. Error Scenarios After Chunks Complete

```mermaid
sequenceDiagram
    participant C as Client
    participant M as Mesh
    participant S as Server
    participant B as Bitcoin RPC

    C->>C: Validate TX hex
    C->>C: Create session (generates ID, chunks TX)

    loop Send each chunk i of n
        C->>M: BTC_TX|abc12|i/n|payload
        M->>S: [LoRa]
        S->>S: Buffer chunk i
        S->>M: BTC_CHUNK_ACK|abc12|i|REQUEST|i+1
        M->>C: [LoRa]
    end

    S->>S: All n chunks received
    S->>S: Reassemble transaction
    S->>S: Validate protocol format

    alt Reassembly or Protocol Error
        S->>M: BTC_NACK|abc12|Invalid chunk format
        M->>C: [LoRa]
        C->>C: ✗ Protocol error
    else Broadcast Failed (RPC validation)
        S->>B: broadcast_transaction()
        B-->>S: Error: Insufficient fee
        S->>M: BTC_NACK|abc12|Insufficient fee
        M->>C: [LoRa]
        C->>C: ✗ Broadcast failed
    end

    C->>C: Cleanup session
```

**Failure points:**
- **Reassembly validation error**: Malformed protocol format, mismatched chunk counts, etc. (checked by reassembler)
- **Broadcast error**: Invalid TX signature, insufficient fee, missing inputs, non-standard TX, mempool full, etc. (detected by Bitcoin RPC)
- No retry at this level (session ends)

### 5. Session Lifecycle Timeline

```mermaid
graph LR
    A["T0: First chunk arrives"]
    B["Chunks buffered, ACKs sent"]
    C["T1: Last chunk arrives"]
    D["T2: Reassemble & validate"]
    E["T3: Broadcast to Bitcoin"]
    F["T4: Send final result"]

    G["FAIL: T > 300s - Timeout, discarded"]

    A -->|t ≤ 20ms| B
    B -->|t ≤ 60s| C
    C -->|t ≤ 70s| D
    D -->|t ≤ 80s| E
    E -->|t ≤ 90s| F

    B -.->|t > 300s| G

    style F fill:#90EE90,color:#000
    style G fill:#FFB6C6,color:#000
```
