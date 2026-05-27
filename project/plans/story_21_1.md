# Story 21.1: Create `transport/base.py` Interface

## Context

All three consumers (CLI, server, GUI) directly import and use `meshtastic.serial_interface.SerialInterface` with duplicate initialization, sending, receiving, and cleanup logic. This story creates a protocol-agnostic transport interface that decouples the core business logic (chunking, ACKs, reassembly) from any specific mesh protocol. Different mesh protocols (Meshtastic, MeshCore, Reticulum, bitchat) and connection methods (serial, BLE, WiFi) can be supported by implementing this interface. Note: UI layers (labels, configuration, device scanning) would still need adaptation per protocol.

This is the foundation for Epic 3's transport abstraction — Story 21.2 (Meshtastic serial implementation) and Stories 22.x (client sender refactoring) depend on this interface.

**Scope:** Abstract interface + exceptions + tests only. No concrete implementation (that's Story 21.2).

---

## Files to Create

| File | Purpose |
|------|---------|
| `transport/__init__.py` | Package init, re-exports public API |
| `transport/base.py` | `BaseTransport` ABC + exception hierarchy + `MessageHandler` type alias |
| `tests/test_transport_base.py` | Tests for ABC enforcement, exceptions, contract, imports |

**Reference files for patterns:**
- `core/reassembler.py` — exception hierarchy pattern (`ReassemblyError` -> `InvalidChunkFormatError`)
- `core/protocol.py` — module structure (doc header, section dividers, `from __future__ import annotations`)

---

## Design

### Exception Hierarchy

```
Exception
  └── TransportError                  (base for all transport errors)
        ├── TransportConnectionError  (connect failures: no device, permission, busy)
        └── TransportSendError        (send failures: disconnected, invalid destination)
```

Uses `TransportConnectionError` (not `ConnectionError`) to avoid shadowing Python's built-in.

### `BaseTransport` ABC

```python
class BaseTransport(ABC):
    @abstractmethod
    def connect(self, device_path: Optional[str] = None) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def send(self, message: str, destination: str) -> None: ...
    @abstractmethod
    def set_message_handler(self, handler: MessageHandler) -> None: ...
    @abstractmethod
    def remove_message_handler(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @property
    @abstractmethod
    def local_node_id(self) -> Optional[str]: ...

    def __enter__(self) -> "BaseTransport": return self
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: self.disconnect()
```

### `MessageHandler` Type Alias

```python
MessageHandler = Callable[[str, str], None]  # (message_text, sender_id)
```

The transport extracts text and sender ID from raw packets internally — consumers never see protocol-specific packet structure.

### Key Design Decisions

- **`remove_message_handler()`** — explicit method instead of `set_message_handler(None)`. CLI currently calls `pub.unsubscribe()` in its finally block; this mirrors that pattern.
- **`__enter__` does NOT auto-connect** — connection requires `device_path` and can fail. Context manager is purely for cleanup (ensuring `disconnect()` is called).
- **`local_node_id` format is implementation-defined** — each transport defines its own node identifier format (e.g., Meshtastic uses `!xxxxxxxx`).
- **No protocol-specific parameters on `send()`** — details like `wantAck` are configurable per-implementation via constructor if needed.
- **Device utilities stay separate** — node listing, device scanning, etc. are not part of the transport abstraction. So for the current Meshtastic interface, **Node listing stays in `meshtastic_utils.py`**

---

## Test Plan (`tests/test_transport_base.py`)

Uses a `StubTransport` concrete subclass for contract testing.

| Test Class | What it verifies |
|-----------|-----------------|
| `TestExceptionHierarchy` | Inheritance, no shadowing of builtins, message propagation, catch-by-base |
| `TestABCEnforcement` | Each missing abstract method -> `TypeError` on instantiation; complete impl works |
| `TestTransportContract` | Context manager calls `disconnect()`, state before/after connect/disconnect |
| `TestModuleImports` | Public API importable from both `transport.base` and `transport` |

---

## Implementation Steps

### Step 1: Create `transport/` package
- `mkdir transport`
- Create `transport/__init__.py` with re-exports
- Create `transport/base.py` with exceptions, `MessageHandler` alias, and `BaseTransport` ABC

### Step 2: Create `tests/test_transport_base.py`
- `StubTransport` helper class
- All four test classes (~30 tests)

### Step 3: Run tests and verify
```bash
python -m unittest tests.test_transport_base -v          # New tests pass
python -m unittest discover -s tests -p 'test_*.py'      # Full suite still passes
# Expected: ~575 tests (545 existing + ~30 new), 0 failures
```
