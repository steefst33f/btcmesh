from __future__ import annotations

import time
from typing import Optional, Any, Dict, TYPE_CHECKING

# No direct 'import meshtastic' or its components here at the module level.
# These will be imported inside functions that need them to allow the module
# to be imported by tests even if meshtastic is not installed.

from core.logger_setup import server_logger
from core.config_loader import get_meshtastic_serial_port, load_app_config
from core.reassembler import (
    TransactionReassembler,
    InvalidChunkFormatError,
    MismatchedTotalChunksError,
    ReassemblyError
)

if TYPE_CHECKING:
    import meshtastic.serial_interface

# Global instance of the TransactionReassembler
# TODO: Consider timeout configuration from .env file later if needed for reassembler
transaction_reassembler = TransactionReassembler()

# Placeholder for the main Meshtastic interface, to be set in main()
# This is needed if on_receive_text_message or other global scope functions
# need to call send_meshtastic_reply directly or access iface properties.
# For now, iface is passed to on_receive_text_message by pubsub.
# And send_meshtastic_reply is called from main loop for timeouts,
# or from on_receive for immediate NACKs.
meshtastic_interface_instance: (
    Optional["meshtastic.serial_interface.SerialInterface"]
) = None


TRX_CHUNK_BUFFER: Dict[str, Any] = {}  # This will be replaced by reassembler logic
# TODO: Remove TRX_CHUNK_BUFFER once reassembler is fully integrated and tested.

# Ensure .env is loaded at application startup
load_app_config()


def _format_node_id(node_id_val: Any) -> Optional[str]:
    """Helper to consistently format node IDs to !<hex_string> or return None."""
    if isinstance(node_id_val, int):
        return f"!{node_id_val:x}"
    elif isinstance(node_id_val, str):
        if node_id_val.startswith('!'):
            return node_id_val
        else:
            try:
                # Try to interpret as hex string if not starting with '!'
                int(node_id_val, 16)  # Validate if it can be hex
                return f"!{node_id_val}"
            except ValueError:
                # Not a valid hex string if it doesn't start with '!'
                # and isn't parseable as hex.
                # This case should ideally not happen if Meshtastic
                # provides consistent IDs.
                # Depending on strictness, could log a warning or return None.
                server_logger.warning(
                    f"Received non-standard string node ID format: {node_id_val}"
                )
                return None  # Or treat as opaque string if that's ever expected
    return None


def _extract_session_id_from_raw_chunk(message_text: str) -> Optional[str]:
    """Rudimentary attempt to extract tx_session_id for NACKs if full parsing fails."""
    try:
        if message_text.startswith(transaction_reassembler.CHUNK_PREFIX):
            parts = message_text[len(transaction_reassembler.CHUNK_PREFIX):].split(
                transaction_reassembler.CHUNK_PARTS_DELIMITER
            )
            if len(parts) > 0 and parts[0]:
                return parts[0]
    except Exception: # pylint: disable=broad-except
        pass # Best effort
    return None


