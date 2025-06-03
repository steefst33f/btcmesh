# Reference Materials for Bitcoin-LoRa Project

This document provides quick references for developing the Bitcoin transaction relay over LoRa Meshtastic.

## 1. Meshtastic Python (`autoresponder.py` based)

Key aspects for interacting with Meshtastic devices using the Python library, derived from `autoresponder.py` and project requirements:

*   **Initialization**:
    ```python
    import meshtastic.serial_interface
    interface = meshtastic.serial_interface.SerialInterface() # Or other interface types
    ```

*   **Receiving Messages**:
    *   Uses the `pubsub` library for event-driven message handling.
    *   Subscribe to `'meshtastic.receive'` to get incoming packets.
    ```python
    from pubsub import pub

    def onReceive(packet, interface): # packet is a dict, interface is the Meshtastic interface instance
        try:
            if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
                # For Direct Messages (DM), check 'to' or 'dest' field and if it matches node's ID.
                # The `packet` dictionary contains crucial info:
                # packet['from'] -> Sender's node ID (important for replying)
                # packet['to'] -> Destination node ID
                # packet['decoded']['payload'] -> The actual message bytes
                
                sender_id = packet['from']
                payload_bytes = packet['decoded']['payload']
                message_string = payload_bytes.decode('utf-8')
                print(f"Received DM from {sender_id}: {message_string}")
                
                # Process message_string as potential raw transaction hex
                # ...
                
                # Example: send_reply(interface, sender_id, "ACK: " + message_string)

        except KeyError as e:
            print(f"Error processing packet: {e}, Packet: {packet}")
        except Exception as e:
            print(f"An unexpected error in onReceive: {e}")


    pub.subscribe(onReceive, 'meshtastic.receive')
    ```

*   **Sending Direct Messages (Reply)**:
    *   To reply directly to the sender, use `interface.sendText()` with the `destinationId` parameter.
    ```python
    def send_reply(meshtastic_interface, destination_id, message_text):
        print(f"Sending reply to {destination_id}: {message_text}")
        meshtastic_interface.sendText(
            text=message_text,
            destinationId=destination_id,
            # channelIndex=0, # Or specific channel if needed
            # wantAck=True # Optional: request an acknowledgement
        )
    ```
    *   The `packet['from']` field from the received message should be used as `destinationId` for the reply.

*   **Main Loop**:
    *   Keep the script running to listen for messages.
    ```python
    import time
    while True:
        time.sleep(1) # Keep alive, pubsub handles events in background threads
    ```

*   **Important Packet Fields for DMs**:
    *   `packet['decoded']['portnum']`: Should be `'TEXT_MESSAGE_APP'` (enum `PortNum.TEXT_MESSAGE_APP`) for text.
    *   `packet['from']`: Node ID of the sender. Essential for sending a reply.
    *   `packet['to']`: Node ID of the recipient. Should match the local node's ID for DMs.
    *   `packet['decoded']['payload']`: The raw byte payload of the message. Decode using `.decode('utf-8')` for text.


## 2. Bitcoin Raw Transaction Structure

A raw Bitcoin transaction is a hexadecimal string. Parsing it involves reading specific byte sequences. Bitcoin data types are often little-endian.

**Key Components of a Raw Transaction:**

1.  **Version** (4 bytes, little-endian integer)
    *   Example: `01000000` (Version 1)
    *   Indicates transaction format rules.

2.  **Marker & Flag** (Optional, SegWit)
    *   If present, `0001` indicates a SegWit transaction. The version field above would be followed by `00` (marker) and `01` (flag). Non-SegWit transactions omit these two bytes. For simplicity, initial parsing might focus on non-SegWit.

3.  **Input Count** (Variable-length integer - VarInt)
    *   Specifies the number of transaction inputs.

4.  **Transaction Inputs** (Repeated `Input Count` times)
    *   Each input consists of:
        *   **Previous Transaction Hash (TXID)** (32 bytes, internal byte order is reversed from typical display hash)
            *   The ID of the transaction whose output is being spent.
        *   **Previous Output Index** (4 bytes, little-endian integer)
            *   The `n` value of the specific UTXO in the previous transaction.
        *   **ScriptSig Size** (VarInt)
            *   Length of the `ScriptSig` (unlocking script).
        *   **ScriptSig** (Sequence of bytes, `ScriptSig Size` long)
            *   Script that satisfies the conditions of the UTXO being spent (e.g., contains signature and public key).
        *   **Sequence Number** (4 bytes, little-endian integer)
            *   Often `ffffffff`. Can be used for nLockTime or RBF.

