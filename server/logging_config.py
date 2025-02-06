import logging
import logging.config
import os
import sys

logger = logging.getLogger(__name__)


def store_page_source(source: str, prefix: str = "unknown", directory: str = "fixtures/dumps") -> str:
    """Store page source XML in the fixtures directory with timestamp.

    Args:
        source: The page source XML to store
        prefix: A prefix to identify the type of dump (e.g. 'failed_transition', 'unknown_view')
        directory: The directory to store dumps in

    Returns:
        str: Path to the stored file
    """
    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Generate filename with timestamp
    filename = f"{prefix}.xml"
    filepath = os.path.join(directory, filename)

    # Store the XML
    with open(filepath, "w") as f:
        f.write(source)

    logger.info(f"Stored page source to {filepath}")
    return filepath


class CustomFilter(logging.Filter):
    """Filter out DEBUG messages from external libraries and selenium logs below INFO."""

    def filter(self, record):
        # Filter out DEBUG messages from site-packages
        if record.levelno == logging.DEBUG and "site-packages" in record.pathname:
            return False
        # Filter out selenium logs below INFO
        if "selenium" in record.pathname and record.levelno < logging.INFO:
            return False
        return True


class RelativePathFormatter(logging.Formatter):
    """Format the pathname to be relative to the project root."""

    def format(self, record):
        # Get the project root directory (parent of server/server.py)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Make the pathname relative to project root
        if record.pathname.startswith(project_root):
            record.pathname = os.path.relpath(record.pathname, project_root)

        return super().format(record)


def setup_logger():
    """Configure logging with timestamps including minutes, seconds, and milliseconds"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Clear the log file
    log_file = "logs/server.log"
    with open(log_file, "w") as f:
        f.truncate(0)

    # Configure logging using dictConfig
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "colored": {
                    "()": RelativePathFormatter,
                    "format": "\033[35m[%(levelname)5.5s]\033[0m \033[32m[%(asctime)s]\033[0m \033[33m%(pathname)27s:%(lineno)-4d\033[0m %(message)s",
                    "datefmt": "%H:%M:%S",
                },
            },
            "filters": {
                "custom_filter": {
                    "()": CustomFilter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": "colored",
                    "filters": ["custom_filter"],
                    "level": "DEBUG",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "filename": log_file,
                    "formatter": "colored",
                    "filters": ["custom_filter"],
                    "level": "DEBUG",
                },
            },
            "loggers": {
                # Root logger
                "": {
                    "handlers": ["console", "file"],
                    "level": "DEBUG",
                    "propagate": True,
                },
                # External libraries
                "selenium": {
                    "level": "INFO",
                    "propagate": True,
                },
                "urllib3": {
                    "level": "INFO",
                    "propagate": True,
                },
                "PIL": {
                    "level": "INFO",
                    "propagate": True,
                },
                "appium": {
                    "level": "INFO",
                    "propagate": True,
                },
                "werkzeug": {
                    "level": "INFO",
                    "propagate": True,
                },
            },
        }
    )
