import logging
import os
from dotenv import load_dotenv
from typing import Optional

from core.logger_setup import server_logger

_LOG_LEVEL_NAMES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# Load environment variables from .env file in the project root
# Determine the project root by going up one level from the 'core' directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# A flag to ensure dotenv is loaded only once
dotenv_loaded = False


def load_app_config() -> None:
    """Loads the .env file. Can be called explicitly at app startup."""
    global dotenv_loaded
    if not dotenv_loaded:
        if os.path.exists(DOTENV_PATH):
            load_dotenv(dotenv_path=DOTENV_PATH)
            server_logger.info(f".env file loaded from {DOTENV_PATH}")
            dotenv_loaded = True
        else:
            server_logger.info(
                f".env file not found at {DOTENV_PATH}. "
                "Using environment variables or defaults."
            )
            # dotenv_loaded can be set to True even if not found,
            # to prevent re-checks or kept False if we want to allow
            # retries/reloads in some scenarios. For typical app startup,
            # one check is enough.
            dotenv_loaded = True


def get_meshtastic_serial_port() -> Optional[str]:
    """
    Retrieves the Meshtastic serial port from environment variables.
    Ensures .env is loaded before attempting to retrieve.
    """
    if not dotenv_loaded:
        load_app_config()  # Ensure config is loaded

    return os.getenv("MESHTASTIC_SERIAL_PORT")


def get_relay_serial_port() -> Optional[str]:
    """
    Retrieves the DIY power-relay board's serial port from environment
    variables (Story 26.7). Always explicit - unlike the Meshtastic port,
    this is never auto-detected, since scan_meshtastic_devices() would
    otherwise treat the relay board's own serial port as a false-positive
    Meshtastic candidate (see transport/power_control.py's
    SerialRelayPowerControl).
    """
    if not dotenv_loaded:
        load_app_config()

    return os.getenv("RELAY_SERIAL_PORT")


def load_relay_serial_baud():
    """
    Loads the DIY power-relay board's serial baud rate (Story 26.7) from
    environment variables (.env). Returns (baud: int, source: str); source
    is 'env' or 'default'. Falls back to the firmware's default (115200) if
    missing/invalid.
    """
    if not dotenv_loaded:
        load_app_config()
    val = os.environ.get("RELAY_SERIAL_BAUD")
    default = 115200
    if val is None:
        return default, "default"
    try:
        baud = int(val)
        if baud <= 0:
            raise ValueError()
        return baud, "env"
    except Exception:
        server_logger.warning(
            f"Invalid RELAY_SERIAL_BAUD value '{val}'. Using default: {default}."
        )
        return default, "default"


def get_relay_channel() -> int:
    """
    Loads the DIY power-relay board's channel number (Story 26.7) from
    environment variables (.env). Defaults to 1 - a single relay channel
    per device is the normal deployment (server/client each typically
    manage one local device); only set RELAY_CHANNEL if this machine's
    relay controls more than one device. Falls back to the default on any
    invalid value.
    """
    if not dotenv_loaded:
        load_app_config()
    val = os.environ.get("RELAY_CHANNEL")
    default = 1
    if val is None:
        return default
    try:
        channel = int(val)
        if channel <= 0:
            raise ValueError()
        return channel
    except Exception:
        server_logger.warning(
            f"Invalid RELAY_CHANNEL value '{val}'. Using default: {default}."
        )
        return default


