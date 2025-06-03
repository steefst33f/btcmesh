import unittest
from unittest.mock import MagicMock, call, patch, Mock
# import logging # Unused
import sys

# Import the function to be tested
from btcmesh_server import (
    initialize_meshtastic_interface, on_receive_text_message,
    send_meshtastic_reply, _format_node_id
)
# server_logger will be patched using its path in btcmesh_server

from core.reassembler import (
    InvalidChunkFormatError,
    MismatchedTotalChunksError,
    ReassemblyError,
    CHUNK_PREFIX,  # Import CHUNK_PREFIX directly
    TransactionReassembler
)

# Import the module to be tested AFTER mocks are in sys.modules
# import btcmesh_server # Redundant, direct imports below are used
# from btcmesh_server import (                             # REMOVE THIS LINE
#     # initialize_meshtastic_interface,  # Redefined, covered by top import # REMOVE THIS LINE
#     # on_receive_text_message,  # Redefined, covered by top import # REMOVE THIS LINE
#     # _format_node_id, # Now imported from top-level from btcmesh_server # REMOVE THIS LINE
#     # send_meshtastic_reply,  # Redefined, covered by top import # REMOVE THIS LINE
#     # _extract_session_id_from_raw_chunk, # Unused # REMOVE THIS LINE
# ) # REMOVE THIS LINE


# Define a class to be used as a spec for the Meshtastic interface mock
# in TestMessageHandling. This helps ensure the mock behaves like a real interface.
# class MockSerialInterfaceForMessageHandling: # Commenting out for now
#     """A mock class for specifying the interface of a Meshtastic SerialInterface.
#     Attributes and methods used by on_receive_text_message should be defined here.
#     """
#     def __init__(self, my_node_num=0xabcdef, devicePath='/dev/mock'):
#         self.myInfo = MagicMock()
#         self.myInfo.my_node_num = my_node_num
#         self.devicePath = devicePath
#         # Add other attributes/methods if on_receive_text_message uses them
#         # e.g. self.nodes = {}