def on_receive_text_message(packet: Dict[str, Any], iface: Any) -> None:
    """
    Callback function to handle received Meshtastic packets.
    Filters for direct text messages, identifies transaction chunks,
    and uses TransactionReassembler to process them.
    """
    # Ensure global meshtastic_interface_instance is available if needed for replies from here
    # However, 'iface' is passed directly by pubsub, so use that for replies triggered here.
    global meshtastic_interface_instance
    if meshtastic_interface_instance is None and iface is not None:
        # This is a bit of a workaround. Ideally, the context (iface)
        # should always be passed explicitly where needed.
        # Or on_receive_text_message becomes a method of a class holding the iface.
        pass # Rely on the passed `iface` argument for this call.

    try:
        decoded_packet = packet.get('decoded')
        if not decoded_packet:
            server_logger.debug(
                f"Received packet without 'decoded' content: "
                f"{packet.get('id', 'N/A')}"
            )
            return

        my_node_id_from_iface = None
        if hasattr(iface, 'myInfo') and \
           iface.myInfo and \
           hasattr(iface.myInfo, 'my_node_num'):
            my_node_id_from_iface = iface.myInfo.my_node_num

        my_node_id = _format_node_id(my_node_id_from_iface)

        # Check if the message is from self, using the raw integer ID for comparison
        # This check needs to be after my_node_id_from_iface is determined and
        # ideally after decoded_packet is confirmed to exist for text preview.
        sender_raw_id = packet.get('from')
        if sender_raw_id is not None and my_node_id_from_iface is not None and \
           sender_raw_id == my_node_id_from_iface:
            text_preview = "(No text field)" # Default if text is not present
            if decoded_packet and 'text' in decoded_packet:
                text_content = decoded_packet.get('text', '')
                text_preview = text_content[:30]
                if len(text_content) > 30:
                    text_preview += "..."
            
            # For self-messages, From and To are the same (our ID)
            server_logger.debug(
                f"Ignoring DM from self. From: {my_node_id}, To: {my_node_id}, "
                f"Text: '{text_preview}'"
            )
            return

        # Determine destination node ID from packet (prefer 'to',
        # fallback to 'toId')
        dest_val = packet.get('to')
        if dest_val is None:  # If 'to' (int) is not present, try 'toId' (str)
            dest_val = packet.get('toId')
        destination_node_id = _format_node_id(dest_val)

        if not my_node_id:
            server_logger.warning(
                "Could not determine or format my node ID from interface."
            )
            return

        # If destination_node_id is None, it could be a broadcast
        # (not handled here as DM) or malformed.
        # For strict DM processing, if destination_node_id is None, we ignore.
        # Story 1.2 specifies DMs, so if destination_node_id is None or
        # not matching our ID, it's not a DM to us.
        if destination_node_id != my_node_id:
            # This also handles destination_node_id being None implicitly
            if destination_node_id:  # Log only if there was a different destination
                from_node_display = (
                    _format_node_id(
                        packet.get('from') or packet.get('fromId')
                    ) or 'UnknownSender'
                )
                server_logger.debug(
                    f"Received message not for this node. To: "
                    f"{destination_node_id}, MyID: {my_node_id}, "
                    f"From: {from_node_display}"
                )
            # Else, it could be a broadcast or message with no destination,
            # not processed as DM to us.
            return

        # At this point, message is considered a direct message to us
        # (my_node_id == destination_node_id)
        actual_portnum_str = str(decoded_packet.get('portnum'))

        sender_raw_key_for_reassembler = packet.get('from')  # Prefer int ID
        if sender_raw_key_for_reassembler is None:
            sender_raw_key_for_reassembler = packet.get('fromId', 'UnknownSender')
        
        # This formatted ID is crucial for sending replies correctly
        sender_node_id_for_reply = _format_node_id(packet.get('from') or packet.get('fromId'))

        if not sender_node_id_for_reply:
            server_logger.warning(
                f"Could not determine a valid sender node ID for reply from packet: {packet}. Ignoring DM."
            )
            return

        if actual_portnum_str == 'TEXT_MESSAGE_APP':
            message_text = decoded_packet.get('text')
            if not message_text:
                server_logger.debug(
                    f"Direct text message with no text from {sender_node_id_for_reply}: {packet.get('id', 'N/A')}"
                )
                return

            server_logger.info(
                f"Direct text from {sender_node_id_for_reply}: '{message_text}'"
            )

            if message_text.startswith(transaction_reassembler.CHUNK_PREFIX):
                server_logger.info(
                    f"Potential BTC transaction chunk from {sender_node_id_for_reply}. Processing..."
                )
                try:
                    # --- Replacement of TRX_CHUNK_BUFFER logic starts ---
                    reassembled_hex = transaction_reassembler.add_chunk(
                        sender_raw_key_for_reassembler, # Use the key consistent with reassembler's design
                        message_text
                    )

                    if reassembled_hex:
                        server_logger.info(
                            f"[Sender: {sender_node_id_for_reply}] Successfully reassembled transaction: "
                            f"{reassembled_hex[:50]}... (len: {len(reassembled_hex)})"
                        )
                        # Placeholder: Further processing (decode, validate, broadcast)
                        # and sending BTC_ACK will happen in subsequent stories.
                        # For now, just log reassembly success.
                    # --- Replacement of TRX_CHUNK_BUFFER logic ends ---

                except (InvalidChunkFormatError, MismatchedTotalChunksError) as e:
                    error_type_str = type(e).__name__.replace("Error", "").replace("Invalid", "Invalid ")
                    
                    tx_session_id_for_nack = _extract_session_id_from_raw_chunk(message_text) or "UNKNOWN"
                    nack_message_detail = f"{error_type_str}: {str(e)}"
                    nack_message = f"BTC_NACK|{tx_session_id_for_nack}|ERROR|{nack_message_detail}"
                    
                    max_nack_len = 200 
                    if len(nack_message) > max_nack_len:
                        # Truncate the detail part if overall message is too long
                        available_len_for_detail = max_nack_len - len(f"BTC_NACK|{tx_session_id_for_nack}|ERROR|...e")
                        if available_len_for_detail > 0:
                            nack_message_detail = nack_message_detail[:available_len_for_detail] + "..."
                        else: # Fallback if even prefix is too long (unlikely)
                            nack_message_detail = "Error detail too long"
                        nack_message = f"BTC_NACK|{tx_session_id_for_nack}|ERROR|{nack_message_detail}"


                    server_logger.error(
                        f"[Sender: {sender_node_id_for_reply}, Session: {tx_session_id_for_nack}] "
                        f"Reassembly error: {e}. Sending NACK."
                    )
                    if iface: # Use the iface passed by pubsub for this immediate reply
                        send_meshtastic_reply(
                            iface, sender_node_id_for_reply, nack_message, tx_session_id_for_nack
                        )
                    else:
                        server_logger.error(
                            f"[Sender: {sender_node_id_for_reply}, Session: {tx_session_id_for_nack}] "
                            f"Cannot send NACK: Meshtastic interface not available in on_receive."
                        )
                except ReassemblyError as e: # Catch other specific reassembly errors if any
                    tx_session_id_for_nack = _extract_session_id_from_raw_chunk(message_text) or "UNKNOWN"
                    server_logger.error(
                        f"[Sender: {sender_node_id_for_reply}, Session: {tx_session_id_for_nack}] "
                        f"General reassembly error: {e}. Notifying sender may be needed."
                    )
                    # Decide if a generic NACK is useful here. Current stories might NACK on timeout instead.
                except Exception as e: # Catch-all for unexpected errors in add_chunk
                    tx_session_id_for_nack = _extract_session_id_from_raw_chunk(message_text) or "UNKNOWN"
                    server_logger.error(
                        f"[Sender: {sender_node_id_for_reply}, Session: {tx_session_id_for_nack}] "
                        f"Unexpected error processing chunk: {e}. Not NACKing automatically.",
                        exc_info=True
                    )
            else:
                server_logger.info(
                    f"Std direct text from {sender_node_id_for_reply} (not BTC_TX): '{message_text}'"
                )
        else:
            server_logger.debug(
                f"Received direct message, but not TEXT_MESSAGE_APP. "
                f"Portnum: {actual_portnum_str}, From: {sender_node_id_for_reply}, "
                f"ID: {packet.get('id', 'N/A')}"
            )

    except Exception as e:
        server_logger.error(
            f"Error processing received packet: {e}", exc_info=True
        )


