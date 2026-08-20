"""Protocol constants for the BTCMesh chunked transaction relay protocol.

Single source of truth for all protocol constants used across CLI, server,
and GUI. See project/protocol_spec.md for the full protocol specification.
"""

# --- Chunk format ---
# TODO: Use this delimiter constants everywhere in the codebase to avoid inconsistencies 
# and bugs related to hardcoded delimiters. This will also make it easier to change the 
# delimiter in the future if needed, as we would only need to update it in one place.
CHUNK_DELIMITER = "|"
CHUNK_INDEX_DELIMITER = "/"

# --- Sizing ---
DEFAULT_CHUNK_SIZE = 170  # hex characters per chunk (85 bytes)
SESSION_ID_LENGTH = 5  # hex characters in session ID

# --- Reassembly limits (Issue 26) ---
# Caps on server-side reassembly state, to bound worst-case memory growth
# from a misbehaving/malicious sender rather than growing unboundedly
# until a stale session times out.
# 5000 chunks * 170 hex chars = 850,000 hex chars = 425,000 bytes raw tx
# size - comfortably above Bitcoin Core's default standardness cap
# (MAX_STANDARD_TX_WEIGHT = 400,000 weight units, ~400,000 bytes for a
# non-segwit tx), so no legitimate transaction should ever hit this.
MAX_TOTAL_CHUNKS = 5000
# A sender legitimately has at most a couple of sessions in flight at once
# (this protocol is stop-and-wait per session); this just bounds how many
# bogus/abandoned sessions one sender can pile up before their oldest ones
# time out.
MAX_CONCURRENT_SESSIONS_PER_SENDER = 10

# --- Timeouts (seconds) ---
DEFAULT_ACK_TIMEOUT = 30  # client waits this long for server ACK
DEFAULT_RETRY_TIMEOUT = 10  # client waits before retrying after failure
DEFAULT_MAX_RETRIES = 3  # max retry attempts per chunk
DEFAULT_REASSEMBLY_TIMEOUT = 300  # server session timeout (5 minutes)

# --- Message type prefixes ---
MSG_BTC_TX = "BTC_TX"
MSG_CHUNK_ACK = "BTC_CHUNK_ACK"
MSG_ACK = "BTC_ACK"
MSG_NACK = "BTC_NACK"

# --- ACK sub-commands ---
ACK_REQUEST_CHUNK = "REQUEST_CHUNK"
ACK_ALL_RECEIVED = "ALL_CHUNKS_RECEIVED"

# --- Completion ---
TXID_PREFIX = "TXID:"

# --- NACK size limit ---
MAX_NACK_LENGTH = 200  # max characters for NACK messages (to stay safe within the Meshtastic payload constraints)