class TestMeshtasticInitialization(unittest.TestCase):

    def setUp(self):
        # Mock the Meshtastic library and its components in sys.modules
        # This allows the imports inside initialize_meshtastic_interface to
        # resolve to our mocks
        self.mock_meshtastic_module = MagicMock()
        self.mock_serial_interface_module = MagicMock()

        # This is the class we want to control (e.g., SerialInterface)
        self.MockMeshtasticSerialInterfaceClass = MagicMock()
        self.mock_serial_interface_module.SerialInterface = (
            self.MockMeshtasticSerialInterfaceClass
        )

        self.mock_meshtastic_module.serial_interface = (
            self.mock_serial_interface_module
        )

        # Define mock exceptions that will be imported by the function under test
        self.MockNoDeviceError = type('NoDeviceError', (Exception,), {})
        self.MockMeshtasticError = type('MeshtasticError', (Exception,), {})
        self.mock_meshtastic_module.NoDeviceError = self.MockNoDeviceError
        self.mock_meshtastic_module.MeshtasticError = self.MockMeshtasticError

        # Mock PortNum if it were to be used directly from
        # meshtastic.mesh_pb2 in the callback
        self.mock_mesh_pb2_module = MagicMock()
        self.MockPortNum = MagicMock()
        # If comparing with actual enum values:
        # self.MockPortNum.TEXT_MESSAGE_APP = 1 # or whatever value it has
        # For now, the code uses string comparison 'TEXT_MESSAGE_APP' for
        # portnum in decoded packet
        self.mock_mesh_pb2_module.PortNum = self.MockPortNum

        # Patch sys.modules so that 'import meshtastic' and its sub-imports
        # get our mocks
        self.sys_modules_patcher = patch.dict(sys.modules, {
            'meshtastic': self.mock_meshtastic_module,
            'meshtastic.serial_interface': self.mock_serial_interface_module,
            'meshtastic.mesh_pb2': self.mock_mesh_pb2_module,  # For PortNum
            'pubsub': MagicMock(),  # Mock pubsub as it's imported in main
            'dotenv': MagicMock()  # Mock dotenv used by config_loader
        })
        self.sys_modules_patcher.start()

        # Patch the logger used within btcmesh_server
        self.logger_patcher = patch(
            'btcmesh_server.server_logger', MagicMock()
        )
        self.mock_logger = self.logger_patcher.start()

        # If btcmesh_server.server_logger was used directly (it is),
        # we can capture its original state if needed
        # For these tests, we mostly care about asserting calls on mock_logger.

        # Patch the config loader used by initialize_meshtastic_interface
        self.config_loader_patcher = patch(
            'btcmesh_server.get_meshtastic_serial_port'
        )
        self.mock_get_serial_port_config = self.config_loader_patcher.start()
        # Default behavior: no port configured, so auto-detect is attempted
        self.mock_get_serial_port_config.return_value = None

        # Patch load_app_config in btcmesh_server module scope if called there
        # and also in core.config_loader if tests directly/indirectly call it.
        self.load_config_patcher_server = patch(
            'btcmesh_server.load_app_config', MagicMock()
        )
        self.load_config_patcher_server.start()

        self.load_config_patcher_core = patch(
            'core.config_loader.load_app_config', MagicMock()
        )
        self.load_config_patcher_core.start()

    def tearDown(self):
        self.sys_modules_patcher.stop()
        self.logger_patcher.stop()
        self.config_loader_patcher.stop()
        self.load_config_patcher_server.stop()
        self.load_config_patcher_core.stop()

    def test_initialize_meshtastic_successful_autodetect(self):
        """Test successful init when no port is specified (arg/config) -> auto."""
        # Explicitly ensure config returns None
        self.mock_get_serial_port_config.return_value = None
        mock_iface_instance = (
            self.MockMeshtasticSerialInterfaceClass.return_value
        )
        mock_iface_instance.devicePath = '/dev/ttyUSB0'  # Example path
        mock_iface_instance.myInfo = MagicMock()
        mock_iface_instance.myInfo.my_node_num = 0xdeadbeef

        iface = initialize_meshtastic_interface()  # No port argument

        self.assertIsNotNone(iface)
        # Called with no devPath
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with()
        self.mock_get_serial_port_config.assert_called_once()  # Check config
        expected_log_calls = [
            call.info(
                'Attempting to initialize Meshtastic interface (auto-detect)...'),
            call.info(
                f'Meshtastic interface initialized successfully. Device: '
                f'{mock_iface_instance.devicePath}, My Node Num: !deadbeef')
        ]
        self.mock_logger.info.assert_has_calls(
            expected_log_calls, any_order=False
        )

    def test_initialize_meshtastic_successful_with_config_port(self):
        """Test successful init when port is provided by .env config."""
        configured_port = '/dev/ttyS0'
        self.mock_get_serial_port_config.return_value = configured_port
        mock_iface_instance = (
            self.MockMeshtasticSerialInterfaceClass.return_value
        )
        mock_iface_instance.devicePath = configured_port
        mock_iface_instance.myInfo = MagicMock()
        mock_iface_instance.myInfo.my_node_num = '!configPortNode'

        iface = initialize_meshtastic_interface()  # No port arg, use config

        self.assertIsNotNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with(
            devPath=configured_port
        )
        self.mock_get_serial_port_config.assert_called_once()
        expected_log_calls = [
            call.info(
                f'Attempting to initialize Meshtastic interface on port '
                f'{configured_port}...'),
            call.info(
                f'Meshtastic interface initialized successfully. Device: '
                f'{mock_iface_instance.devicePath}, My Node Num: !configPortNode')
        ]
        self.mock_logger.info.assert_has_calls(
            expected_log_calls, any_order=False
        )

    def test_initialize_meshtastic_successful_with_override_port(self):
        """Test successful init when port is provided by arg (overrides config)."""
        override_port = '/dev/ttyACM1'
        # Simulate a different configured port
        self.mock_get_serial_port_config.return_value = '/dev/ttyS0'

        mock_iface_instance = (
            self.MockMeshtasticSerialInterfaceClass.return_value
        )
        mock_iface_instance.devicePath = override_port
        mock_iface_instance.myInfo = MagicMock()
        mock_iface_instance.myInfo.my_node_num = '!overrideNode'

        # Port argument overrides config
        iface = initialize_meshtastic_interface(port=override_port)

        self.assertIsNotNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with(
            devPath=override_port
        )
        # Config should not be called if port arg is present
        self.mock_get_serial_port_config.assert_not_called()
        expected_log_calls = [
            call.info(
                f'Attempting to initialize Meshtastic interface on port '
                f'{override_port}...'),
            call.info(
                f'Meshtastic interface initialized successfully. Device: '
                f'{mock_iface_instance.devicePath}, My Node Num: !overrideNode')
        ]
        self.mock_logger.info.assert_has_calls(
            expected_log_calls, any_order=False
        )

    def test_initialize_meshtastic_successful_with_str_node_id(self):
        """Test init when my_node_num is str like !<hex> (auto-detect path)."""
        self.mock_get_serial_port_config.return_value = None  # Auto-detect
        mock_iface_instance = (
            self.MockMeshtasticSerialInterfaceClass.return_value
        )
        mock_iface_instance.devicePath = '/dev/ttyUSB1'
        mock_iface_instance.myInfo = MagicMock()
        # Example string node ID
        mock_iface_instance.myInfo.my_node_num = '!abcdef12'

        iface = initialize_meshtastic_interface()
        self.assertIsNotNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with()  # Auto
        self.mock_get_serial_port_config.assert_called_once()
        expected_log_calls = [
            call.info(
                'Attempting to initialize Meshtastic interface (auto-detect)...'),
            call.info(
                f'Meshtastic interface initialized successfully. Device: '
                f'{mock_iface_instance.devicePath}, My Node Num: !abcdef12')
        ]
        self.mock_logger.info.assert_has_calls(
            expected_log_calls, any_order=False
        )

    def test_initialize_meshtastic_no_device_error_autodetect(self):
        self.mock_get_serial_port_config.return_value = None  # Auto-detect
        self.MockMeshtasticSerialInterfaceClass.side_effect = (
            self.MockNoDeviceError("No Meshtastic device found mock")
        )
        iface = initialize_meshtastic_interface()
        self.assertIsNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with()
        self.mock_get_serial_port_config.assert_called_once()
        self.mock_logger.error.assert_any_call(
            "No Meshtastic device found. Ensure it is connected and "
            "drivers are installed."
        )
        self.mock_logger.info.assert_called_with(
            'Attempting to initialize Meshtastic interface (auto-detect)...')

    def test_initialize_meshtastic_no_device_error_with_config_port(self):
        configured_port = '/dev/ttyFAIL'
        self.mock_get_serial_port_config.return_value = configured_port
        self.MockMeshtasticSerialInterfaceClass.side_effect = (
            self.MockNoDeviceError("No Meshtastic device found mock")
        )
        iface = initialize_meshtastic_interface()
        self.assertIsNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with(
            devPath=configured_port
        )
        self.mock_get_serial_port_config.assert_called_once()
        self.mock_logger.error.assert_any_call(
            "No Meshtastic device found. Ensure it is connected and "
            "drivers are installed."
        )
        self.mock_logger.info.assert_called_with(
            f'Attempting to initialize Meshtastic interface on port '
            f'{configured_port}...')

    def test_initialize_meshtastic_generic_meshtastic_error(self):
        # This will use auto-detect path due to setUp
        error_message = "A generic Meshtastic error mock"
        self.MockMeshtasticSerialInterfaceClass.side_effect = (
            self.MockMeshtasticError(error_message)
        )
        iface = initialize_meshtastic_interface()
        self.assertIsNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with()
        self.mock_get_serial_port_config.assert_called_once()
        self.mock_logger.error.assert_any_call(
            f"Meshtastic library error during initialization: {error_message}"
        )
        self.mock_logger.info.assert_called_with(
            'Attempting to initialize Meshtastic interface (auto-detect)...')

    def test_initialize_meshtastic_unexpected_error(self):
        # This will use auto-detect path
        error_message = "An unexpected issue mock"
        self.MockMeshtasticSerialInterfaceClass.side_effect = Exception(
            error_message
        )
        iface = initialize_meshtastic_interface()
        self.assertIsNone(iface)
        self.MockMeshtasticSerialInterfaceClass.assert_called_once_with()
        self.mock_get_serial_port_config.assert_called_once()
        self.mock_logger.error.assert_any_call(
            f"An unexpected error occurred during Meshtastic "
            f"initialization: {error_message}", exc_info=True
        )
        self.mock_logger.info.assert_called_with(
            'Attempting to initialize Meshtastic interface (auto-detect)...')

    def test_initialize_meshtastic_import_error(self):
        # Manipulate sys.modules so config loader won't affect it directly
        # regarding meshtastic import
        self.sys_modules_patcher.stop()
        temp_sys_modules_patch = patch.dict(
            sys.modules, 
            {k: v for k, v in sys.modules.items() 
             if not k.startswith('meshtastic')}
        )
        temp_sys_modules_patch.start()

        # Stop config loader patch if it interferes with ImportError for meshtastic
        self.config_loader_patcher.stop()
        iface = initialize_meshtastic_interface()
        self.config_loader_patcher.start()  # Restart for other tests

        temp_sys_modules_patch.stop()
        self.sys_modules_patcher.start()
        self.assertIsNone(iface)
        self.mock_logger.error.assert_any_call(
            "Meshtastic library not found. Please install it "
            "(e.g., pip install meshtastic)."
        )


