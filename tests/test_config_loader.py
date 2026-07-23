"""Tests for core/config_loader.py's Bitcoin RPC config and reassembly
timeout loading functions.

Relocated from tests/test_btcmesh_server.py (Story 23.3) - these tests
exercise core.config_loader directly and have no dependency on
btcmesh_server.py, they were just historically written before this logic
was extracted into its own core/ module.
"""
import os
import tempfile
import unittest
import unittest.mock


class TestBitcoinRpcConfigStory41(unittest.TestCase):
    def setUp(self):
        self.env_keys = [
            "BITCOIN_RPC_HOST",
            "BITCOIN_RPC_PORT",
            "BITCOIN_RPC_USER",
            "BITCOIN_RPC_PASSWORD",
        ]
        self.default_env = {
            "BITCOIN_RPC_HOST": "127.0.0.1",
            "BITCOIN_RPC_PORT": "8332",
            "BITCOIN_RPC_USER": "testuser",
            "BITCOIN_RPC_PASSWORD": "testpass",
        }

    def test_all_fields_present_in_env(self):
        """Given all required RPC fields in .env, When loaded, Then config is correct."""
        from core.config_loader import load_bitcoin_rpc_config

        with unittest.mock.patch.dict("os.environ", self.default_env, clear=True):
            config = load_bitcoin_rpc_config()
            self.assertEqual(config["host"], "127.0.0.1")
            self.assertEqual(config["port"], 8332)
            self.assertEqual(config["user"], "testuser")
            self.assertEqual(config["password"], "testpass")

    def test_missing_required_field_raises(self):
        """Given missing required RPC fields, When loaded, Then error is raised or logged."""
        from core.config_loader import load_bitcoin_rpc_config

        env = self.default_env.copy()
        del env["BITCOIN_RPC_USER"]
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ValueError):
                load_bitcoin_rpc_config()

    def test_partial_fields_use_defaults(self):
        """Given only host and port in .env, When loaded, Then user/password missing triggers error."""
        from core.config_loader import load_bitcoin_rpc_config

        env = {
            "BITCOIN_RPC_HOST": "10.0.0.2",
            "BITCOIN_RPC_PORT": "18443",
        }
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ValueError):
                load_bitcoin_rpc_config()

    def test_default_host_used_when_unset(self):
        """Given no BITCOIN_RPC_HOST in .env, When loaded, Then host defaults to 127.0.0.1."""
        from core.config_loader import load_bitcoin_rpc_config

        env = self.default_env.copy()
        del env["BITCOIN_RPC_HOST"]
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            config = load_bitcoin_rpc_config()
            self.assertEqual(config["host"], "127.0.0.1")

    def test_default_port_used_when_unset(self):
        """Given no BITCOIN_RPC_PORT in .env, When loaded, Then port defaults to 8332."""
        from core.config_loader import load_bitcoin_rpc_config

        env = self.default_env.copy()
        del env["BITCOIN_RPC_PORT"]
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            config = load_bitcoin_rpc_config()
            self.assertEqual(config["port"], 8332)

    def test_cookie_file_not_found_raises(self):
        """Given BITCOIN_RPC_COOKIE pointing to a nonexistent file, When loaded, Then ValueError is raised."""
        from core.config_loader import load_bitcoin_rpc_config

        env = self.default_env.copy()
        env["BITCOIN_RPC_COOKIE"] = "/nonexistent/path/.cookie"
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ValueError) as context:
                load_bitcoin_rpc_config()
            self.assertIn("not found", str(context.exception))

    def test_cookie_file_read_successfully(self):
        """Given a well-formed cookie file, When loaded, Then user/password come from its contents,
        not from BITCOIN_RPC_USER/BITCOIN_RPC_PASSWORD."""
        from core.config_loader import load_bitcoin_rpc_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cookie", delete=False) as f:
            f.write("cookieuser:cookiepass\n")
            cookie_path = f.name
        try:
            env = self.default_env.copy()
            env["BITCOIN_RPC_COOKIE"] = cookie_path
            with unittest.mock.patch.dict("os.environ", env, clear=True):
                config = load_bitcoin_rpc_config()
                self.assertEqual(config["user"], "cookieuser")
                self.assertEqual(config["password"], "cookiepass")
        finally:
            os.remove(cookie_path)

    def test_cookie_file_malformed_raises(self):
        """Given a cookie file with no ':' separator, When loaded, Then ValueError is raised."""
        from core.config_loader import load_bitcoin_rpc_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cookie", delete=False) as f:
            f.write("nocolonhere")
            cookie_path = f.name
        try:
            env = self.default_env.copy()
            env["BITCOIN_RPC_COOKIE"] = cookie_path
            with unittest.mock.patch.dict("os.environ", env, clear=True):
                with self.assertRaises(ValueError):
                    load_bitcoin_rpc_config()
        finally:
            os.remove(cookie_path)


