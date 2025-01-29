import logging
import sys
import os


def setup_logger():
    """Configure logging with timestamps including minutes, seconds, and milliseconds"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Clear the log file
    log_file = "logs/server.log"
    with open(log_file, "w") as f:
        f.truncate(0)

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear any existing handlers
    logger.handlers.clear()

    # Create formatter with minutes, seconds, and milliseconds
    formatter = logging.Formatter(
        # "[%(asctime)s.%(msecs)03d] %(message)s", datefmt="%H:%M:%S"
        "\033[32m[%(asctime)s]\033[0m %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Create console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    return logger


# Create and export logger instance
logger = setup_logger()