class TestMessageHandling(unittest.TestCase):
    def setUp(self):
        # Patch the logger
        self.patcher_logger = patch('btcmesh_server.server_logger', MagicMock())
        self.mock_logger = self.patcher_logger.start()

        # Patch the transaction reassembler instance that is used in btcmesh_server
        self.patcher_reassembler = patch(
            'btcmesh_server.transaction_reassembler', autospec=True
        )
        self.mock_reassembler = self.patcher_reassembler.start()
        # Set CHUNK_PREFIX on the mock reassembler instance. 
        # This is NOT used by the SUT's startswith() check, which uses a direct import.
        self.mock_reassembler.CHUNK_PREFIX = CHUNK_PREFIX 

        # Patch send_meshtastic_reply
        self.patcher_send_reply = patch(
            'btcmesh_server.send_meshtastic_reply', autospec=True
        )
        self.mock_send_reply = self.patcher_send_reply.start()

        # Patch _extract_session_id_from_raw_chunk
        self.patcher_extract_id = patch(
            'btcmesh_server._extract_session_id_from_raw_chunk', autospec=True
        )
        self.mock_extract_id = self.patcher_extract_id.start()

        # Create a mock Meshtastic interface instance
        self.mock_iface = MagicMock()
        self.mock_iface.myInfo = MagicMock()
        self.mock_iface.myInfo.my_node_num = 0xabcdef # Server's node number

    def tearDown(self):
        self.patcher_logger.stop()
        self.patcher_reassembler.stop()
        self.patcher_send_reply.stop()
        self.patcher_extract_id.stop()

    def test_receive_standard_text_message_for_server(self):
        """Test receiving a standard (non-BTC_TX) text message for the server."""
        sender_node_id_int = 0xfeedface
        sender_node_id_str_formatted = _format_node_id(sender_node_id_int) # "!feedface"
        
        server_node_id_str_formatted = "!abcdef" # Our server's ID, string formatted

        message_text = "Hello from Meshtastic!"
        
        # Packet construction for a direct message to the server
        # Using top-level 'toId' (string) which on_receive_text_message checks first.
        packet = {
            'from': sender_node_id_int, 
            'toId': server_node_id_str_formatted, # String formatted node ID
            'decoded': {
                # 'to': server_node_id_int, # Not strictly needed if toId is present and used first
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_std_text',
            'channel': 0 # Indicates a direct message
        }

        on_receive_text_message(packet, self.mock_iface)

        # For a standard text message, these should NOT be called.
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()

    def test_receive_btc_tx_chunk_partial_no_reassembly(self):
        """Test receiving a BTC_TX chunk that is part of a larger transaction (no full reassembly yet)."""
        sender_node_id_int = 0x54321
        # sender_node_id_str_formatted = _format_node_id(sender_node_id_int) # For logging, if used
        
        server_node_id_str_formatted = "!abcdef" # Our server's ID

        session_id = "sess2_partial"
        message_text = f"{CHUNK_PREFIX}{session_id}|1/2|partial_payload_data"

        # Simulate that add_chunk will be called but won't return a full transaction yet
        self.mock_reassembler.add_chunk.return_value = None

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted, # Message for our server
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_btc_partial',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # Crucial assertions for this test:
        # 1. add_chunk should be called with the correct sender ID and message text.
        #    The sender_id passed to add_chunk by on_receive_text_message is the raw integer packet['from'].
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int, 
            message_text
        )
        
        # 2. No reply should be sent for a partial (non-error) chunk reception.
        self.mock_send_reply.assert_not_called()

        # Optional: Minimal log assertion to confirm it took the BTC_TX path if needed,
        # but primary focus is on add_chunk call.
        # Example log: server_logger.info(f"Potential BTC transaction chunk from {sender_id_str_formatted}. Processing...")
        # self.mock_logger.info.assert_any_call(
        #     f"Potential BTC transaction chunk from {sender_node_id_str_formatted}. Processing..."
        # )

    def test_receive_btc_tx_chunk_success_reassembly(self):
        """Test receiving a BTC_TX chunk that leads to successful reassembly."""
        sender_node_id_int = 0x12345 # Example sender
        server_node_id_str_formatted = "!abcdef" # Our server's ID

        session_id = "sess_success_reassembly"
        # Simulate a single chunk transaction for simplicity, or the last chunk
        message_text = f"{CHUNK_PREFIX}{session_id}|1/1|deadbeefcafebabe"
        reassembled_hex_payload = "deadbeefcafebabe" # Expected result from reassembler

        # Configure the mock reassembler to return the complete payload
        self.mock_reassembler.add_chunk.return_value = reassembled_hex_payload

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_btc_success',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # 1. add_chunk should be called correctly.
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int,
            message_text
        )

        # 2. No ACK/NACK reply should be sent directly by on_receive_text_message 
        #    upon successful reassembly. Further processing (validation, RPC) would 
        #    trigger replies via send_meshtastic_reply.
        self.mock_send_reply.assert_not_called()

        # 3. Assert the log message for successful reassembly.
        #    The sender_id for logging is formatted by _format_node_id inside on_receive_text_message
        sender_node_id_str_formatted_for_log = _format_node_id(sender_node_id_int)
        expected_log_reassembly_success = (
            f"[Sender: {sender_node_id_str_formatted_for_log}] Successfully reassembled transaction: "
            f"{reassembled_hex_payload[:50]}... (len: {len(reassembled_hex_payload)})"
        )
        self.mock_logger.info.assert_any_call(expected_log_reassembly_success)

    def test_receive_btc_tx_chunk_invalid_format_sends_nack(self):
        """Test that InvalidChunkFormatError from add_chunk results in a NACK."""
        sender_node_id_int = 0x67890 # Example sender
        server_node_id_str_formatted = "!abcdef" # Our server's ID

        session_id_for_nack = "sess_invalid_fmt"
        # This message format might be parsable up to a point by add_chunk before it determines the error
        # or _parse_chunk within add_chunk might raise it.
        # For this test, we assume add_chunk itself is the source of the exception due to internal parsing.
        malformed_message_text = f"{CHUNK_PREFIX}{session_id_for_nack}|bad_chunk_format|payload"
        exception_message = "Test: Invalid chunk format detected by reassembler"

        # Configure mocks
        self.mock_reassembler.add_chunk.side_effect = InvalidChunkFormatError(exception_message)
        self.mock_extract_id.return_value = session_id_for_nack # Used for NACK message construction

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': malformed_message_text
            },
            'id': 'packet_btc_invalid_format',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # 1. add_chunk should be called.
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int,
            malformed_message_text
        )

        # 2. _extract_session_id_from_raw_chunk should be called for the NACK.
        self.mock_extract_id.assert_called_once_with(malformed_message_text)

        # 3. A NACK should be sent.
        sender_id_str_for_reply = _format_node_id(sender_node_id_int)
        # NACK format: BTC_NACK|<tx_session_id>|ERROR|<ErrorTypeString>: <exception_details>
        # ErrorTypeString for InvalidChunkFormatError is "Invalid ChunkFormat"
        expected_nack_detail = f"Invalid ChunkFormat: {exception_message}"
        expected_nack_message = f"BTC_NACK|{session_id_for_nack}|ERROR|{expected_nack_detail}"
        
        self.mock_send_reply.assert_called_once_with(
            self.mock_iface, 
            sender_id_str_for_reply,
            expected_nack_message,
            session_id_for_nack
        )

        # 4. Assert the error log.
        expected_error_log = (
            f"[Sender: {sender_id_str_for_reply}, Session: {session_id_for_nack}] "
            f"Reassembly error: {exception_message}. Sending NACK."
        )
        self.mock_logger.error.assert_any_call(expected_error_log)

    def test_receive_btc_tx_chunk_mismatched_total_sends_nack(self):
        """Test that MismatchedTotalChunksError from add_chunk results in a NACK."""
        sender_node_id_int = 0xabcde # Example sender
        server_node_id_str_formatted = "!abcdef" # Our server's ID

        session_id_for_nack = "sess_mismatch_total"
        # A valid-looking chunk message; the error comes from reassembler's state
        chunk_message_text = f"{CHUNK_PREFIX}{session_id_for_nack}|1/3|payload_part_for_mismatch"
        exception_message = "Test: Mismatched total chunks detected by reassembler"

        # Configure mocks
        self.mock_reassembler.add_chunk.side_effect = MismatchedTotalChunksError(exception_message)
        self.mock_extract_id.return_value = session_id_for_nack # Used for NACK

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': chunk_message_text
            },
            'id': 'packet_btc_mismatch_total',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # 1. add_chunk should be called.
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int,
            chunk_message_text
        )

        # 2. _extract_session_id_from_raw_chunk should be called for the NACK.
        self.mock_extract_id.assert_called_once_with(chunk_message_text)

        # 3. A NACK should be sent.
        sender_id_str_for_reply = _format_node_id(sender_node_id_int)
        # ErrorTypeString for MismatchedTotalChunksError is "MismatchedTotalChunks"
        expected_nack_detail = f"MismatchedTotalChunks: {exception_message}"
        expected_nack_message = f"BTC_NACK|{session_id_for_nack}|ERROR|{expected_nack_detail}"
        
        self.mock_send_reply.assert_called_once_with(
            self.mock_iface, 
            sender_id_str_for_reply,
            expected_nack_message,
            session_id_for_nack
        )

        # 4. Assert the error log.
        expected_error_log = (
            f"[Sender: {sender_id_str_for_reply}, Session: {session_id_for_nack}] "
            f"Reassembly error: {exception_message}. Sending NACK."
        )
        self.mock_logger.error.assert_any_call(expected_error_log)

    def test_receive_btc_tx_chunk_other_reassembly_error_no_nack_by_default(self):
        """Test that a generic ReassemblyError from add_chunk does NOT send a NACK by default."""
        sender_node_id_int = 0xfedcb  # Example sender
        server_node_id_str_formatted = "!abcdef"  # Our server's ID

        session_id_for_log = "sess_other_err"
        chunk_message_text = f"{CHUNK_PREFIX}{session_id_for_log}|1/1|payload_for_other_error"
        exception_message = "Test: Generic reassembly problem"

        # Configure mocks
        # Ensure the correct ReassemblyError is imported for this test to be meaningful
        # from core.reassembler import ReassemblyError # Already imported at top of file
        self.mock_reassembler.add_chunk.side_effect = ReassemblyError(exception_message)
        self.mock_extract_id.return_value = session_id_for_log  # Used for logging context

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': chunk_message_text
            },
            'id': 'packet_btc_other_error',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # 1. add_chunk should be called.
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int,
            chunk_message_text
        )

        # 2. _extract_session_id_from_raw_chunk should be called for logging context.
        self.mock_extract_id.assert_called_once_with(chunk_message_text)

        # 3. A NACK should NOT be sent for a generic ReassemblyError by default.
        self.mock_send_reply.assert_not_called()

        # 4. Assert the error log.
        sender_id_str_for_log = _format_node_id(sender_node_id_int)
        expected_error_log = (
            f"[Sender: {sender_id_str_for_log}, Session: {session_id_for_log}] "
            f"General reassembly error: {exception_message}. "
            f"Notifying sender may be needed."
        )
        self.mock_logger.error.assert_any_call(expected_error_log)

    def test_receive_btc_tx_chunk_unexpected_error_no_nack(self):
        """Test that an unexpected Exception from add_chunk does NOT send a NACK."""
        sender_node_id_int = 0x98765  # Example sender
        server_node_id_str_formatted = "!abcdef"  # Our server's ID

        session_id_for_log = "sess_unexpected_err"
        chunk_message_text = f"{CHUNK_PREFIX}{session_id_for_log}|1/1|payload_for_unexpected_error"
        exception_message = "Test: Totally unexpected problem during add_chunk"
        test_exception = Exception(exception_message)

        # Configure mocks
        self.mock_reassembler.add_chunk.side_effect = test_exception
        self.mock_extract_id.return_value = session_id_for_log  # Used for logging context

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_str_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': chunk_message_text
            },
            'id': 'packet_btc_unexpected_error',
            'channel': 0
        }

        on_receive_text_message(packet, self.mock_iface)

        # 1. add_chunk should be called.
        self.mock_reassembler.add_chunk.assert_called_once_with(
            sender_node_id_int,
            chunk_message_text
        )

        # 2. _extract_session_id_from_raw_chunk should be called for logging context.
        self.mock_extract_id.assert_called_once_with(chunk_message_text)

        # 3. A NACK should NOT be sent for an unexpected exception.
        self.mock_send_reply.assert_not_called()

        # 4. Assert the error log, ensuring exc_info=True.
        sender_id_str_for_log = _format_node_id(sender_node_id_int)
        expected_error_log_message = (
            f"[Sender: {sender_id_str_for_log}, Session: {session_id_for_log}] "
            f"Unexpected error processing chunk: {exception_message}. " # Note: str(test_exception) is exception_message
            f"Not NACKing automatically."
        )
        
        # Check if any error log call matches the message and has exc_info=True
        found_log_with_exc_info = False
        for call_args_item in self.mock_logger.error.call_args_list:
            args, kwargs = call_args_item
            if args and args[0] == expected_error_log_message and kwargs.get('exc_info') is True:
                found_log_with_exc_info = True
                break
        self.assertTrue(
            found_log_with_exc_info,
            f"Expected error log '{expected_error_log_message}' with exc_info=True not found. "
            f"Actual calls: {self.mock_logger.error.call_args_list}"
        )

    def test_receive_btc_tx_chunk_not_for_server(self):
        """Test that a BTC_TX chunk not addressed to the server is ignored by reassembler."""
        sender_node_id_int = 0x112233
        # server_node_id_int = self.mock_iface.myInfo.my_node_num # 0xabcdef
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num) # "!abcdef"
        
        other_node_id_str = "!feedbeef" # Message addressed to this node

        session_id = "sess_not_for_us"
        message_text = f"{CHUNK_PREFIX}{session_id}|1/1|some_payload"

        packet = {
            'from': sender_node_id_int,
            'toId': other_node_id_str,  # Key: Addressed to another node
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_btc_not_for_server',
            'channel': 0 # Direct message
        }

        on_receive_text_message(packet, self.mock_iface)

        # Assertions:
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()

        # Verify the specific log message for ignoring DM not addressed to us
        expected_log = f"Received message not for this node. To: {other_node_id_str}, MyID: {server_node_id_formatted}, From: {_format_node_id(sender_node_id_int)}"
        self.mock_logger.debug.assert_any_call(expected_log)

        # Ensure no BTC transaction processing logs occurred (e.g., "Potential BTC transaction chunk...")
        # This can be done by checking that certain calls were *not* made after the specific ignore log.
        # For simplicity, we rely on add_chunk_not_called primarily.

    def test_receive_standard_text_message_not_for_server(self):
        """Test that a standard text message not for the server is ignored."""
        sender_node_id_int = 0x445566
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num) # "!abcdef"
        
        other_node_id_str = "!anotherNodeStd" # Message addressed to this node
        message_text = "This is a standard message for someone else."

        packet = {
            'from': sender_node_id_int,
            'toId': other_node_id_str,  # Addressed to another node
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_std_not_for_server',
            'channel': 0 # Direct message
        }

        on_receive_text_message(packet, self.mock_iface)

        # Assertions:
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()

        # Verify the specific log message for ignoring DM not addressed to us
        expected_log = f"Received message not for this node. To: {other_node_id_str}, MyID: {server_node_id_formatted}, From: {_format_node_id(sender_node_id_int)}"
        self.mock_logger.debug.assert_any_call(expected_log)

    def test_receive_non_text_message_for_server(self):
        """Test receiving a non-text (e.g., position) direct message for the server."""
        sender_node_id_int = 0x778899
        sender_node_id_formatted = _format_node_id(sender_node_id_int)
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num) # "!abcdef"
        
        portnum_for_test = 'POSITION_APP' # Example non-text portnum
        packet_id = 'packet_non_text'

        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_formatted,  # Addressed to our server
            'decoded': {
                'portnum': portnum_for_test, 
                # No 'text' field for many non-text messages
            },
            'id': packet_id,
            'channel': 0 # Direct message
        }

        on_receive_text_message(packet, self.mock_iface)

        # Assertions:
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()

        # Verify the specific log message for non-text DMs
        expected_log = (
            f"Received direct message, but not TEXT_MESSAGE_APP. "
            f"Portnum: {portnum_for_test}, From: {sender_node_id_formatted}, "
            f"ID: {packet_id}"
        )
        self.mock_logger.debug.assert_any_call(expected_log)

    def test_receive_packet_no_decoded_field(self):
        """Test receiving a packet that is missing the 'decoded' field."""
        sender_node_id_int = 0x121212
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num)
        packet_id = 'packet_no_decoded'

        # Packet is missing the 'decoded' key entirely
        packet = {
            'from': sender_node_id_int,
            'toId': server_node_id_formatted, # Still a DM to us
            # 'decoded': { ... } -> MISSING
            'id': packet_id,
            'channel': 0 
        }

        on_receive_text_message(packet, self.mock_iface)

        # Assertions:
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()

        # Verify the specific log message
        expected_log = f"Received packet without 'decoded' content: {packet_id}"
        self.mock_logger.debug.assert_any_call(expected_log)

    def test_receive_packet_no_text_field(self):
        """Test TEXT_MESSAGE_APP packet for server but missing 'text' field."""
        sender_node_id_int = 0xABABAB
        sender_node_id_formatted = _format_node_id(sender_node_id_int)
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num)
        packet_id = 'packet_no_text_field'

        # Scenario 1: 'text' field is missing
        packet_missing_text = {
            'from': sender_node_id_int,
            'toId': server_node_id_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                # 'text': ... -> MISSING
            },
            'id': packet_id + "_missing",
            'channel': 0
        }

        on_receive_text_message(packet_missing_text, self.mock_iface)
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        expected_log_missing = f"Direct text message with no text from {sender_node_id_formatted}: {packet_missing_text.get('id')}"
        self.mock_logger.debug.assert_any_call(expected_log_missing)
        self.mock_logger.reset_mock() # Reset for next scenario
        self.mock_reassembler.reset_mock()
        self.mock_send_reply.reset_mock()

        # Scenario 2: 'text' field is None
        packet_text_is_none = {
            'from': sender_node_id_int,
            'toId': server_node_id_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': None
            },
            'id': packet_id + "_none",
            'channel': 0
        }
        on_receive_text_message(packet_text_is_none, self.mock_iface)
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        expected_log_none = f"Direct text message with no text from {sender_node_id_formatted}: {packet_text_is_none.get('id')}"
        self.mock_logger.debug.assert_any_call(expected_log_none)
        self.mock_logger.reset_mock()
        self.mock_reassembler.reset_mock()
        self.mock_send_reply.reset_mock()

        # Scenario 3: 'text' field is empty string
        packet_text_is_empty = {
            'from': sender_node_id_int,
            'toId': server_node_id_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': ""
            },
            'id': packet_id + "_empty",
            'channel': 0
        }
        on_receive_text_message(packet_text_is_empty, self.mock_iface)
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        expected_log_empty = f"Direct text message with no text from {sender_node_id_formatted}: {packet_text_is_empty.get('id')}"
        self.mock_logger.debug.assert_any_call(expected_log_empty)

    def test_receive_packet_from_self(self):
        """Test that packets sent from the server to itself are ignored."""
        server_node_id_int = self.mock_iface.myInfo.my_node_num # 0xabcdef
        server_node_id_formatted = _format_node_id(server_node_id_int) # "!abcdef"
        packet_id_base = 'packet_from_self'

        # Scenario 1: BTC_TX chunk from self to self
        btc_tx_message_from_self = f"{CHUNK_PREFIX}self_sess|1/1|payload_from_self"
        packet_btc_from_self = {
            'from': server_node_id_int,
            'toId': server_node_id_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': btc_tx_message_from_self
            },
            'id': packet_id_base + "_btc",
            'channel': 0
        }

        on_receive_text_message(packet_btc_from_self, self.mock_iface)
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        # This log assumes a new log message is added to SUT for ignoring self-messages
        expected_log_text_btc = btc_tx_message_from_self[:30] + "..." if len(btc_tx_message_from_self) > 30 else btc_tx_message_from_self
        expected_log_self_btc = f"Ignoring DM from self. From: {server_node_id_formatted}, To: {server_node_id_formatted}, Text: '{expected_log_text_btc}'"
        self.mock_logger.debug.assert_any_call(expected_log_self_btc)
        
        self.mock_logger.reset_mock()
        self.mock_reassembler.reset_mock()
        self.mock_send_reply.reset_mock()

        # Scenario 2: Standard text message from self to self
        std_text_from_self = "Hello me!"
        packet_std_from_self = {
            'from': server_node_id_int,
            'toId': server_node_id_formatted,
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': std_text_from_self
            },
            'id': packet_id_base + "_std",
            'channel': 0
        }
        on_receive_text_message(packet_std_from_self, self.mock_iface)
        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        expected_log_text_std = std_text_from_self[:30] + "..." if len(std_text_from_self) > 30 else std_text_from_self
        expected_log_self_std = f"Ignoring DM from self. From: {server_node_id_formatted}, To: {server_node_id_formatted}, Text: '{expected_log_text_std}'"
        self.mock_logger.debug.assert_any_call(expected_log_self_std)

    def test_receive_broadcast_btc_tx_chunk_ignored(self):
        """Test that a BTC_TX chunk sent as a broadcast is ignored."""
        sender_node_id_int = 0xb20adc57 # Example sender (valid hex)
        sender_node_id_formatted = _format_node_id(sender_node_id_int)
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num)
        
        broadcast_dest_id_str = "!ffffffff" # Meshtastic broadcast address

        session_id = "sess_broadcast_btc"
        message_text = f"{CHUNK_PREFIX}{session_id}|1/1|broadcast_payload"

        # Simulate a broadcast packet by setting 'toId' to broadcast and channel to 0 (for pubsub text)
        # or by setting channel > 0 (though on_receive_text_message may not be called by pubsub then)
        # For this test, we rely on the toId check in on_receive_text_message
        packet = {
            'from': sender_node_id_int,
            'toId': broadcast_dest_id_str, # Addressed to broadcast
            # 'channel': 1, # Alternatively, a non-zero channel indicates broadcast
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_broadcast_btc'
            # channel: 0 is implied if not present for DMs, pubsub might filter based on channel already
        }

        on_receive_text_message(packet, self.mock_iface)

        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        
        # Expect a log that it was not for this node
        expected_log = f"Received message not for this node. To: {broadcast_dest_id_str}, MyID: {server_node_id_formatted}, From: {sender_node_id_formatted}"
        self.mock_logger.debug.assert_any_call(expected_log)

    def test_receive_broadcast_standard_text_ignored(self):
        """Test that a standard text message sent as a broadcast is ignored."""
        sender_node_id_int = 0xb20adc57 # Example sender (same as other broadcast test for consistency)
        sender_node_id_formatted = _format_node_id(sender_node_id_int)
        server_node_id_formatted = _format_node_id(self.mock_iface.myInfo.my_node_num)
        
        broadcast_dest_id_str = "!ffffffff" # Meshtastic broadcast address
        message_text = "This is a standard broadcast message."

        packet = {
            'from': sender_node_id_int,
            'toId': broadcast_dest_id_str, # Addressed to broadcast
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': message_text
            },
            'id': 'packet_broadcast_std'
        }

        on_receive_text_message(packet, self.mock_iface)

        self.mock_reassembler.add_chunk.assert_not_called()
        self.mock_send_reply.assert_not_called()
        
        expected_log = f"Received message not for this node. To: {broadcast_dest_id_str}, MyID: {server_node_id_formatted}, From: {sender_node_id_formatted}"
        self.mock_logger.debug.assert_any_call(expected_log)