5.  **Output Count** (VarInt)
    *   Specifies the number of transaction outputs.

6.  **Transaction Outputs** (Repeated `Output Count` times)
    *   Each output consists of:
        *   **Value** (8 bytes, little-endian integer)
            *   Amount in Satoshis.
        *   **ScriptPubKey Size** (VarInt)
            *   Length of the `ScriptPubKey` (locking script).
        *   **ScriptPubKey** (Sequence of bytes, `ScriptPubKey Size` long)
            *   Script that defines the conditions for spending this output.

7.  **Witness Data** (Optional, SegWit)
    *   If it's a SegWit transaction (marker & flag were present), witness data for each input follows all outputs. Each input's witness consists of a VarInt for the number of witness items, followed by each item (VarInt for length, then the item itself).

8.  **Locktime** (4 bytes, little-endian integer)
    *   If `00000000`, the transaction is valid immediately.
    *   Otherwise, specifies the block height or UNIX timestamp before which the transaction is not valid.

**Variable-length Integer (VarInt) Encoding:**

A compact way to represent integers. Read the first byte (`fb`):
*   If `fb < 0xFD` (253): `fb` is the value (1 byte).
*   If `fb == 0xFD`: The next 2 bytes are the value (little-endian unsigned short).
*   If `fb == 0xFE`: The next 4 bytes are the value (little-endian unsigned int).
*   If `fb == 0xFF`: The next 8 bytes are the value (little-endian unsigned long long).

**Example Parsing Flow (Conceptual for a non-SegWit transaction):**

```
raw_hex_tx = "0100000001abcdef...(64 hex chars)...000000006b48...(ScriptSig)...ffffffff01fedcba...(8 bytes value)...1976a914...(ScriptPubKey)...88ac00000000"
pointer = 0

# Version (4 bytes * 2 hex chars/byte = 8 chars)
version_hex = raw_hex_tx[pointer : pointer+8]
pointer += 8

# Input Count (VarInt - assume 1 byte for simplicity here, e.g., '01')
input_count_hex = raw_hex_tx[pointer : pointer+2]
pointer += 2
# ... parse input_count_hex to integer ...

# For each input:
#   Prev TXID (32 bytes * 2 = 64 chars)
#   Prev Output Index (4 bytes * 2 = 8 chars)
#   ScriptSig Size (VarInt)
#   ScriptSig (variable)
#   Sequence (4 bytes * 2 = 8 chars)

# Output Count (VarInt)

# For each output:
#   Value (8 bytes * 2 = 16 chars)
#   ScriptPubKey Size (VarInt)
#   ScriptPubKey (variable)

# Locktime (4 bytes * 2 = 8 chars)
```

**Considerations for Python Implementation:**

*   Use the `bytes.fromhex()` method to convert the hex string to bytes.
*   Use slicing to extract parts of the byte array.
*   Use `int.from_bytes(byte_slice, 'little')` to convert byte slices to integers.
*   Remember to handle VarInts correctly by checking the first byte.

This reference should help in building the functions for decoding (`Story 2.2`) and basic validation (`Story 3.1`).
For detailed step-by-step, refer to the StackExchange link or Bitcoin developer guides.
The URL from user: https://bitcoin.stackexchange.com/questions/121373/how-to-parse-a-raw-transaction-field-by-field 

## 3. Bitcoin RPC Client Usage (Python)

For interacting with a Bitcoin Core node's RPC interface. The `python-bitcoinrpc` library is a common choice.

*   **Installation**:
    ```bash
    pip install python-bitcoinrpc
    ```

*   **Connecting and Basic Usage**:
    ```python
    from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException

    # These should be loaded from a config file or environment variables
    rpc_user = "your_rpc_user"
    rpc_password = "your_rpc_password"
    rpc_host = "127.0.0.1"  # Or the IP of your Bitcoin node
    rpc_port = 8332      # Default for mainnet, 18332 for testnet, 18443 for regtest

    try:
        rpc_connection = AuthServiceProxy(f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}")
        
        # Example: Get blockchain info
        # blockchain_info = rpc_connection.getblockchaininfo()
        # print(f"Current block height: {blockchain_info['blocks']}")

    except JSONRPCException as e:
        print(f"RPC Error: {e.error['message']}")
    except ConnectionRefusedError:
        print(f"Connection refused. Is Bitcoin Core running and RPC configured correctly?")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    ```

