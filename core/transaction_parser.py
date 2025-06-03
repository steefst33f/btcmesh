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
        return int.from_bytes(data[offset+1:offset+3], 'little'), offset + 3
    elif fb == 0xFE:
        return int.from_bytes(data[offset+1:offset+5], 'little'), offset + 5
    elif fb == 0xFF:
        return int.from_bytes(data[offset+1:offset+9], 'little'), offset + 9
    else:
        raise ValueError('Invalid varint prefix')

def decode_raw_transaction_hex(hex_str: str) -> Dict[str, Any]:
    """
    Decodes a raw Bitcoin transaction hex string into a dict with basic fields.
    Only minimal parsing is done (version, input count, output count, locktime).
    Raises ValueError if parsing fails.
    TODO: Full input/output parsing for advanced validation.
    """
    try:
        data = bytes.fromhex(hex_str)
        offset = 0
        # Version (4 bytes, little-endian)
        version = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        # Input count (varint)
        input_count, offset = read_varint(data, offset)
        # For now, skip all inputs (not full parsing)
        # Output count (varint, after skipping inputs)
        # TODO: Actually parse inputs to get to outputs
        output_count = None  # Placeholder
        locktime = int.from_bytes(data[-4:], 'little')
        return {
            'version': version,
            'input_count': input_count,
            'output_count': output_count,
            'locktime': locktime,
            # TODO: Add 'inputs', 'outputs' fields after full parsing
        }
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
    if tx.get('input_count', 0) == 0:
        return False, "No inputs"
    if tx.get('output_count', 0) == 0:
        return False, "No outputs"
    return True, None 