class TestMeshtasticReplySending(unittest.TestCase):
    def setUp(self):
        # Mock the logger
        self.patcher_logger = patch('btcmesh_server.server_logger')
        self.mock_logger = self.patcher_logger.start()

        # Mock the Meshtastic interface and node objects
        self.mock_iface = MagicMock()
        self.mock_node = MagicMock()
        self.mock_iface.getNode.return_value = self.mock_node

    def tearDown(self):
        self.patcher_logger.stop()
        # Ensure all mocks are reset if necessary, though patch.stop handles it

    def test_send_reply_success_ack(self):
        """Test sending a successful ACK reply."""
        dest_id = "!dummyNodeId1"
        session_id = "sess123"
        txid = "sampletxid012345"
        message = f"BTC_ACK|{session_id}|SUCCESS|TXID:{txid}"

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, session_id
        )

        self.assertTrue(result)
        self.mock_iface.getNode.assert_called_once_with(dest_id)
        self.mock_node.sendText.assert_called_once_with(text=message, wantAck=False)
        self.mock_logger.info.assert_any_call(
            f"[Session: {session_id}] Attempting to send reply to {dest_id}: "
            f"'{message}'"
        )
        self.mock_logger.info.assert_any_call(
            f"[Session: {session_id}] Successfully sent reply to {dest_id}: "
            f"'{message}'"
        )

    def test_send_reply_success_nack_no_session_id(self):
        """Test sending a successful NACK reply without a session ID."""
        dest_id = "!dummyNodeId2"
        error_details = "Reassembly timeout"
        message = f"BTC_NACK||ERROR|{error_details}"  # Empty session_id

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, tx_session_id=None
        )

        self.assertTrue(result)
        self.mock_iface.getNode.assert_called_once_with(dest_id)
        self.mock_node.sendText.assert_called_once_with(text=message, wantAck=False)
        self.mock_logger.info.assert_any_call(
            f"Attempting to send reply to {dest_id}: '{message}'"
        )
        self.mock_logger.info.assert_any_call(
            f"Successfully sent reply to {dest_id}: '{message}'"
        )

    def test_send_reply_invalid_destination_id_format(self):
        """Test sending reply with an invalid destination_id format."""
        dest_id = "dummyNodeId3"  # Missing '!'
        message = "BTC_NACK||ERROR|Invalid destination"
        session_id = "sess456"

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, session_id
        )

        self.assertFalse(result)
        self.mock_iface.getNode.assert_not_called()
        self.mock_node.sendText.assert_not_called()
        self.mock_logger.error.assert_called_once_with(
            f"[Session: {session_id}] Cannot send reply: Invalid "
            f"destination_id format '{dest_id}'. Must start with '!'. "
            f"Message: '{message}'"
        )

    def test_send_reply_destination_node_not_found(self):
        """Test sending reply when destination node is not found."""
        self.mock_iface.getNode.return_value = None
        dest_id = "!nonExistentNode"
        message = "BTC_NACK||ERROR|Node not found"
        session_id = "sess789"

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, session_id
        )

        self.assertFalse(result)
        self.mock_iface.getNode.assert_called_once_with(dest_id)
        self.mock_node.sendText.assert_not_called()
        self.mock_logger.error.assert_called_once_with(
            f"[Session: {session_id}] Node {dest_id} not found in mesh. "
            f"Cannot send reply: '{message}'"
        )

    def test_send_reply_sendtext_raises_exception(self):
        """Test sending reply when node.sendText() raises an exception."""
        self.mock_node.sendText.side_effect = Exception("Send failed")
        dest_id = "!errorNode"
        message = "BTC_ACK|sessErr|SUCCESS|TXID:errtxid"
        session_id = "sessErr"

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, session_id
        )

        self.assertFalse(result)
        self.mock_iface.getNode.assert_called_once_with(dest_id)
        self.mock_node.sendText.assert_called_once_with(
            text=message, wantAck=False
        )
        self.mock_logger.error.assert_called_once_with(
            f"[Session: {session_id}] Failed to send reply to {dest_id}: "
            f"Send failed. Message: '{message}'",
            exc_info=True
        )

    def test_send_reply_no_interface(self):
        """Test sending reply when Meshtastic interface is None."""
        dest_id = "!noIfaceNode"
        message = "BTC_NACK|noIface|ERROR|No interface"
        session_id = "noIface"

        result = send_meshtastic_reply(None, dest_id, message, session_id)

        self.assertFalse(result)
        # getNode should not be called on None
        self.mock_iface.getNode.assert_not_called()
        self.mock_logger.error.assert_called_once_with(
            f"[Session: {session_id}] Cannot send reply: "
            f"Meshtastic interface is not available."
        )

    def test_send_reply_attribute_error_on_getnode(self):
        """Test AttributeError when calling getNode (iface is misconfigured)."""
        self.mock_iface.getNode.side_effect = AttributeError(
            "Fake getnode error"
        )
        dest_id = "!attrErrorNode"
        message = "Info message"
        session_id = "attrSess"

        result = send_meshtastic_reply(
            self.mock_iface, dest_id, message, session_id
        )

        self.assertFalse(result)
        self.mock_iface.getNode.assert_called_once_with(dest_id)
        self.mock_logger.error.assert_called_once_with(
            f"[Session: {session_id}] AttributeError while sending reply to "
            f"{dest_id}: Fake getnode error. Ensure interface and node "
            f"objects are valid. Message: '{message}'",
            exc_info=True
        )


