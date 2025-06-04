"""
Bitcoin raw transaction parser for btcmesh relay.
"""

from typing import Dict, Any, Optional

# Helper for varint parsing


def read_varint(data: bytes, offset: int) -> (int, int):
    fb = data[offset]
    if fb < 0xFD:
        return fb, offset + 1
    elif fb == 0xFD:
        return int.from_bytes(data[offset + 1 : offset + 3], "little"), offset + 3
    elif fb == 0xFE:
        return int.from_bytes(data[offset + 1 : offset + 5], "little"), offset + 5
    elif fb == 0xFF:
        return int.from_bytes(data[offset + 1 : offset + 9], "little"), offset + 9
    return (
        0,
        0,
    )  # Should not be reached if prefixes are valid, but as a fallback for linter.
    # The original code would raise IndexError if fb is not one of the above.
    # For robustness, one might add a final else raise ValueError.


def decode_raw_transaction_hex(hex_str: str) -> Dict[str, Any]:
    """
    Decodes a raw Bitcoin transaction hex string into a dict with basic fields.
    Handles SegWit marker/flag and skips inputs to correctly find output count.
    Raises ValueError if parsing fails.
    """
    try:
        data = bytes.fromhex(hex_str)
        offset = 0
        is_segwit = False

        # Version (4 bytes, little-endian)
        version = int.from_bytes(data[offset : offset + 4], "little")
        offset += 4

        # Check for SegWit marker and flag
        # Marker is 0x00, Flag is 0x01
        if (
            offset + 2 <= len(data)
            and data[offset] == 0x00
            and data[offset + 1] == 0x01
        ):
            is_segwit = True
            offset += 2  # Skip marker and flag

        # Input count (varint)
        input_count, offset = read_varint(data, offset)

        # Skip all inputs
        for _ in range(input_count):
            # Previous Transaction Hash (32 bytes)
            offset += 32
            # Previous Output Index (4 bytes)
            offset += 4
            # ScriptSig Size (VarInt)
            scriptsig_len, offset = read_varint(data, offset)
            # ScriptSig (variable length)
            offset += scriptsig_len
            # Sequence Number (4 bytes)
            offset += 4

        # Output count (varint)
        output_count, offset = read_varint(data, offset)

        # For basic sanity check, we don't need to parse individual outputs or witness yet.
        # We just need to ensure we can read output_count.

        # Locktime (last 4 bytes of the transaction if non-segwit, or before witness if segwit)
        # For simplicity of this basic parser, and given we've skipped inputs and read output_count,
        # we will assume locktime is at the end for now. A full parser would handle witness data.
        # This might be inaccurate if there's witness data.
        # However, for the specific error "No inputs" or "No outputs", this simplified locktime parsing is not the cause.
        locktime = int.from_bytes(data[-4:], "little")

        return {
            "version": version,
            "is_segwit": is_segwit,
            "input_count": input_count,
            "output_count": output_count,
            "locktime": locktime,
        }
    except IndexError as e:  # Catch index errors from bad offsets
        raise ValueError(
            f"Failed to decode raw transaction due to parsing error (IndexError): {e}. TX length: {len(data)}, Offset: {offset}"
        )
    except Exception as e:
        raise ValueError(f"Failed to decode raw transaction: {e}")


def basic_sanity_check(tx: dict) -> (bool, Optional[str]):
    """
    Performs basic sanity checks on a decoded Bitcoin transaction dict.
    Returns (True, None) if valid, (False, error_message) if invalid.
    - Fails if input_count == 0 ("No inputs")
    - Fails if output_count == 0 ("No outputs")
    Story 3.1, see reference_materials.md for structure.
    """
    if tx.get("input_count", 0) == 0:
        return False, "No inputs"
    if tx.get("output_count", 0) == 0:
        return False, "No outputs"
    return True, None