*   **Sending a Raw Transaction (Story 4.3)**:
    ```python
    def broadcast_transaction(rpc_conn, raw_tx_hex):
        try:
            txid = rpc_conn.sendrawtransaction(raw_tx_hex)
            print(f"Transaction broadcasted successfully! TXID: {txid}")
            return txid, None # txid, error
        except JSONRPCException as e:
            # Specific errors from Bitcoin Core are in e.error
            # e.g., {'code': -26, 'message': 'txn-mempool-conflict'}
            # e.g., {'code': -25, 'message': 'bad-txns-inputs-missingorspent'}
            error_message = e.error.get('message', 'Unknown RPC error')
            error_code = e.error.get('code', 'N/A')
            print(f"RPC Error broadcasting transaction: {error_message} (Code: {error_code})")
            return None, error_message
        except Exception as e:
            print(f"An unexpected error broadcasting transaction: {e}")
            return None, str(e)

    # Assuming rpc_connection is established as shown above
    # raw_transaction_hex = "your_valid_raw_hex_transaction_string"
    # tx_id, error = broadcast_transaction(rpc_connection, raw_transaction_hex)
    # if tx_id:
    #     # Send success message back via LoRa
    # else:
    #     # Send error message back via LoRa
    ```

## 4. Basic Python Logging (Story 5.1)

Using Python's built-in `logging` module.

*   **Setup**:
    ```python
    import logging
    import os

    # Create logs directory if it doesn't exist
    LOGS_DIR = "logs"
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    
    LOG_FILE = os.path.join(LOGS_DIR, "bitcoin_lora_relay.log")

    logging.basicConfig(
        level=logging.INFO, # Set default logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE), # Log to a file
            logging.StreamHandler()        # Log to console
        ]
    )

    # Example usage:
    # logging.debug("This is a debug message.")
    # logging.info("Informational message.")
    # logging.warning("A warning occurred.")
    # logging.error("An error occurred.")
    # logging.critical("A critical error occurred.")
    ```
    Place this setup code at the beginning of your main script.

## 5. Configuration File Handling (Story 4.1, 5.2)

Example using INI files with `configparser`.

*   **Example `config.ini` file**:
    ```ini
    [Meshtastic]
    # serial_port = /dev/ttyACM0 ; Example for Linux
    # serial_port = COM3        ; Example for Windows

    [BitcoinRPC]
    host = 127.0.0.1
    port = 8332
    user = your_rpc_user
    password = your_rpc_password
    # For testnet, use port 18332
    # For regtest, use port 18443

    [Logging]
    log_level = INFO
    log_file = logs/bitcoin_lora_relay.log
    ```

*   **Reading `config.ini` in Python**:
    ```python
    import configparser

    config = configparser.ConfigParser()
    config_file_path = 'config.ini'

    def load_config():
        if not config.read(config_file_path):
            logging.warning(f"Warning: Configuration file '{config_file_path}' not found. Using defaults or expecting environment variables.")
            # You might want to create a default config here or raise an error if critical sections are missing
            return None # Or an empty config object, or defaults
        return config

    # Example usage:
    # app_config = load_config()
    # if app_config:
    #     rpc_host = app_config.get('BitcoinRPC', 'host', fallback='127.0.0.1')
    #     rpc_port = app_config.getint('BitcoinRPC', 'port', fallback=8332) # Use getint for integers
    #     # ... and so on for other parameters.
    #     # meshtastic_port = app_config.get('Meshtastic', 'serial_port', fallback=None)
    # else:
    #     # Handle missing config scenario
    #     logging.error("Failed to load configuration.")
    ```
    You would call `load_config()` early in your application.
    The `fallback` parameter in `get`, `getint`, `getboolean` etc. is useful for providing default values if a key is not found.

## 6. Chunked Transaction Sending Protocol (`btcmesh-cli.py` & Relay Server)

This section outlines the protocol for sending large raw Bitcoin transaction hex strings by chunking them into multiple Meshtastic text messages. This involves a sender client (`btcmesh-cli.py`) and the relay device (running `btcmesh-server.py`).

