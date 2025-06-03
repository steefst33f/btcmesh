from typing import Any
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException

def connect_bitcoin_rpc(config: dict) -> Any:
    """
    Connects to Bitcoin Core RPC using the provided config dict.
    Returns an AuthServiceProxy instance if successful.
    Raises on error (invalid config, connection failure).
    Story 4.2.
    """
    url = f"http://{config['user']}:{config['password']}@{config['host']}:{int(config['port'])}"
    rpc = AuthServiceProxy(url)
    # Test connection
    rpc.getblockchaininfo()
    return rpc 


def broadcast_transaction_via_rpc(rpc, raw_tx_hex: str):
    """
    Broadcasts a raw transaction hex via Bitcoin Core RPC sendrawtransaction.
    Returns (txid, None) on success, (None, error_message) on failure.
    Story 4.3.
    """
    if rpc is None:
        return None, "No RPC connection"
    try:
        txid = rpc.sendrawtransaction(raw_tx_hex)
        return txid, None
    except JSONRPCException as e:
        msg = e.error.get('message', str(e))
        return None, msg
    except Exception as e:
        return None, str(e) 