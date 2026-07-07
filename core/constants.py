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
ACK_OK = "OK"
ACK_REQUEST_CHUNK = "REQUEST_CHUNK"
ACK_ALL_RECEIVED = "ALL_CHUNKS_RECEIVED"

# --- Completion statuses ---
STATUS_SUCCESS = "SUCCESS"
STATUS_ERROR = "ERROR"
TXID_PREFIX = "TXID:"

# --- NACK size limit ---
MAX_NACK_LENGTH = 200  # max characters for NACK messages (to stay safe within the Meshtastic payload constraints)
