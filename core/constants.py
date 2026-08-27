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

# MeshCore's own hard cap on a single companion-protocol text message:
# MAX_TEXT_LEN = 10*CIPHER_BLOCK_SIZE = 160 bytes (meshcore-dev/MeshCore's
# src/helpers/BaseChatMesh.h / src/MeshCore.h) - far smaller than the limit
# Meshtastic's DEFAULT_CHUNK_SIZE was tuned for (Issue 51).
MESHCORE_MAX_TEXT_LEN = 160  # bytes, external MeshCore firmware constant

# MESHCORE_MAX_CHUNK_SIZE (Issue 51): the wire format
# "BTC_TX|<5-char session>|<n>/<total>|<payload>" adds up to 19 bytes of
# overhead in the worst case (6 + 1 + 5 + 1 + 2 + 1 + 2 + 1, bounding
# chunk/total digit counts by MAX_TOTAL_CHUNKS=50's 2 digits), leaving
# MESHCORE_MAX_TEXT_LEN - 19 = 141 bytes theoretically safe. 120 leaves
# real margin below that edge - confirmed via real hardware that the
# default 170 fails outright (MeshCore's ERR_CODE_TABLE_FULL) while 100
# sends cleanly.
MESHCORE_MAX_CHUNK_SIZE = 120  # hex characters per chunk (60 bytes)

# --- Reassembly limits (Issue 26) ---
# Caps on server-side reassembly state, to bound worst-case memory growth
# from a misbehaving/malicious sender rather than growing unboundedly
# until a stale session times out.
#
# MAX_TOTAL_CHUNKS is derived from LoRa physics, not from a theoretical
# max Bitcoin transaction size - the latter would be a far weaker bound.
# A chunk message at Meshtastic's default LongFast preset (SF11/BW250,
# this project's own real-hardware setup - see Issue 16) takes ~2s of
# airtime. Even a sender that ignores the region's duty-cycle limit
# entirely and floods the channel back-to-back is still bound by that
# per-packet airtime (the server's radio can't demodulate faster than
# the channel allows): DEFAULT_REASSEMBLY_TIMEOUT (300s) / ~2s per chunk
# ~= 150 chunks is the physical ceiling for how many chunks could ever
# arrive in one session's lifetime. A real, duty-cycle-compliant sender
# on EU_868's 10% limit is far more constrained still (~15 chunks fit in
# 300s). 50 is set deliberately below even the adversarial 150-chunk
# ceiling for extra margin.
MAX_TOTAL_CHUNKS = 50
# A sender legitimately has at most a couple of sessions in flight at once
# (this protocol is stop-and-wait per session); this just bounds how many
# bogus/abandoned sessions one sender can pile up before their oldest ones
# time out.
MAX_CONCURRENT_SESSIONS_PER_SENDER = 5

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
