import logging
import sys


def setup_logger():
    """Configure logging with timestamps including minutes, seconds, and milliseconds"""
    logger = logging.getLogger("kindle_automator")
    logger.setLevel(logging.INFO)

    # Create console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create formatter with minutes, seconds, and milliseconds
    formatter = logging.Formatter(
        # "[%(asctime)s.%(msecs)03d] %(message)s", datefmt="%H:%M:%S"
        "\033[32m[%(asctime)s]\033[0m %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    return logger


# Create and export logger instance
logger = setup_logger()
