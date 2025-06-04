import sys
import os

# Adjust the path to include the project root if
# test_bitcoin_connection.py is in the root
# and core module is in a subdirectory.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from core.config_loader import load_app_config, load_bitcoin_rpc_config
    from core.rpc_client import connect_bitcoin_rpc

    # Import Tor management functions and SOCKS port from btcmesh_server
    from btcmesh_server import TOR_SOCKS_PORT, start_tor, stop_tor
except ImportError as e:
    print(f"Error importing necessary modules: {e}")
    print(
        "Please ensure that test_bitcoin_connection.py is in the project root "
        "directory, and the 'core' and 'btcmesh_server.py' are accessible."
    )
    sys.exit(1)

# Example raw transaction hex provided by the user
EXAMPLE_RAW_TX = (
    "02000000000108bf2c7da5efaf2708170ffbafde7b2b0ca68234474ea71d443aee6ae"
    "bfbf998030000000000fdffffffd6fcdbf37f974be27e8b0d66638355e5f53bfaf7"
    "b930fae035d23b313c4751042900000000fdffffffcccc5ca913b8eb426fd7c6bb57"
    "8eab0f26583d40c51ce52cb12a428c1e75f7320100000000fdffffff981b8b54ad2a"
    "8bd8b59d063e9473aead87412b699cb969298cf29b8787fe1060000000000fdffff"
    "ff5d154c445b35a92aaf179c078cdab6310e69455cde650f128cbe85d92bab516001"
    "00000000fdffffff7d23c74a412ef33d5dd856d01933dd6a5453aee3539b12349feb"
    "bf6c1ba157980100000000fdffffffc5c95ce2eac84fbd3db87bbbdb4cc0855088e8"
    "91cc57b1f9e0684943a399aabf0000000000fdffffffb7ef5d8a55141068da0d7b5a"
    "712ad9bbe44c3b8b412d0df5b9bcad366d71c8f90500000000fdffffff01697c6303"
    "0000000016001482ea8436a6318c989767a51ce33886d65faf59a10247304402203e"
    "c9cfb2b60a7b1df545493d1794fec0b8b6d8589f562f61c9aec6852775b54102205d"
    "fb34dcc9cc31110fdf4e4544c76e9a664cf29e8f1f9905771db38688252719012103"
    "0e92cc6f0829ea8b91469c8aa7ca0660d66020d3e8baaece478905e0c30c1f770247"
    "304402204a3a6a7a5d4ff285b1ba4a3457dae8566a1616738f94e9eddcce6a75dbb8"
    "31ef0220285c586f6463dcf68ccef59484b2d12bccd7d68a68b7092068e6cbfd96f0"
    "4d88012102f48b8ab9a082a1cf94dcd7052ddea7d260b40cf01e83aa3df00f2266721e"
    "f420024730440220527c3eb66a06d697a078b2b2bdf9be52f9fe036b1e3422a0a150"
    "e151ff0cd25b0220268688d8d9a3dd24b9f846b1b2f1b1f1ed84443f0023e26fa1ac"
    "5f2c1f0626ac012103acc2fbe36c425eb49389e5896232ef90beda75531845cd726dfed"
    "5f60a1fedd10247304402202eee600a307d10fc4777e8143d3db8994a6e742d56d4e3"
    "ce67a21a1e5e509178022022ee1b1fee5d7ec8112a56b1c0ab2eef1be00907d384bbf1"
    "0a7a9d2d27564fb5012103bd6876311fbf657af0c1c85e907c3adf8d5086d1b3cf2cd4"
    "805b40873d2cf3cd02473044022042dbc6204b70da1548456beef504d5e8d61349dd3"
    "6913832060b35f61a360429022006940b48cff72f6476b8d4495126618766500f0868"
    "fb99ba40ab518934e9cc2b0121035aa46c0cf9b30a9edf20c65e5c39158aefbfdd2b7a"
    "049d146f42b7dc3163d1b50247304402207811bd5b127e8a693f20115f7f8b8b4dec6a"
    "4d5df32109b21e1252331778ac5202202ac727cc6c53287110fcd371845b5fcdba825c"
    "b9e60992cc01cffa8e2ee41701012102700455a96ddb63fdaf8fc3ad60d02b057f8e00"
    "ed512476d817150a22fd4495d90247304402202caf8f9c584fe1b5214dc2a67f42fe3b"
    "9fd7386b98807fc6bc273a2cf519769902201f9f7b407f92c7df84701e4259acb198ca"
    "19c5edbd860385caa6ca1316417c010121035bfcbb577fe3a3a805c78226c7e7c57305"
    "3e85e6641243c8f435acde0e04668902473044022074d6273ed2c7f338c9db6a979f64"
    "f572a21e5a324eec4979dad77383b25263de02202635d0e21ddf4e46f5751d4d6117ad"
    "559f04b7a6d3d00f13dd784b82a902638e012103de05dcec6736d4e15dd88c5b34b638"
    "fee6cccfd8b260d53379a43be0b343617cd9540c00"
)