### Raw transaction example
02000000000108bf2c7da5efaf2708170ffbafde7b2b0ca68234474ea71d443aee6aebfbf998030000000000fdffffffd6fcdbf37f974be27e8b0d66638355e5f53bfaf7b930fae035d23b313c4751042900000000fdffffffcccc5ca913b8eb426fd7c6bb578eab0f26583d40c51ce52cb12a428c1e75f7320100000000fdffffff981b8b54ad2a8bd8b59d063e9473aead87412b699cb969298cf29b8787fe10600000000000fdffffff5d154c445b35a92aaf179c078cdab6310e69455cde650f128cbe85d92bab51600100000000fdffffff7d23c74a412ef33d5dd856d01933dd6a5453aee3539b12349febbf6c1ba157980100000000fdffffffc5c95ce2eac84fbd3db87bbbdb4cc0855088e891cc57b1f9e0684943a399aabf0000000000fdffffffb7ef5d8a55141068da0d7b5a712ad9bbe44c3b8b412d0df5b9bcad366d71c8f90500000000fdffffff01697c63030000000016001482ea8436a6318c989767a51ce33886d65faf59a10247304402203ec9cfb2b60a7b1df545493d1794fec0b8b6d8589f562f61c9aec6852775b54102205dfb34dcc9cc31110fdf4e4544c76e9a664cf29e8f1f9905771db386882527190121030e92cc6f0829ea8b91469c8aa7ca0660d66020d3e8baaece478905e0c30c1f770247304402204a3a6a7a5d4ff285b1ba4a3457dae8566a1616738f94e9eddcce6a75dbb831ef0220285c586f6463dcf68ccef59484b2d12bccd7d68a68b7092068e6cbfd96f04d88012102f48b8ab9a082a1cf94dcd7052ddea7d260b40cf01e83aa3df00f2266721ef420024730440220527c3eb66a06d697a078b2b2bdf9be52f9fe036b1e3422a0a150e151ff0cd25b0220268688d8d9a3dd24b9f846b1b2f1b1f1ed84443f0023e26fa1ac5f2c1f0626ac012103acc2fbe36c425eb49389e5896232ef90beda75531845cd726dfed5f60a1fedd10247304402202eee600a307d10fc4777e8143d3db8994a6e742d56d4e3ce67a21a1e5e509178022022ee1b1fee5d7ec8112a56b1c0ab2eef1be00907d384bbf10a7a9d2d27564fb5012103bd6876311fbf657af0c1c85e907c3adf8d5086d1b3cf2cd4805b40873d2cf3cd02473044022042dbc6204b70da1548456beef504d5e8d61349dd36913832060b35f61a360429022006940b48cff72f6476b8d4495126618766500f0868fb99ba40ab518934e9cc2b0121035aa46c0cf9b30a9edf20c65e5c39158aefbfdd2b7a049d146f42b7dc3163d1b50247304402207811bd5b127e8a693f20115f7f8b8b4dec6a4d5df32109b21e1252331778ac5202202ac727cc6c53287110fcd371845b5fcdba825cb9e60992cc01cffa8e2ee41701012102700455a96ddb63fdaf8fc3ad60d02b057f8e00ed512476d817150a22fd4495d90247304402202caf8f9c584fe1b5214dc2a67f42fe3b9fd7386b98807fc6bc273a2cf519769902201f9f7b407f92c7df84701e4259acb198ca19c5edbd860385caa6ca1316417c010121035bfcbb577fe3a3a805c78226c7e7c573053e85e6641243c8f435acde0e04668902473044022074d6273ed2c7f338c9db6a979f64f572a21e5a324eec4979dad77383b25263de02202635d0e21ddf4e46f5751d4d6117ad559f04b7a6d3d00f13dd784b82a902638e012103de05dcec6736d4e15dd88c5b34b638fee6cccfd8b260d53379a43be0b343617cd9540c00

### 6.1. Sender Client: `btcmesh-cli.py`

*   **Purpose**: To take a full raw Bitcoin transaction hex string and a destination Meshtastic node ID, split the hex string into manageable chunks, and send them sequentially to the destination.
*   **Command-Line Usage**:
    ```bash
    python btcmesh-cli.py -d <destination_node_id> -tx <raw_transaction_hex_string>
    ```
    *   `-d <destination_node_id>`: The Meshtastic node ID of the relay device (`btcmesh-server.py`).
    *   `-tx <raw_transaction_hex_string>`: The complete raw Bitcoin transaction as a hexadecimal string.

### 6.2. Chunk Message Format

Each chunk sent by `btcmesh-cli.py` (and received by the relay) will be a text message formatted as follows:

`BTC_TX|<tx_session_id>|<chunk_num>/<total_chunks>|<hex_payload_part>`