def build_bitcoin_rpc_config(
    host: str,
    port,
    user: Optional[str] = None,
    password: Optional[str] = None,
    cookie_path: Optional[str] = None,
) -> dict:
    """
    Build a Bitcoin RPC config dict from explicit values (Issue 29).

    Resolves cookie-file auth the same way load_bitcoin_rpc_config() does
    from env vars, but takes values directly - so any caller with its own
    source of these values (e.g. a GUI's text inputs, not just os.environ)
    gets the same cookie-file handling instead of reimplementing it.

    Args:
        host, port: RPC host and port (required).
        user, password: RPC credentials. Ignored if cookie_path is given.
        cookie_path: Path to a Bitcoin Core .cookie file. If given, user/
            password are read from it instead (overriding any passed in).

    Returns:
        dict with host, port, user, password.

    Raises:
        ValueError: If cookie_path is given but unreadable, or if neither
            cookie_path nor both user and password are usable.
    """
    config = {"host": host, "port": int(port), "user": user, "password": password}
    if cookie_path:
        if not os.path.isfile(cookie_path):
            raise ValueError(f".cookie file not found: {cookie_path}")
        try:
            with open(cookie_path, "r") as f:
                cookie = f.read().strip()
                config["user"], config["password"] = cookie.split(":", 1)
        except Exception as e:
            raise ValueError(f"Error to read file .cookie: {e}")
    elif not config["user"] or not config["password"]:
        raise ValueError(
            "Wrong credentials. "
            "Define BITCOIN_RPC_COOKIE or BITCOIN_RPC_USER and BITCOIN_RPC_PASSWORD."
        )
    return config


def load_bitcoin_rpc_config():
    """
    Loads Bitcoin RPC config from environment variables (.env).
    Returns a dict with host, port, user, password.
    Raises ValueError if any required field is missing.
    Story 4.1.
    """
    return build_bitcoin_rpc_config(
        host=os.getenv("BITCOIN_RPC_HOST", "127.0.0.1"),
        port=os.getenv("BITCOIN_RPC_PORT", 8332),
        user=os.environ.get("BITCOIN_RPC_USER"),
        password=os.environ.get("BITCOIN_RPC_PASSWORD"),
        cookie_path=os.getenv("BITCOIN_RPC_COOKIE"),
    )


def load_reassembly_timeout():
    """
    Loads reassembly timeout (seconds) from environment variables (.env).
    Returns (timeout_seconds: int, source: str); source is 'env' or 'default'.
    Logs the loaded value and its source.
    Falls back to default (30s) if missing/invalid.
    """
    if not dotenv_loaded:
        load_app_config()
    val = os.environ.get("REASSEMBLY_TIMEOUT_SECONDS")
    default = 30
    if val is None:
        server_logger.info(
            f"REASSEMBLY_TIMEOUT_SECONDS not set. Using default: {default}s."
        )
        return default, "default"
    try:
        timeout = int(val)
        if timeout <= 0:
            raise ValueError()
        server_logger.info(f"Loaded reassembly timeout from env: {timeout}s.")
        return timeout, "env"
    except Exception:
        server_logger.warning(
            f"Invalid REASSEMBLY_TIMEOUT_SECONDS value '{val}'. "
            f"Using default: {default}s."
        )
        return default, "default"


def load_log_level():
    """
    Loads the console/file log level (Issue 49) from environment variables
    (.env). Returns (level: int, source: str); source is 'env' or 'default'.
    Accepts DEBUG/INFO/WARNING/ERROR/CRITICAL, case-insensitive.
    Falls back to default (logging.INFO) if missing/invalid.
    """
    if not dotenv_loaded:
        load_app_config()
    val = os.environ.get("LOG_LEVEL")
    default = logging.INFO
    if val is None:
        return default, "default"
    level = _LOG_LEVEL_NAMES.get(val.strip().upper())
    if level is None:
        server_logger.warning(
            f"Invalid LOG_LEVEL value '{val}'. Using default: INFO."
        )
        return default, "default"
    return level, "env"


# Example of how to extend for more configurations:
# def get_rpc_host() -> Optional[str]:
#     if not dotenv_loaded:
#         load_app_config()
#     return os.getenv('BITCOIN_RPC_HOST')

# Call load_app_config at module import time if you want it to load
# automatically when this module is imported. Or, call it explicitly
# from your main script. For now, let's make it explicit by calling
# from functions that need the config.