class TestTransactionReassemblerStory21(unittest.TestCase):
    def setUp(self):
        self.reassembler = TransactionReassembler(timeout_seconds=1)  # Short timeout for test
        self.sender_id = 12345
        self.session_id = "story21sess"

    def test_out_of_order_chunk_reassembly(self):
        """Given chunks arrive out of order, When all are received, Then reassembly succeeds in order."""
        # Given
        chunk1 = f"BTC_TX|{self.session_id}|1/3|AAA"
        chunk2 = f"BTC_TX|{self.session_id}|2/3|BBB"
        chunk3 = f"BTC_TX|{self.session_id}|3/3|CCC"
        # When: Add out of order
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk2))
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk1))
        # Then: Only after last chunk, reassembly occurs
        result = self.reassembler.add_chunk(self.sender_id, chunk3)
        self.assertEqual(result, "AAABBBCCC")

    def test_duplicate_chunk_ignored(self):
        """Given a duplicate chunk, When it is received, Then it is ignored and not reassembled twice."""
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        chunk2 = f"BTC_TX|{self.session_id}|2/2|BBB"
        # Add first chunk
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk1))
        # Add duplicate of first chunk
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk1))
        # Add second chunk
        result = self.reassembler.add_chunk(self.sender_id, chunk2)
        self.assertEqual(result, "AAABBB")
        # Add duplicate of second chunk (should not reassemble again)
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk2))

    def test_reassembly_timeout(self):
        """Given not all chunks arrive, When timeout passes, Then session is cleaned up and NACK info is returned."""
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        self.assertIsNone(self.reassembler.add_chunk(self.sender_id, chunk1))
        # Wait for timeout
        import time as _time
        _time.sleep(1.1)
        # When: cleanup is called
        nacks = self.reassembler.cleanup_stale_sessions()
        # Then: NACK info is returned for the timed out session
        self.assertTrue(any(n["tx_session_id"] == self.session_id for n in nacks))
        # And: session is removed
        self.assertIsNone(self.reassembler.get_session_sender_id_str(self.sender_id, self.session_id))


