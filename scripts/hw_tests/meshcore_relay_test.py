#!/usr/bin/env python3
"""Real-hardware verification for the MeshCore relay path (Story 30.5).

Drives a full BTC_TX chunked send/receive round trip between two real
MeshCore companion devices, using the exact production classes under
test (TransactionSender, TransactionReceiver) wired together directly in
one script so pass/fail can be asserted programmatically in one run,
instead of needing two terminals and manual log-reading (see
project/issues.txt Issues 50/51/52 for how this test was originally done
by hand, and what it found each time).

Verifies the relay layer, not Bitcoin broadcast: expects the server's
specific "Bitcoin RPC not connected" NACK (no RPC configured), and
asserts the server's reassembled hex exactly matches what was sent -
proof every chunk was relayed, acknowledged, and reassembled correctly,
independent of whether the content is a real spendable transaction.

Usage:
    python scripts/hw_tests/meshcore_relay_test.py <client_port> <server_port>
    python scripts/hw_tests/meshcore_relay_test.py <client_port> <server_port> --tx-hex <real signed tx hex>
"""
import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from client.sender import TransactionSender
from server.receiver import TransactionReceiver
from transport.meshcore_serial import MeshCoreSerialTransport

DEFAULT_TX_HEX = "ab" * (3 * 120)  # forces >1 chunk at MESHCORE_MAX_CHUNK_SIZE
# Not real transaction bytes, so the server's structural sanity check
# (core/transaction_sanity.py, wired in server/receiver.py::_broadcast())
# rejects it before ever reaching the RPC-connection check - confirmed via
# real hardware. That's fine and deliberate: it's a fixed, local check
# that doesn't depend on whoever runs this script having (or not having)
# Bitcoin RPC configured, unlike "Bitcoin RPC not connected" would be.
EXPECTED_ERROR_FOR_DEFAULT_TX = "Invalid transaction structure"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_port", help="Client's MeshCore device serial port")
    parser.add_argument("server_port", help="Server's MeshCore device serial port")
    parser.add_argument(
        "--tx-hex", default=DEFAULT_TX_HEX,
        help="Raw tx hex to send (default: placeholder, forces multi-chunk)",
    )
    args = parser.parse_args()

    print(f"Connecting server transport ({args.server_port})...")
    server_transport = MeshCoreSerialTransport()
    server_transport.connect(args.server_port)
    print(f"Server node: {server_transport.local_node_id}")

    print(f"Connecting client transport ({args.client_port})...")
    client_transport = MeshCoreSerialTransport()
    client_transport.connect(args.client_port)
    print(f"Client node: {client_transport.local_node_id}")

    outcome = {}
    done = threading.Event()

    def on_broadcast(result):
        outcome["success"] = result.success
        outcome["error"] = result.error
        outcome["raw_tx"] = result.raw_tx
        outcome["txid"] = result.txid
        done.set()

    def on_error(session_id, sender_id, error):
        outcome["success"] = False
        outcome["error"] = error
        outcome["raw_tx"] = None
        outcome["txid"] = None
        done.set()

    receiver = TransactionReceiver(
        server_transport, rpc_client=None,
        on_broadcast=on_broadcast,
        on_error=on_error,
        on_chunk_received=lambda evt: print(
            f"  [server] chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}"
        ),
    )

    sender = TransactionSender(client_transport, timeout_seconds=30, max_retries=3)

    total_chunks = -(-len(args.tx_hex) // client_transport.max_chunk_size)
    print(f"\nSending {len(args.tx_hex)} hex chars (expect {total_chunks} chunks)...")
    result = sender.send_transaction(
        args.tx_hex, server_transport.local_node_id,
        on_progress=lambda n, total: print(f"  [client] ACK {n}/{total}"),
        on_chunk_sending=lambda n, total, attempt, wire: print(
            f"  [client] sending {n}/{total} (attempt {attempt})"
        ),
    )

    # send_transaction() blocks until the *final* ACK/NACK arrives, not
    # just the per-chunk ACKs - so result.success=False here doesn't mean
    # the relay failed, only that the final outcome was a NACK. With the
    # default placeholder hex that's expected (see EXPECTED_ERROR_FOR_DEFAULT_TX
    # above), so this is a mismatch check, not a bare success check. The
    # server's own callbacks (via `outcome`) are still the source of truth
    # for what the server actually reassembled and reported - checked
    # independently below, not inferred from the client's side alone.
    ok = True
    if not done.wait(timeout=5):
        print("\nFAIL: server never reached a broadcast outcome")
        ok = False
    else:
        if outcome.get("raw_tx") != args.tx_hex:
            print("\nFAIL: reassembled hex does not match what was sent")
            print(f"  sent:         {args.tx_hex[:60]}...")
            print(f"  reassembled:  {(outcome.get('raw_tx') or '')[:60]}...")
            ok = False

        if result.error != outcome.get("error"):
            print(
                f"\nFAIL: client-reported error {result.error!r} doesn't match "
                f"server-reported error {outcome.get('error')!r} - the NACK "
                f"reason wasn't relayed back to the client correctly"
            )
            ok = False

        if args.tx_hex == DEFAULT_TX_HEX:
            # Deterministic, environment-independent expectation for the
            # placeholder hex - see EXPECTED_ERROR_FOR_DEFAULT_TX.
            if outcome.get("success") or outcome.get("error") != EXPECTED_ERROR_FOR_DEFAULT_TX:
                print(
                    f"\nFAIL: expected the placeholder hex to be rejected with "
                    f"{EXPECTED_ERROR_FOR_DEFAULT_TX!r}, got success="
                    f"{outcome.get('success')}, error={outcome.get('error')!r}"
                )
                ok = False
        else:
            # A caller-supplied --tx-hex's outcome legitimately depends on
            # this machine's own Bitcoin RPC configuration (real broadcast
            # is a different concern - see scripts/regtest_demo/ and
            # scripts/testnet4_demo/) - report it, don't gate pass/fail on
            # a specific string here.
            print(f"\n--tx-hex outcome: success={outcome.get('success')}, "
                  f"error={outcome.get('error')}, txid={outcome.get('txid')}")

        if ok:
            print(
                "\nPASS: relay verified - chunked, sent, ACKed, and reassembled "
                "byte-for-byte correctly, with the NACK reason relayed back to "
                "the client accurately."
            )

    server_transport.disconnect()
    client_transport.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
