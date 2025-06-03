# BTC Mesh Relay

## Description

BTC Mesh Relay is a project designed to enable the broadcasting of Bitcoin raw transactions by sending them as chunked hexadecimal strings via LoRa Meshtastic direct messages. A dedicated client script (`btcmesh_cli.py`, planned) will be used for sending, and a relay device running `btcmesh_server.py` will reassemble these chunks, decode, validate, and then relay the complete transaction to a configured Bitcoin RPC node. This system is intended for scenarios with limited or censored internet access but where LoRa Meshtastic network availability exists.

This project is currently under development.

## Features (Planned & In-Progress)

*   **Meshtastic Communication**: Initializes and manages communication with a Meshtastic device.
*   **Transaction Chunking & Reassembly**: Allows large Bitcoin transactions to be sent in smaller chunks over LoRa and reassembled by the relay.
*   **Payload Handling**: Validates reassembled hexadecimal strings and decodes them into Bitcoin transaction structures.
*   **Basic Transaction Validation**: Performs sanity checks on decoded transactions (e.g., presence of inputs/outputs).
*   **Bitcoin RPC Integration**: Connects to a Bitcoin Core RPC node to broadcast the validated raw transaction.
*   **Logging**: Comprehensive logging for both server and client operations.
*   **Client Script (`btcmesh_cli.py`)**: A command-line tool for users to easily send raw transactions.

## Project Structure

```
btcmesh/
├── btcmesh_cli.py         # Client script (Planned)
├── btcmesh_server.py      # Server/Relay script
├── core/                  # Core logic for the server/relay
│   ├── __init__.py
│   ├── config_loader.py   # For loading .env and other configurations
│   ├── logger_setup.py    # For setting up consistent logging
│   ├── transaction_parser.py # For decoding raw Bitcoin transactions (Planned)
│   ├── rpc_client.py      # For interacting with Bitcoin RPC (Planned)
│   └── reassembler.py     # For reassembling chunked messages (Planned)
├── project/               # Project planning documents
│   ├── tasks.txt
│   └── reference_materials.md
├── logs/                  # Directory for log files (created at runtime)
├── tests/                 # Unit and integration tests
├── .env.example           # Example environment variable configuration file
├── config.ini.example     # Example INI configuration file (Planned for more complex settings)
├── requirements.txt       # Python dependencies
└── README.md              # This file
```
(Refer to `project/tasks.txt` for detailed ongoing tasks and user stories.)

## Setup Instructions

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd btcmesh
    ```

2.  **Create and Activate Conda Environment**:
    It's recommended to use a Conda environment. If you don't have Conda, please [install it first](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html).
    ```bash
    conda create -n btcmesh python=3.11
    conda activate btcmesh
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment (.env)**:
    The application can be configured using a `.env` file in the project root.
    Copy the example file to create your own configuration:
    ```bash
    cp .env.example .env
    ```
    Then, edit the `.env` file to set your specific configurations. For example:

    *   **`MESHTASTIC_SERIAL_PORT`**: Specifies the serial port for your Meshtastic device (e.g., `/dev/ttyUSB0`, `/dev/ttyACM0` on Linux, or `COM3` on Windows). If this is not set or is commented out, the application will attempt to auto-detect the Meshtastic device.
        ```env
        # MESHTASTIC_SERIAL_PORT=/dev/your/meshtastic_port
        ```

5.  **Meshtastic Device Setup**:
    *   Ensure you have a Meshtastic device connected to the machine where `btcmesh_server.py` will run (and another for the client when `btcmesh_cli.py` is used).
    *   The Meshtastic Python library, by default, attempts to auto-detect your device. You can specify the serial port explicitly by setting `MESHTASTIC_SERIAL_PORT` in your `.env` file (see step 4).

6.  **Bitcoin Core RPC Setup (for Relay)**:
    *   The relay server (`btcmesh_server.py`) will need to connect to a running Bitcoin Core node with RPC enabled.
    *   Ensure your Bitcoin Core node is configured to accept RPC connections and that you have the necessary credentials (RPC user, password, host, port).
    *   (Future) These details will be configured in a `config.ini` file. See `config.ini.example` (once available).

## Configuration

The primary method for basic configuration (like serial ports) is via a `.env` file in the project root (see "Configure Environment (.env)" in Setup Instructions).

(Planned) For more advanced or structured configurations, the server might also support a `config.ini` file. An example file `config.ini.example` will be provided if this is implemented.

Key settings that can or will be configurable:

*   Meshtastic device serial port (`MESHTASTIC_SERIAL_PORT` in `.env`).
*   Bitcoin RPC connection details (host, port, user, password) - likely via `.env` or `config.ini` in the future.

## Running the Server

Once set up and configured, you can run the BTC Mesh Relay server:

```bash
conda activate btcmesh
python btcmesh_server.py
```

The server will initialize the Meshtastic interface and start listening for incoming messages.

## Running Tests

To run the automated tests:

```bash
conda activate btcmesh
python -m unittest discover -s tests -p 'test_*.py'
```

## Contributing

Contributions are welcome! Please refer to the project's issue tracker and development plan in `project/tasks.txt`. Follow TDD/BDD principles when adding new features or fixing bugs. 