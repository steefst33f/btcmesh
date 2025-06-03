import os
from dotenv import load_dotenv
from typing import Optional

from core.logger_setup import server_logger

# Load environment variables from .env file in the project root
# Determine the project root by going up one level from the 'core' directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')

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
            server_logger.info(f".env file not found at {DOTENV_PATH}. Using environment variables or defaults.")
            # dotenv_loaded can be set to True even if not found, to prevent re-checks
            # or kept False if we want to allow retries/reloads in some scenarios.
            # For typical app startup, one check is enough.
            dotenv_loaded = True


def get_meshtastic_serial_port() -> Optional[str]:
    """
    Retrieves the Meshtastic serial port from environment variables.
    Ensures .env is loaded before attempting to retrieve.
    """
    if not dotenv_loaded:
        load_app_config() # Ensure config is loaded
    
    return os.getenv('MESHTASTIC_SERIAL_PORT')

# Example of how to extend for more configurations:
# def get_rpc_host() -> Optional[str]:
#     if not dotenv_loaded:
#         load_app_config()
#     return os.getenv('BITCOIN_RPC_HOST')

# Call load_app_config at module import time if you want it to load automatically
# when this module is imported. Or, call it explicitly from your main script.
# For now, let's make it explicit by calling from functions that need the config. 