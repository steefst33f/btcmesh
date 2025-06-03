import logging
import os
from logging.handlers import RotatingFileHandler

# Define the log directory and ensure it exists
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = logging.INFO

# Server log file
SERVER_LOG_FILE = os.path.join(LOG_DIR, 'btcmesh_server.log')

def setup_logger(logger_name: str, log_file: str, level: int = LOG_LEVEL) -> logging.Logger:
    """
    Configures and returns a logger instance.

    Args:
        logger_name: The name for the logger.
        log_file: The path to the log file.
        level: The logging level.

    Returns:
        A configured logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False  # Prevents log duplication if root logger is also configured

    # Avoid adding handlers if they already exist (e.g., in tests or multiple calls)
    if not logger.handlers:
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(console_handler)

        # File Handler (Rotating)
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5) # 10MB per file, 5 backups
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)

    return logger

# Pre-configured server logger instance
server_logger = setup_logger('btcmesh_server', SERVER_LOG_FILE)

if __name__ == '__main__':
    # Example usage:
    test_logger = setup_logger('test_logger', os.path.join(LOG_DIR, 'test.log'), logging.DEBUG)
    test_logger.debug("This is a debug message.")
    test_logger.info("This is an info message.")
    test_logger.warning("This is a warning message.")
    test_logger.error("This is an error message.")
    test_logger.critical("This is a critical message.")

    server_logger.info("Server logger test message from logger_setup.py") 