class TestReassemblyTimeoutConfigStory52(unittest.TestCase):
    def setUp(self):
        self.default_timeout = 30
        self.env_key = "REASSEMBLY_TIMEOUT_SECONDS"
        self.env = {
            "BITCOIN_RPC_HOST": "127.0.0.1",
            "BITCOIN_RPC_PORT": "8332",
            "BITCOIN_RPC_USER": "user",
            "BITCOIN_RPC_PASSWORD": "pass",
        }

    def test_timeout_loaded_from_env(self):
        from core.config_loader import load_reassembly_timeout

        env = self.env.copy()
        env[self.env_key] = "42"
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            timeout, source = load_reassembly_timeout()
            self.assertEqual(timeout, 42)
            self.assertEqual(source, "env")

    def test_timeout_missing_uses_default(self):
        from core.config_loader import load_reassembly_timeout

        with unittest.mock.patch.dict("os.environ", self.env, clear=True):
            timeout, source = load_reassembly_timeout()
            self.assertEqual(timeout, self.default_timeout)
            self.assertEqual(source, "default")

    def test_timeout_invalid_uses_default_and_logs_warning(self):
        from core.config_loader import load_reassembly_timeout

        env = self.env.copy()
        env[self.env_key] = "notanint"
        with unittest.mock.patch.dict("os.environ", env, clear=True):
            with unittest.mock.patch("core.config_loader.server_logger") as mock_logger:
                timeout, source = load_reassembly_timeout()
                self.assertEqual(timeout, self.default_timeout)
                self.assertEqual(source, "default")
                mock_logger.warning.assert_any_call(
                    "Invalid REASSEMBLY_TIMEOUT_SECONDS value 'notanint'. Using default: 30s."
                )

    def test_timeout_zero_or_negative_uses_default_and_logs_warning(self):
        from core.config_loader import load_reassembly_timeout

        for bad_val in ["0", "-5"]:
            env = self.env.copy()
            env[self.env_key] = bad_val
            with unittest.mock.patch.dict("os.environ", env, clear=True):
                with unittest.mock.patch(
                    "core.config_loader.server_logger"
                ) as mock_logger:
                    timeout, source = load_reassembly_timeout()
                    self.assertEqual(timeout, self.default_timeout)
                    self.assertEqual(source, "default")
                    mock_logger.warning.assert_any_call(
                        f"Invalid REASSEMBLY_TIMEOUT_SECONDS value '{bad_val}'. Using default: 30s."
                    )


class TestLoadAppConfig(unittest.TestCase):
    """Tests for load_app_config()'s .env loading and idempotency.

    Uses patch.object on the module's own `dotenv_loaded` flag (rather than
    manual save/restore) so each test's real, process-wide value is restored
    automatically on exit, regardless of what other test files already set it
    to earlier in a full suite run.
    """

    def setUp(self):
        import core.config_loader as config_loader

        self.config_loader = config_loader

    def test_loads_dotenv_when_env_file_exists(self):
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", False), \
                unittest.mock.patch("os.path.exists", return_value=True), \
                unittest.mock.patch("core.config_loader.load_dotenv") as mock_load_dotenv, \
                unittest.mock.patch("core.config_loader.server_logger") as mock_logger:
            self.config_loader.load_app_config()
            mock_load_dotenv.assert_called_once_with(dotenv_path=self.config_loader.DOTENV_PATH)
            mock_logger.info.assert_any_call(f".env file loaded from {self.config_loader.DOTENV_PATH}")
            self.assertTrue(self.config_loader.dotenv_loaded)

    def test_logs_and_continues_when_env_file_missing(self):
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", False), \
                unittest.mock.patch("os.path.exists", return_value=False), \
                unittest.mock.patch("core.config_loader.load_dotenv") as mock_load_dotenv, \
                unittest.mock.patch("core.config_loader.server_logger") as mock_logger:
            self.config_loader.load_app_config()
            mock_load_dotenv.assert_not_called()
            mock_logger.info.assert_any_call(
                f".env file not found at {self.config_loader.DOTENV_PATH}. "
                "Using environment variables or defaults."
            )
            self.assertTrue(self.config_loader.dotenv_loaded)

    def test_is_idempotent_once_loaded(self):
        """Given dotenv_loaded is already True, When called again, Then it's a no-op."""
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", True), \
                unittest.mock.patch("os.path.exists") as mock_exists, \
                unittest.mock.patch("core.config_loader.load_dotenv") as mock_load_dotenv:
            self.config_loader.load_app_config()
            mock_exists.assert_not_called()
            mock_load_dotenv.assert_not_called()


class TestGetMeshtasticSerialPort(unittest.TestCase):
    """Tests for get_meshtastic_serial_port()."""

    def setUp(self):
        import core.config_loader as config_loader

        self.config_loader = config_loader

    def test_returns_env_var_when_set(self):
        # dotenv_loaded forced True so this doesn't depend on the real .env
        # file's contents or the process-wide flag's current state.
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", True), \
                unittest.mock.patch.dict(
                    "os.environ", {"MESHTASTIC_SERIAL_PORT": "/dev/ttyUSB0"}, clear=True
                ):
            self.assertEqual(self.config_loader.get_meshtastic_serial_port(), "/dev/ttyUSB0")

    def test_returns_none_when_not_set(self):
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", True), \
                unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(self.config_loader.get_meshtastic_serial_port())

    def test_loads_app_config_when_not_yet_loaded(self):
        """Given config hasn't been loaded yet, When called, Then it loads it first."""
        with unittest.mock.patch.object(self.config_loader, "dotenv_loaded", False), \
                unittest.mock.patch.object(self.config_loader, "load_app_config") as mock_load_app_config:
            self.config_loader.get_meshtastic_serial_port()
            mock_load_app_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