def main():
    print("Starting Bitcoin node connection test...")
    tor_process = None
    tor_data_dir = None

    try:
        print("\nStep 1: Loading application configuration (for .env)...")
        try:
            load_app_config()
            print("Application configuration loaded.")
        except Exception as e:
            print(f"Failed to load application configuration: {e}")
            sys.exit(1)

        print("\nStep 2: Loading Bitcoin RPC configuration...")
        rpc_config = None
        try:
            rpc_config = load_bitcoin_rpc_config()
            print(
                f"Bitcoin RPC config loaded: Host={rpc_config['host']}, "
                f"Port={rpc_config['port']}, User={rpc_config['user']}"
            )
        except ValueError as e:
            print(f"Failed to load Bitcoin RPC configuration: {e}")
            print(
                "Please ensure BITCOIN_RPC_HOST, _PORT, _USER, and _PASSWORD "
                "are correctly set in your .env file."
            )
            sys.exit(1)
        except Exception as e:
            print(
                "An unexpected error occurred while loading Bitcoin RPC "
                f"configuration: {e}"
            )
            sys.exit(1)

        # Check for .onion address and start Tor if needed
        if rpc_config["host"].endswith(".onion"):
            print(
                f"Detected .onion address ({rpc_config['host']}). "
                "Attempting to start Tor..."
            )
            try:
                tor_process, tor_data_dir = start_tor(TOR_SOCKS_PORT)
                print(
                    f"Tor started successfully. Process ID: "
                    f"{tor_process.pid if tor_process else 'N/A'}"
                )
                proxy_url = f"socks5h://localhost:{TOR_SOCKS_PORT}"
                rpc_config["proxy"] = proxy_url
                print(f"Using Tor SOCKS proxy: {proxy_url}")
            except Exception as e:
                print(f"Failed to start Tor: {e}")
                print(
                    "Ensure Tor executable is correctly placed (e.g., in "
                    "tor/tor relative to project root) and has permissions."
                )
                sys.exit(1)

        print("\nStep 3: Attempting to connect to Bitcoin Core RPC node...")
        rpc = None
        try:
            rpc = connect_bitcoin_rpc(rpc_config)
            print("Successfully initiated connection object.")
        except Exception as e:
            print("Failed to establish connection with Bitcoin Core RPC node: " f"{e}")
            print(
                "Check your Bitcoin node's status, RPC settings, and network "
                "connectivity."
            )
            if rpc_config.get("proxy"):
                print(
                    "Also, verify Tor is working correctly if a .onion "
                    "address is used."
                )
            sys.exit(1)

        print("\nStep 4: Calling getblockchaininfo()...")
        try:
            blockchain_info = rpc.getblockchaininfo()
            print("Successfully called getblockchaininfo(). Response:")
            print(f"  Chain: {blockchain_info.get('chain')}")
            print(f"  Blocks: {blockchain_info.get('blocks')}")
            print(f"  Headers: {blockchain_info.get('headers')}")
            print(
                f"  Verification Progress: "
                f"{blockchain_info.get('verificationprogress')}"
            )
            print(
                f"  Initial Block Download: "
                f"{blockchain_info.get('initialblockdownload')}"
            )
            print("\nBasic connection test successful!")
        except Exception as e:
            print(f"Error calling getblockchaininfo(): {e}")
            print("The connection object was created, but an RPC command failed.")
            print(
                "This could indicate an issue with the RPC interface on the "
                "node, permissions, or network issues preventing the "
                "command execution."
            )
            sys.exit(1)

        print("\nStep 5: Attempting to broadcast an example raw transaction...")
        print(
            f"Using raw transaction hex (first 80 chars): " f"{EXAMPLE_RAW_TX[:80]}..."
        )
        try:
            # The sendrawtransaction method in our rpc object
            # (AuthServiceProxy or RequestsBitcoinRPC) from core.rpc_client
            # was updated to accept max_fee_rate as the second argument.
            # We pass 0.0 for no feerate limit.
            txid = rpc.sendrawtransaction(EXAMPLE_RAW_TX, 0.0)
            print(f"Successfully broadcast example transaction. TXID: {txid}")
            print("\nRaw transaction broadcast test successful!")
        except Exception as e:
            print(f"Error broadcasting example transaction: {e}")
            print(
                "This could indicate an issue with the transaction itself "
                "(e.g., invalid, already broadcast),"
            )
            print(
                "stricter rules on your Bitcoin node for transaction relay, "
                "or the transaction fee rate."
            )
            # We don't sys.exit(1) here as the primary test
            # (getblockchaininfo) passed. This is an additional diagnostic step.

    finally:
        if tor_process:
            print("\nCleaning up: Stopping Tor process...")
            stop_tor(tor_process, tor_data_dir)
            print("Tor process stopped.")
        print("\nTest script finished.")


if __name__ == "__main__":
    main()