*   **`BTC_TX|`**: A literal prefix to identify the message as part of a Bitcoin transaction chunk sequence. (7 characters)
*   **`<tx_session_id>`**: A unique identifier for the entire transaction being sent. This allows the receiver to group chunks from the same transaction. `btcmesh-cli.py` should generate this (e.g., using a combination of timestamp and random characters to ensure uniqueness). Recommended length: 8-12 characters.
*   **`|`**: Pipe delimiter.
*   **`<chunk_num>`**: The sequence number of the current chunk (1-indexed).
*   **`/`**: Slash delimiter.
*   **`<total_chunks>`**: The total number of chunks that make up the complete transaction hex.
*   **`|`**: Pipe delimiter.
*   **`<hex_payload_part>`**: The actual segment of the hexadecimal transaction string for this particular chunk.

**Determining `<hex_payload_part>` Size:**
*   Meshtastic text messages have a practical payload limit of around 237 bytes.
*   The overhead for our protocol (prefix, session_id, chunk_num/total_chunks, delimiters) needs to be subtracted from this limit.
    *   Example Overhead: `BTC_TX|` (7) + `session_id` (e.g., 10) + `|` (1) + `chunk_num` (max 3 for 999 chunks) + `/` (1) + `total_chunks` (max 3) + `|` (1) = ~26 characters.
*   This leaves approximately `237 - 26 = 211` characters for the `<hex_payload_part>`.
*   It's advisable to use a slightly smaller conservative size, e.g., **200 hex characters**, to allow for variations and ensure reliable delivery.

**Example Chunking:**
Raw TX Hex (350 chars): `0100000001...[342 more hex chars]...00000000`
`tx_session_id`: `ts1678886400abc`
Payload part size: 200 hex chars

Chunk 1:
`BTC_TX|ts1678886400abc|1/2|0100000001...{first 200 hex chars of TX}`

Chunk 2:
`BTC_TX|ts1678886400abc|2/2|{remaining 150 hex chars of TX}`

### 6.3. Relay Device (`btcmesh-server.py`): Receiving and Reassembling Chunks

The relay device (`btcmesh-server.py`) must implement logic to:
1.  **Identify**: Recognize messages starting with `BTC_TX|` as transaction chunks.
2.  **Parse**: Extract `tx_session_id`, `chunk_num`, `total_chunks`, and `hex_payload_part` from the message.
3.  **Buffer**: Store incoming `hex_payload_part`s in a temporary structure (e.g., a dictionary keyed by `tx_session_id`, where each value is another dictionary or list keyed by `chunk_num`).
4.  **Handle Out-of-Order Arrival**: Chunks may not arrive in the order they were sent. The `chunk_num` is crucial for correct reassembly.
5.  **Check for Completion**: After receiving each chunk for a `tx_session_id`, check if all `total_chunks` have arrived.
6.  **Reconstruct**: Once all chunks for a `tx_session_id` are present, concatenate the `hex_payload_part`s in the correct order (sorted by `chunk_num`) to form the complete raw transaction hex string.
7.  **Timeout**: Implement a timeout mechanism (e.g., 5 minutes). If all chunks for a `tx_session_id` are not received within this period after the *first* chunk for that session arrived (or last chunk), the session should be considered stale, and its buffered chunks discarded to free resources. An error should be logged, and optionally a NACK sent to the sender.
8.  **Error Handling**: Handle cases like duplicate chunks (ignore), or inconsistent `total_chunks` values within the same session (treat as an error, discard session).

### 6.4. Acknowledgement Protocol (Relay `btcmesh-server.py` to Sender `btcmesh-cli.py`)

After the relay (`btcmesh-server.py`) attempts to process a fully reassembled transaction, it should send an acknowledgement back to the original sender (whose node ID is available from the incoming Meshtastic packets from `btcmesh-cli.py`).

*   **Success Acknowledgement (ACK)**:
    `BTC_ACK|<tx_session_id>|SUCCESS|TXID:<actual_bitcoin_txid>`
    Sent if the transaction is successfully reassembled, validated, and broadcast by the Bitcoin RPC node.

*   **Negative Acknowledgement (NACK)**:
    `BTC_NACK|<tx_session_id>|ERROR|<error_details_string>`
    Sent if any step fails (e.g., reassembly timeout, invalid reassembled hex, decode error, validation error, RPC broadcast error).
    `<error_details_string>` should be a concise message indicating the failure reason.

`btcmesh-cli.py` (if enhanced with Story 6.4 from `tasks.txt`) can listen for these messages to provide feedback to the user.
