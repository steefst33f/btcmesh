#!/usr/bin/env python3
import argparse
import sys
import re
import uuid
import os
from core.config_loader import get_meshtastic_serial_port
from core.logger_setup import setup_logger

def is_valid_hex(s):
    try:
        int(s, 16)
        return True
    except Exception:
        return False

CHUNK_SIZE = 200  # hex chars (100 bytes)

def chunk_transaction(tx_hex, chunk_size):
    return [tx_hex[i:i+chunk_size] for i in range(0, len(tx_hex), chunk_size)]

def generate_session_id():
    return uuid.uuid4().hex[:12]  # 12 hex chars for uniqueness

# Example raw transaction for reference and testing (see reference_materials.md):
EXAMPLE_RAW_TX = (
    "02000000000108bf2c7da5efaf2708170ffbafde7b2b0ca68234474ea71d443aee6aebfbf998030000000000fdffffff"
    "d6fcdbf37f974be27e8b0d66638355e5f53bfaf7b930fae035d23b313c4751042900000000fdffffffcccc5ca913b8eb426fd7c6bb578eab0f26583d40c51ce52cb12a428c1e75f7320100000000fdffffff981b8b54ad2a8bd8b59d063e9473aead87412b699cb969298cf29b8787fe10600000000000fdffffff5d154c445b35a92aaf179c078cdab6310e69455cde650f128cbe85d92bab51600100000000fdffffff7d23c74a412ef33d5dd856d01933dd6a5453aee3539b12349febbf6c1ba157980100000000fdffffffc5c95ce2eac84fbd3db87bbbdb4cc0855088e891cc57b1f9e0684943a399aabf0000000000fdffffffb7ef5d8a55141068da0d7b5a712ad9bbe44c3b8b412d0df5b9bcad366d71c8f90500000000fdffffff01697c63030000000016001482ea8436a6318c989767a51ce33886d65faf59a10247304402203ec9cfb2b60a7b1df545493d1794fec0b8b6d8589f562f61c9aec6852775b54102205dfb34dcc9cc31110fdf4e4544c76e9a664cf29e8f1f9905771db386882527190121030e92cc6f0829ea8b91469c8aa7ca0660d66020d3e8baaece478905e0c30c1f770247304402204a3a6a7a5d4ff285b1ba4a3457dae8566a1616738f94e9eddcce6a75dbb831ef0220285c586f6463dcf68ccef59484b2d12bccd7d68a68b7092068e6cbfd96f04d88012102f48b8ab9a082a1cf94dcd7052ddea7d260b40cf01e83aa3df00f2266721ef420024730440220527c3eb66a06d697a078b2b2bdf9be52f9fe036b1e3422a0a150e151ff0cd25b0220268688d8d9a3dd24b9f846b1b2f1b1f1ed84443f0023e26fa1ac5f2c1f0626ac012103acc2fbe36c425eb49389e5896232ef90beda75531845cd726dfed5f60a1fedd10247304402202eee600a307d10fc4777e8143d3db8994a6e742d56d4e3ce67a21a1e5e509178022022ee1b1fee5d7ec8112a56b1c0ab2eef1be00907d384bbf10a7a9d2d27564fb5012103bd6876311fbf657af0c1c85e907c3adf8d5086d1b3cf2cd4805b40873d2cf3cd02473044022042dbc6204b70da1548456beef504d5e8d61349dd36913832060b35f61a360429022006940b48cff72f6476b8d4495126618766500f0868fb99ba40ab518934e9cc2b0121035aa46c0cf9b30a9edf20c65e5c39158aefbfdd2b7a049d146f42b7dc3163d1b50247304402207811bd5b127e8a693f20115f7f8b8b4dec6a4d5df32109b21e1252331778ac5202202ac727cc6c53287110fcd371845b5fcdba825cb9e60992cc01cffa8e2ee41701012102700455a96ddb63fdaf8fc3ad60d02b057f8e00ed512476d817150a22fd4495d90247304402202caf8f9c584fe1b5214dc2a67f42fe3b9fd7386b98807fc6bc273a2cf519769902201f9f7b407f92c7df84701e4259acb198ca19c5edbd860385caa6ca1316417c010121035bfcbb577fe3a3a805c78226c7e7c573053e85e6641243c8f435acde0e04668902473044022074d6273ed2c7f338c9db6a979f64f572a21e5a324eec4979dad77383b25263de02202635d0e21ddf4e46f5751d4d6117ad559f04b7a6d3d00f13dd784b82a902638e012103de05dcec6736d4e15dd88c5b34b638fee6cccfd8b260d53379a43be0b343617cd9540c00"
)

CLI_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'btcmesh_cli.log')
cli_logger = setup_logger('btcmesh_cli', CLI_LOG_FILE)