def send_meshtastic_reply(
    iface: "meshtastic.serial_interface.SerialInterface",
    destination_id: str,  # Expected to be in '!<hex_id>' format
    message_text: str,
    tx_session_id: Optional[str] = None
) -> bool:
    """
    Sends a reply message to a specified node via Meshtastic.

    Args:
        iface: The initialized Meshtastic interface.
        destination_id: The target node ID (e.g., '!abcdef12').
                        Must be correctly formatted for Meshtastic.
        message_text: The text message to send.
        tx_session_id: Optional transaction session ID for logging context.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    log_prefix = f"[Session: {tx_session_id}] " if tx_session_id else ""
    try:
        if not iface:
            server_logger.error(
                f"{log_prefix}Cannot send reply: "
                f"Meshtastic interface is not available."
            )
            return False

        # Basic validation for destination_id format (must start with '!')
        # More robust validation could be added if necessary.
        if not destination_id or not destination_id.startswith('!'):
            msg = (
                f"{log_prefix}Cannot send reply: Invalid destination_id format "
                f"'{destination_id}'. Must start with '!'. "
                f"Message: '{message_text}'"
            )
            server_logger.error(msg)
            return False

        server_logger.info(
            f"{log_prefix}Attempting to send reply to {destination_id}: "
            f"'{message_text}'"
        )

        # The sendText method expects the destination node ID.
        # SerialInterface.getNode(nodeId) is used to find the node object.
        # If `destination_id` is `!node_hex_id`, getNode should resolve it.
        node = iface.getNode(destination_id)
        if not node:
            server_logger.error(
                f"{log_prefix}Node {destination_id} not found in mesh. "
                f"Cannot send reply: '{message_text}'"
            )
            return False

        # node.sendText() is the preferred way if we have the node object
        node.sendText(
            text=message_text,
            wantAck=False  # Set to True if we want link-layer ACK
        )
        # Typically, it queues for sending.

        server_logger.info(
            f"{log_prefix}Successfully sent reply to {destination_id}: "
            f"'{message_text}'"
        )
        return True
    except AttributeError as e:
        # This might happen if 'iface' or 'node' is None or
        # doesn't have sendText/getNode
        error_msg = (
            f"{log_prefix}AttributeError while sending reply to {destination_id}: "
            f"{e}. Ensure interface and node objects are valid. "
            f"Message: '{message_text}'"
        )
        server_logger.error(error_msg, exc_info=True)
        return False
    except Exception as e:
        # Catching generic MeshtasticError or other exceptions
        server_logger.error(
            f"{log_prefix}Failed to send reply to {destination_id}: {e}. "
            f"Message: '{message_text}'",
            exc_info=True
        )
        return False


def initialize_meshtastic_interface(
    port: Optional[str] = None
) -> Optional["meshtastic.serial_interface.SerialInterface"]:
    """
    Initializes and returns a Meshtastic SerialInterface.

    Imports meshtastic library components internally to handle cases where
    the library might not be installed in the test environment.

    Args:
        port: The specific serial port to connect to (e.g., /dev/ttyACM0).
              If None, the library will attempt to auto-detect.
              This argument is now primarily for testing overrides.
              The preferred method for users is via .env
              (MESHTASTIC_SERIAL_PORT).

    Returns:
        A Meshtastic SerialInterface object if successful, None otherwise.
    """
    # Use port from argument if provided (e.g., for testing),
    # otherwise get from config (which could be None for auto-detect).
    serial_port_to_use = port if port is not None \
        else get_meshtastic_serial_port()

    try:
        # Import Meshtastic components here, so the module can load without them
        import meshtastic.serial_interface
        from meshtastic import MeshtasticError, NoDeviceError

        log_port_info = f' on port {serial_port_to_use}' \
            if serial_port_to_use else ' (auto-detect)'
        server_logger.info(
            f"Attempting to initialize Meshtastic interface{log_port_info}..."
        )

        iface = (
            meshtastic.serial_interface.SerialInterface(
                devPath=serial_port_to_use
            )
            if serial_port_to_use
            else meshtastic.serial_interface.SerialInterface()
        )

        node_num_display = "Unknown Node Num"
        if hasattr(iface, 'myInfo') and \
           iface.myInfo and \
           hasattr(iface.myInfo, 'my_node_num'):
            # Use the same robust formatting for display
            formatted_node_id = _format_node_id(iface.myInfo.my_node_num)
            if formatted_node_id:
                node_num_display = formatted_node_id
            elif iface.myInfo.my_node_num is not None:  # If formatting failed
                # Fallback to raw string or int
                node_num_display = str(iface.myInfo.my_node_num)

        server_logger.info(
            f"Meshtastic interface initialized successfully. "
            f"Device: {iface.devicePath}, My Node Num: {node_num_display}"
        )
        return iface
    except ImportError:
        server_logger.error(
            "Meshtastic library not found. Please install it "
            "(e.g., pip install meshtastic)."
        )
        return None
    except NoDeviceError:
        server_logger.error(
            "No Meshtastic device found. Ensure it is connected and "
            "drivers are installed."
        )
        return None
    except MeshtasticError as e:
        server_logger.error(
            f"Meshtastic library error during initialization: {e}"
        )
        return None
    except Exception as e:
        server_logger.error(
            f"An unexpected error occurred during Meshtastic "
            f"initialization: {e}",
            exc_info=True
        )
        return None


def main() -> None:
    """
    Main function for the BTC Mesh Server.
    """
    global meshtastic_interface_instance
    server_logger.info("Starting BTC Mesh Relay Server...")

    # initialize_meshtastic_interface will now use the config loader by default
    meshtastic_iface = initialize_meshtastic_interface()

    if not meshtastic_iface:
        server_logger.error(
            "Failed to initialize Meshtastic interface. Exiting."
        )
        return

    try:
        # Import pubsub here as it's part of meshtastic
        from pubsub import pub  # PubSub library used by meshtastic

        # Register the callback for text messages
        # The callback signature for pub.subscribe("meshtastic.receive")
        # is typically `def callback(packet, interface)`
        # meshtastic-python's PubSub wrapper sends `interface`
        # as a keyword argument or second positional.
        pub.subscribe(on_receive_text_message, "meshtastic.receive")
        server_logger.info(
            "Registered Meshtastic message handler. Waiting for messages..."
        )

    except ImportError:
        server_logger.error(
            "PubSub library not found. Please install it (e.g., pip install "
            "pypubsub). This is a dependency for Meshtastic event handling."
        )
        if meshtastic_iface and hasattr(meshtastic_iface, 'close'):
            meshtastic_iface.close()
        return
    except Exception as e:
        server_logger.error(
            f"Failed to subscribe to Meshtastic messages: {e}", exc_info=True
        )
        if meshtastic_iface and hasattr(meshtastic_iface, 'close'):
            meshtastic_iface.close()
        return

    try:
        cleanup_interval = 10  # seconds, same as sleep
        last_cleanup_time = time.time()

        while True:
            current_time = time.time()
            if current_time - last_cleanup_time >= cleanup_interval:
                server_logger.debug("Running periodic cleanup of stale reassembly sessions...")
                timed_out_sessions = transaction_reassembler.cleanup_stale_sessions()
                for session_info in timed_out_sessions:
                    nack_message = (
                        f"BTC_NACK|{session_info['tx_session_id']}|ERROR|"
                        f"{session_info['error_message']}"
                    )
                    max_nack_len = 200 # Arbitrary safe length
                    if len(nack_message) > max_nack_len:
                        nack_message = nack_message[:max_nack_len-3] + "..."

                    server_logger.info(
                        f"[Sender: {session_info['sender_id_str']}, Session: {session_info['tx_session_id']}] "
                        f"Session timed out. Sending NACK: {nack_message}"
                    )
                    # Ensure global instance is used here if iface is not available otherwise
                    if meshtastic_interface_instance: 
                        send_meshtastic_reply(
                            meshtastic_interface_instance,
                            session_info['sender_id_str'],
                            nack_message,
                            session_info['tx_session_id']
                        )
                    else:
                        server_logger.error(
                            f"[Sender: {session_info['sender_id_str']}, Session: {session_info['tx_session_id']}] "
                            f"Cannot send timeout NACK: Meshtastic interface not available globally."
                        )
                last_cleanup_time = current_time
            
            # Sleep for a short duration to allow other operations and not busy-wait
            # The effective sleep will be cleanup_interval because of the check above.
            # If more frequent checks are needed for other things, sleep less.
            time.sleep(1.0) # Check for cleanup every second, actual cleanup every 10s.

    except KeyboardInterrupt:
        server_logger.info(
            "Server shutting down by user request (Ctrl+C)."
        )
    except Exception as e:
        server_logger.error(
            f"Unhandled exception in main loop: {e}", exc_info=True
        )
    finally:
        if meshtastic_iface and hasattr(meshtastic_iface, 'close'):
            server_logger.info("Closing Meshtastic interface...")
            meshtastic_iface.close()
        server_logger.info("BTC Mesh Relay Server stopped.")


if __name__ == "__main__":
    main() 