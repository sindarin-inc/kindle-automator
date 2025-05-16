import logging
import logging.config
import os
import sys
import threading
from typing import Dict, Optional

# Remove circular import - DynamicEmailHandler will get email from flask.g only

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


def get_email_logger(email: str) -> Optional[logging.Logger]:
    """Get a logger specific to the provided email address.

    Creates a file handler that writes logs to logs/<email>.log
    while maintaining the existing logging configuration. This allows
    for per-user logging that can be useful for debugging issues with
    specific user profiles.

    This function:
    1. Creates a logger with a namespace of "email.<email>"
    2. Adds a file handler that writes to logs/<email>.log
    3. Uses the same formatting as the main logger
    4. Propagates logs to the root logger (so they also appear in the main log)

    Usage:
        email_logger = get_email_logger("user@example.com")
        email_logger.info("This will be logged to both logs/user@example.com.log and logs/server.log")

    Args:
        email: The email address to create a logger for

    Returns:
        A logger instance configured for the specific email, or None if email is empty
    """
    if not email:
        return None

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Create a logger for this email
    email_logger = logging.getLogger(f"email.{email}")

    # Check if this logger already has handlers to avoid duplicates
    if not email_logger.handlers:
        # Create a file handler for this email
        log_file = f"logs/{email}.log"
        file_handler = logging.FileHandler(log_file)

        # Use the same formatter as the main logger
        formatter = RelativePathFormatter(
            "\033[35m[%(levelname)5.5s]\033[0m \033[32m[%(asctime)s]\033[0m \033[33m%(pathname)44s:%(lineno)-4d\033[0m %(message)s",
            datefmt="%H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        # Add the custom filter
        file_handler.addFilter(CustomFilter())

        # Set the level to DEBUG to capture all relevant logs
        file_handler.setLevel(logging.DEBUG)

        # Add the handler to the logger
        email_logger.addHandler(file_handler)

        # Set propagate to True so logs also go to the root logger
        email_logger.propagate = True

        logger.info(f"Created email-specific logger for {email} writing to {log_file}")

    return email_logger


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


class DynamicEmailHandler(logging.Handler):
    """
    A handler that routes logs to email-specific log files based on the current request.

    This handler tries to get the email from:
    1. Flask g.request_email (set in before_request)
    2. Thread-local storage (for non-request contexts)
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.handler_cache = {}  # Cache of email -> handler
        self.formatter = None
        self._local = threading.local()  # Thread-local storage for email

    def setFormatter(self, formatter):
        """Set the formatter for this handler and all email-specific handlers."""
        self.formatter = formatter
        # Also set formatter for all cached handlers
        for handler in self.handler_cache.values():
            handler.setFormatter(formatter)
        super().setFormatter(formatter)

    def get_handler_for_email(self, email):
        """Get or create a file handler for the specified email."""
        if not email:
            return None

        # Check if we already have a handler for this email
        if email in self.handler_cache:
            return self.handler_cache[email]

        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)

        # Create a file handler for this email
        log_file = f"logs/{email}.log"
        handler = logging.FileHandler(log_file)

        # Use the same formatter as the main handler
        if self.formatter:
            handler.setFormatter(self.formatter)

        # Cache the handler
        self.handler_cache[email] = handler

        return handler

    def set_email(self, email):
        """Set the email for the current thread (useful for non-request contexts)."""
        if hasattr(self._local, 'email'):
            self._local.email = email
        else:
            self._local.email = email

    def clear_email(self):
        """Clear the email for the current thread."""
        if hasattr(self._local, 'email'):
            delattr(self._local, 'email')

    def emit(self, record):
        """Emit the log record to the appropriate log file based on the current request email."""
        email = None
        
        # Only try Flask g.request_email (set in before_request)
        try:
            from flask import g
            if hasattr(g, "request_email"):
                email = g.request_email
        except (ImportError, RuntimeError):
            # Not in Flask context - check thread-local only for background threads
            if hasattr(self._local, 'email'):
                email = self._local.email

        if email:
            # Get a handler for this email
            handler = self.get_handler_for_email(email)

            if handler:
                # Emit the record to the email-specific handler
                handler.emit(record)


# Removed RequestEmailContextFilter - no longer needed


class RelativePathFormatter(logging.Formatter):
    """Format the pathname to be relative to the project root."""

    def format(self, record):
        # Get the project root directory (parent of server/server.py)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Make the pathname relative to project root
        if record.pathname.startswith(project_root):
            record.pathname = os.path.relpath(record.pathname, project_root)

        return super().format(record)


# Global reference to the dynamic email handler
_email_handler = None

def get_email_handler():
    """Get the global email handler instance."""
    return _email_handler

def set_email_context(email):
    """Set the email context for the current thread (useful for background tasks)."""
    if _email_handler:
        _email_handler.set_email(email)

def clear_email_context():
    """Clear the email context for the current thread."""
    if _email_handler:
        _email_handler.clear_email()

class EmailContext:
    """Context manager for setting email context for logging."""
    
    def __init__(self, email):
        self.email = email
    
    def __enter__(self):
        if self.email:
            set_email_context(self.email)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        clear_email_context()
        return False

def setup_logger():
    """Configure logging with timestamps including minutes, seconds, and milliseconds"""
    global _email_handler
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Clear the log file
    log_file = "logs/server.log"
    with open(log_file, "w") as f:
        f.truncate(0)

    # Create the formatter
    formatter = RelativePathFormatter(
        "\033[35m[%(levelname)5.5s]\033[0m \033[32m[%(asctime)s]\033[0m \033[33m%(pathname)44s:%(lineno)-4d\033[0m %(message)s",
        datefmt="%H:%M:%S",
    )

    # Create the custom filter
    custom_filter = CustomFilter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(custom_filter)
    root_logger.addHandler(console_handler)

    # Add file handler for main log
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(custom_filter)
    root_logger.addHandler(file_handler)

    # Add dynamic email handler for user-specific logs
    _email_handler = DynamicEmailHandler()
    _email_handler.setLevel(logging.DEBUG)
    _email_handler.setFormatter(formatter)
    _email_handler.addFilter(custom_filter)
    root_logger.addHandler(_email_handler)

    # Configure external libraries to use higher log level
    for lib_name in ["selenium", "urllib3", "PIL", "appium", "werkzeug"]:
        lib_logger = logging.getLogger(lib_name)
        lib_logger.setLevel(logging.INFO)

    # Log that we've set up the email-specific logging
    logger.info(
        "Direct email-specific logging configured - all logs will be directed to both global and user-specific log files based on request context"
    )