def initialize_meshtastic_interface_cli(port=None):
    """
    Initializes and returns a Meshtastic SerialInterface for CLI use.
    Logs all attempts and errors to both stdout and the CLI log file.
    Args:
        port: Optional override for serial port.
    Returns:
        Meshtastic SerialInterface instance if successful, None otherwise.
    """
    serial_port_to_use = port if port is not None else get_meshtastic_serial_port()
    try:
        import meshtastic.serial_interface
        from meshtastic import MeshtasticError, NoDeviceError
        log_port_info = f' on port {serial_port_to_use}' if serial_port_to_use else ' (auto-detect)'
        cli_logger.info(f"Attempting to initialize Meshtastic interface{log_port_info}...")
        iface = (
            meshtastic.serial_interface.SerialInterface(devPath=serial_port_to_use)
            if serial_port_to_use else meshtastic.serial_interface.SerialInterface()
        )
        node_num_display = "Unknown Node Num"
        if hasattr(iface, 'myInfo') and iface.myInfo and hasattr(iface.myInfo, 'my_node_num'):
            node_num_display = str(iface.myInfo.my_node_num)
        cli_logger.info(f"Meshtastic interface initialized successfully. Device: {getattr(iface, 'devicePath', '?')}, My Node Num: {node_num_display}")
        return iface
    except ImportError:
        cli_logger.error("Meshtastic library not found. Please install it (e.g., pip install meshtastic).")
        return None
    except Exception as e:
        # Try to distinguish NoDeviceError and MeshtasticError if possible
        try:
            from meshtastic import NoDeviceError, MeshtasticError
            if isinstance(e, NoDeviceError):
                cli_logger.error("No Meshtastic device found. Ensure it is connected and drivers are installed.")
                return None
            if isinstance(e, MeshtasticError):
                cli_logger.error(f"Meshtastic library error during initialization: {e}")
                return None
        except Exception:
            pass
        cli_logger.error(f"An unexpected error occurred during Meshtastic initialization: {e}", exc_info=True)
        return None

def cli_main(args=None, injected_iface=None, injected_logger=None):
    import argparse
    import sys
    import re
    if args is None:
        parser = argparse.ArgumentParser(description="Send a raw Bitcoin transaction via Meshtastic LoRa relay.")
        parser.add_argument('-d', '--destination', required=True, help='Destination node ID (e.g., !abcdef12)')
        parser.add_argument('-tx', '--tx', required=True, help='Raw transaction hex string')
        parser.add_argument('--dry-run', action='store_true', help='Only parse and print arguments, do not send')
        args = parser.parse_args()
    tx_hex = args.tx
    if len(tx_hex) % 2 != 0 or not re.fullmatch(r'[0-9a-fA-F]+', tx_hex):
        print('Invalid raw transaction hex: must be even length and hex characters only.', file=sys.stderr)
        raise ValueError('Invalid raw transaction hex')
    logger = injected_logger if injected_logger is not None else cli_logger
    if args.dry_run:
        print(f"Arguments parsed successfully:")
        print(f"  Destination: {args.destination}")
        print(f"  Raw TX Hex: {args.tx}")
        session_id = generate_session_id()
        chunks = chunk_transaction(tx_hex, CHUNK_SIZE)
        total_chunks = len(chunks)
        for i, payload in enumerate(chunks, 1):
            print(f"BTC_TX|{session_id}|{i}/{total_chunks}|{payload}")
        return 0
    iface = injected_iface if injected_iface is not None else initialize_meshtastic_interface_cli()
    if iface is None:
        print("Failed to initialize Meshtastic interface. See logs for details.", file=sys.stderr)
        raise RuntimeError('Failed to initialize Meshtastic interface')
    session_id = generate_session_id()
    chunks = chunk_transaction(tx_hex, CHUNK_SIZE)
    total_chunks = len(chunks)
    for i, payload in enumerate(chunks, 1):
        msg = f"BTC_TX|{session_id}|{i}/{total_chunks}|{payload}"
        try:
            iface.sendText(text=msg, destinationId=args.destination)
            print(f"Sent chunk {i}/{total_chunks} for session {session_id}")
            logger.info(f"Sent chunk {i}/{total_chunks} for session {session_id} to {args.destination}")
        except Exception as e:
            err_msg = f"Error sending chunk {i}/{total_chunks} for session {session_id}: {e}"
            print(err_msg, file=sys.stderr)
            logger.error(f"Error sending chunk {i}/{total_chunks} for session {session_id}", exc_info=True)
            raise
    print(f"All transaction chunks sent for session {session_id}.")
    logger.info(f"All transaction chunks sent for session {session_id} to {args.destination}.")
    return 0

def main():
    import sys
    try:
        cli_main()
    except ValueError:
        sys.exit(1)
    except RuntimeError:
        sys.exit(2)
    except Exception:
        sys.exit(3)
    sys.exit(0)

if __name__ == '__main__':
    main() 