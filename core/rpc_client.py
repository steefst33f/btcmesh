import requests
import json
import socket
import time
from urllib.parse import quote

from core.logger_setup import server_logger  # Assuming a logger is available

TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9050
TOR_CHECK_TIMEOUT_SECONDS = 5


class BitcoinRPCClient:
    class BitcoinRPCException(Exception):
        def __init__(self, error_info):
            self.code = error_info.get('code', 'Unknown code')
            self.message = error_info.get('message', 'Unknown error')
            super().__init__(self.message)

        def __str__(self):
            # Issue 35: self.code falls back to the string 'Unknown code'
            # (line 17) when error_info lacks a 'code' key - '%d' on a
            # string raises TypeError, crashing while formatting the
            # error itself.
            return '%s: %s' % (self.code, self.message)

        def __repr__(self):
            return '<%s \'%s\'>' % (self.__class__.__name__, self)

    def __init__(self, config: dict):
        user = config['user']
        password = config['password']

        host = config['host']
        if host is None:
            raise ValueError("'host' cannot be None")
        
        port = int(config['port'])
        if port is None:
            raise ValueError("'port' cannot be None")
        
        # Issue 28: user/password can legitimately contain characters
        # (@, :, /, #) that would otherwise corrupt the URI's authority
        # component or misparse into the wrong host/path.
        self.uri = f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
        self.use_tor = host.endswith(".onion")
        self.connect()  # Establish connection on initialization

    def connect(self):
        """Connects to Bitcoin Core RPC using the provided config dictionary."""
        if self.use_tor:
            self._check_tor_reachable()
        server_logger.debug("Connecting to Bitcoin RPC...")

        # Test connection and get chain info
        info = self.getblockchaininfo()
        self.chain = info['chain']  # Store chain for later access (main, test, testnet4, signet)
        server_logger.info(f"Connected to Bitcoin Core chain: {self.chain}")

    def _check_tor_reachable(self) -> None:
        """Verify the local Tor SOCKS proxy is reachable before attempting
        an RPC call through it (Issue 34). Without this, a missing/stopped
        Tor daemon surfaces as a confusing low-level connection-refused or
        timeout error from deep inside requests/urllib3 instead of a clear
        message - and previously this check only existed in the server
        GUI's "Test Connection" button, so real server startup (CLI and
        GUI alike) skipped it entirely.

        Raises:
            ConnectionError: If the SOCKS proxy port isn't reachable.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TOR_CHECK_TIMEOUT_SECONDS)
        try:
            result = sock.connect_ex((TOR_SOCKS_HOST, TOR_SOCKS_PORT))
        finally:
            sock.close()
        if result != 0:
            raise ConnectionError(
                f"Tor service not reachable on {TOR_SOCKS_HOST}:{TOR_SOCKS_PORT}"
            )

    def rpc_request(self, method, params=None, retries: int = 3, delay: int = 5):
        """Performs a JSON-RPC requests with automatic connection retry logic."""
        if self.use_tor:
            proxies = {
                'http': 'socks5h://127.0.0.1:9050',
                'https': 'socks5h://127.0.0.1:9050'
            }
        else:
            proxies = {}

        if params is None:
            params = []
        
        headers = {'Content-Type': 'application/json'}
        payload = {
            "jsonrpc": "1.0",
            "id": "btcmesh",
            "method": method,
            "params": params
        }

        for i in range(retries):
            try:
                server_logger.debug(f"Executing RPC method: {method} (Attempt {i + 1}/{retries})")
                response = requests.post(self.uri, data=json.dumps(payload), headers=headers, proxies=proxies, timeout=30)
                # response.raise_for_status()  # Raise an HTTPError for bad responses
                result = response.json()
                if result.get("error"):
                    raise self.BitcoinRPCException(result["error"])
                return result["result"]
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Issue 28: promoted from .debug() - server_logger runs at
                # INFO by default, so a connectivity problem an operator
                # actually needs to know about was previously invisible
                # without manually enabling DEBUG logging.
                if i < retries - 1:
                    server_logger.warning(
                        f"Connection error on {method}, retrying in {delay}s "
                        f"(attempt {i + 1}/{retries}): {e}"
                    )
                    time.sleep(delay)
                else:
                    server_logger.error(f"{method} failed after {retries} attempts: {e}")
                    raise  # Re-raise the exception after exhausting retries
            except Exception as e:
                # Log any other exceptions and re-raise
                server_logger.warning(f"Unexpected error during {method}: {e}")
                raise  # Re-raise any unexpected exception

    def getblockchaininfo(self):
        return self.rpc_request("getblockchaininfo")
        
    def sendrawtransaction(self, raw_tx_hex, max_fee_rate=0.0):
        # Bitcoin Core RPC sendrawtransaction takes an optional maxfeerate.
        # Setting to 0.0 means no limit.
        return self.rpc_request("sendrawtransaction", [raw_tx_hex, max_fee_rate])
    
    def broadcast_transaction(self, raw_tx_hex: str):
        """
        Broadcasts a raw transaction hex via Bitcoin Core RPC sendrawtransaction.
        Returns (txid, None) on success or (None, error_message) on failure.
        """
        server_logger.debug(f"Calling broadcast_transaction_via_rpc: raw_tx_hex: {raw_tx_hex}")
        
        try:
            txid = self.sendrawtransaction(raw_tx_hex, 0.0)  # Pass 0.0 for no fee rate limit
            server_logger.info(f"Transaction ID received: {txid}")
            return txid, None
        except self.BitcoinRPCException as e:
            message = e.message
            server_logger.warning(f"RPC rejected transaction (code {e.code}): {e.message}")
            return None, message
        except requests.exceptions.RequestException as e:
            server_logger.warning(f"RequestException during broadcast: {e}")
            return None, str(e)
        except Exception as e:
            server_logger.warning(f"Unexpected error during broadcast: {e}")
            return None, str(e)
