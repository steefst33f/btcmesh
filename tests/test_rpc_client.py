"""Tests for core/rpc_client.py's BitcoinRPCClient class.

Relocated from tests/test_btcmesh_server.py (Story 23.3) - these tests
exercise BitcoinRPCClient directly and have no dependency on
btcmesh_server.py, they were just historically written before the RPC
client was extracted into its own core/ module.
"""
import unittest
from unittest.mock import MagicMock


class TestBitcoinRpcConnectionStory42(unittest.TestCase):
    def setUp(self):
        self.valid_config = {
            "host": "127.0.0.1",
            "port": 8332,
            "user": "testuser",
            "password": "testpass",
        }

    def test_valid_config_node_reachable(self):
        """Given valid config and node reachable, When connecting, Then connection is established."""
        with unittest.mock.patch("core.rpc_client.requests.post") as mock_post:
            from core.rpc_client import BitcoinRPCClient

            # Configure the mock to return a successful response
            mock_response = MagicMock()
            mock_response.json.return_value = {"result": {"chain": "main"}, "error": None}
            mock_post.return_value = mock_response

            # Call the method
            rpc = BitcoinRPCClient(self.valid_config)

            # Assertions
            self.assertIsNotNone(rpc)
            mock_post.assert_called_once_with(
                rpc.uri,
                data='{"jsonrpc": "1.0", "id": "btcmesh", "method": "getblockchaininfo", "params": []}',
                headers={'Content-Type': 'application/json'},
                proxies={},
                timeout=30
            )


    def test_non_int_port_invalid_config_raises(self):
        """Given invalid config, When connecting, Then error is raised."""
        from core.rpc_client import BitcoinRPCClient

        bad_config = self.valid_config.copy()
        bad_config["port"] = "notanint"

        # Assertions
        with self.assertRaises(Exception):
            # Call the method
            BitcoinRPCClient(bad_config)

    def test_no_port_invalid_config_raises(self):
        """Given invalid config, When connecting, Then error is raised."""
        from core.rpc_client import BitcoinRPCClient

        bad_config = self.valid_config.copy()
        bad_config["port"] = None

        # Assertions
        with self.assertRaises(Exception):
            # Call the method
            BitcoinRPCClient(bad_config)

    def test_no_host_invalid_config_raises(self):
        """Given invalid config, When connecting, Then error is raised."""
        from core.rpc_client import BitcoinRPCClient

        bad_config = self.valid_config.copy()
        bad_config["host"] = None

        # Assertions
        with self.assertRaises(Exception):
            # Call the method
            BitcoinRPCClient(bad_config)

    def test_rpc_request_retries_on_connection_error_three_times_last_success(self):
        """Given valid config but node unreachable, When connecting, retries twice, succeeds on third try."""
        with unittest.mock.patch("core.rpc_client.requests.post") as mock_post:
            from core.rpc_client import BitcoinRPCClient

            # Mock the response to raise ConnectionError for the first two calls and success on last
            mock_post.side_effect = [
                ConnectionError("Connection error"),
                ConnectionError("Connection error"),
                MagicMock(json=MagicMock(return_value={"result": {"chain": "main"}, "error": None}))
            ]

            # Call the method
            rpc = BitcoinRPCClient(self.valid_config)

            # Assertions
            self.assertIsNotNone(rpc)
            self.assertEqual(mock_post.call_count, 3)  # Ensure post was called three times

    def test_rpc_request_retries_on_connection_error_second_success(self):
        """Given valid config but node unreachable on first try, retries and suceeds on second try."""
        with unittest.mock.patch("core.rpc_client.requests.post") as mock_post:
            from core.rpc_client import BitcoinRPCClient

            # Mock the response to raise ConnectionError for the first call and success on the second
            mock_post.side_effect = [
                ConnectionError("Connection error"),
                MagicMock(json=MagicMock(return_value={"result": {"chain": "main"}, "error": None}))
            ]

            # Call the method
            rpc = BitcoinRPCClient(self.valid_config)

            # Assertions
            self.assertIsNotNone(rpc)
            self.assertEqual(mock_post.call_count, 2)  # Ensure post was called two times

    def test_rpc_request_retries_on_connection_error_three_times_failure(self):
        """Given valid config but node unreachable, When connecting, retries 3 times, fails."""
        with unittest.mock.patch("core.rpc_client.requests.post") as mock_post:
            from core.rpc_client import BitcoinRPCClient

            # Mock the response to raise ConnectionError
            mock_post.side_effect = ConnectionError("Connection error")

            # Assert that the ConnectionError is raised after 3 attempts
            with self.assertRaises(ConnectionError) as context:
                # Call the method
                rpc = BitcoinRPCClient(self.valid_config)

            # Assertions
            self.assertTrue("Connection error" in str(context.exception))
            self.assertEqual(mock_post.call_count, 3)  # Ensure post was called three times


class TestBitcoinRpcBroadcastStory43(unittest.TestCase):
    def setUp(self):
        self.config = {
            'user': 'testuser',
            'password': 'testpass',
            'host': 'localhost',
            'port': 8332
        }
        self.valid_tx_hex = "0100000001abcdef..."
        self.txid = "deadbeefcafebabe1234567890abcdef1234567890abcdef"

    def test_successful_broadcast_returns_txid(self):
        """Given valid hex and RPC connection, When broadcast, Then TXID is returned."""
        from core.rpc_client import BitcoinRPCClient

        # Mock connect to prevent actual connection, and requests.post for the broadcast call
        with unittest.mock.patch.object(BitcoinRPCClient, 'connect'), \
            unittest.mock.patch('requests.post') as mock_post:
            # Create client (connect is mocked so no actual connection)
            client = BitcoinRPCClient(self.config)

            # Simulate a successful response from the RPC server
            mock_post.return_value.json.return_value = {
                "result": self.txid,
                "error": None
            }

            # Call the method
            txid, error = client.broadcast_transaction(self.valid_tx_hex)

            # Assertions
            self.assertEqual(txid, self.txid, "TXID returned should match expected TXID.")
            self.assertIsNone(error, "There should be no error for valid transaction.")

    def test_rpc_error_returns_error_message(self):
        """Given valid hex but RPC error, When broadcast, Then error message is returned."""
        from core.rpc_client import BitcoinRPCClient

        with unittest.mock.patch.object(BitcoinRPCClient, 'connect'), \
            unittest.mock.patch('requests.post') as mock_post:
            client = BitcoinRPCClient(self.config)

            # Simulate an error response from the RPC server
            mock_post.return_value.json.return_value = {
                "result": None,
                "error": {"code": -26, "message": "txn-mempool-conflict"}
            }

            # Call the method
            txid, error = client.broadcast_transaction(self.valid_tx_hex)

            # Assertions
            self.assertIsNone(txid)
            self.assertIn("txn-mempool-conflict", error)

    def test_no_rpc_connection_returns_error(self):
        """Given connection failure during broadcast, Then txid=None and error message is returned."""
        from core.rpc_client import BitcoinRPCClient
        import requests

        with unittest.mock.patch.object(BitcoinRPCClient, 'connect'), \
            unittest.mock.patch('requests.post') as mock_post:
            client = BitcoinRPCClient(self.config)

            # Simulate connection failure when trying to broadcast
            mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

            txid, error = client.broadcast_transaction(self.valid_tx_hex)

            self.assertIsNone(txid)
            self.assertIsNotNone(error)
            self.assertIn("Connection refused", error)


if __name__ == "__main__":
    unittest.main()