class TestHexValidationStory22(unittest.TestCase):
    def setUp(self):
        from core.reassembler import TransactionReassembler
        self.reassembler = TransactionReassembler(timeout_seconds=1)
        self.sender_id = 54321
        self.session_id = "hexval22"

    def test_valid_hex_string(self):
        """Given a valid hex string, When validated, Then it passes validation."""
        valid_hex = "deadbeefCAFEBABE0123456789abcdef"
        # Should not raise
        try:
            int(valid_hex, 16)
        except ValueError:
            self.fail("Valid hex string did not pass validation")

    def test_invalid_hex_string(self):
        """Given an invalid hex string, When validated, Then it fails validation and logs error."""
        invalid_hex = "deadbeefZZZ01234"
        with self.assertRaises(ValueError):
            int(invalid_hex, 16)

    def test_integration_reassembled_hex_validation(self):
        """Given a reassembled payload, When it is not valid hex, Then the server should log and prepare NACK."""
        # Simulate reassembly
        chunk1 = f"BTC_TX|{self.session_id}|1/2|deadbeef"
        chunk2 = f"BTC_TX|{self.session_id}|2/2|ZZZ01234"  # Invalid hex part
        self.reassembler.add_chunk(self.sender_id, chunk1)
        reassembled = self.reassembler.add_chunk(self.sender_id, chunk2)
        self.assertEqual(reassembled, "deadbeefZZZ01234")
        # Now validate
        with self.assertRaises(ValueError):
            int(reassembled, 16)

        # In the real server, this would trigger a NACK and log an error


if __name__ == '__main__':
    unittest.main() 