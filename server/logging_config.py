import logging
import logging.config
import os
import sys
import threading
from datetime import datetime
from typing import Dict, Optional

import pytz

from server.utils.ansi_colors import (
    BLUE,
    BOLD,
    BRIGHT_CYAN,
    BRIGHT_YELLOW,
    CYAN,
    GRAY,
    GREEN,
    MAGENTA,
    RED,
    RESET,
    WHITE,
    YELLOW,
)

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

    logger.debug(f"Stored page source to {filepath}")
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

    # Create logs/email_logs directory if it doesn't exist
    os.makedirs("logs/email_logs", exist_ok=True)

    # Create a logger for this email
    email_logger = logging.getLogger(f"email.{email}")

    # Check if this logger already has handlers to avoid duplicates
    if not email_logger.handlers:
        # Create a file handler for this email
        log_file = f"logs/email_logs/{email}.log"
        file_handler = logging.FileHandler(log_file)

        # Use the same formatter as the main logger
        formatter = RelativePathFormatter(
            f"[%(levelname)5.5s] {GREEN}[%(asctime)s]{RESET} {YELLOW}%(pathname)22s:%(lineno)-4d{RESET} %(message)s",
            datefmt="%-m-%-d-%y %H:%M:%S %Z",
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

        # Create logs/email_logs directory if it doesn't exist
        os.makedirs("logs/email_logs", exist_ok=True)

        # Create a file handler for this email
        log_file = f"logs/email_logs/{email}.log"
        handler = logging.FileHandler(log_file)

        # Use the same formatter as the main handler
        if self.formatter:
            handler.setFormatter(self.formatter)

        # Cache the handler
        self.handler_cache[email] = handler

        return handler

    def set_email(self, email):
        """Set the email for the current thread (useful for non-request contexts)."""
        if hasattr(self._local, "email"):
            self._local.email = email
        else:
            self._local.email = email

    def clear_email(self):
        """Clear the email for the current thread."""
        if hasattr(self._local, "email"):
            delattr(self._local, "email")

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
            if hasattr(self._local, "email"):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pst_tz = pytz.timezone("US/Pacific")

        # Define log level colors
        self.level_colors = {
            logging.DEBUG: GRAY,
            logging.INFO: WHITE,  # White (no color code needed for default)
            logging.WARNING: BRIGHT_YELLOW,
            logging.ERROR: RED,
            logging.CRITICAL: RED,
        }

    def formatTime(self, record, datefmt=None):
        """Override formatTime to use PT timezone"""
        # Convert the timestamp to PT timezone
        ct = datetime.fromtimestamp(record.created, tz=pytz.UTC)
        ct = ct.astimezone(self.pst_tz)

        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%-m-%-d-%y %-H:%M:%S %Z")
        return s

    def format(self, record):
        # Check if this is a request manager log (from books_resources.py with timestamp pattern)
        is_request_manager_log = False
        if "books_resources.py" in record.pathname or "request_manager" in record.pathname:
            # Check if the message contains a unix timestamp pattern [1234567890.123]
            import re

            if re.search(r"\[\d{10}\.\d{3}\]", record.getMessage()):
                is_request_manager_log = True
                # Remove the unix timestamp from the message
                original_msg = record.getMessage()
                record.msg = re.sub(r"\[\d{10}\.\d{3}\]\s*", "", original_msg)
                record.args = ()  # Clear args since we modified the message

        # Get the project root directory (parent of server/server.py)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Make the pathname relative to project root
        if record.pathname.startswith(project_root):
            record.pathname = os.path.relpath(record.pathname, project_root)

        # Truncate long paths from the left, keeping the filename
        max_length = 22  # Half of the original 44 characters
        original_path = record.pathname

        if len(original_path) > max_length:
            # Find the last slash
            last_slash = original_path.rfind("/")
            if last_slash > 0:
                filename = original_path[last_slash + 1 :]
                # If filename itself is too long, just truncate it
                if len(filename) >= max_length - 3:  # -3 for "..."
                    truncated = "..." + filename[-(max_length - 3) :]
                else:
                    # Calculate how much of the path we can show
                    # We want: "..." + path_part + "/" + filename = exactly max_length
                    available_for_path = max_length - len(filename) - 4  # -4 for ".../"
                    if available_for_path > 0:
                        # Show some of the directory path
                        path_part = original_path[:last_slash]
                        truncated = "..." + path_part[-available_for_path:] + "/" + filename
                    else:
                        truncated = ".../" + filename

                # Ensure the truncated path is exactly max_length characters
                if len(truncated) > max_length:
                    # If still too long, just take the last max_length chars
                    record.pathname = "..." + truncated[-(max_length - 3) :]
                else:
                    record.pathname = truncated

        # Get the user email for the current request/context
        email = None
        request_number = None
        has_multiple_requests = False

        # Try Flask g.request_email (set in before_request)
        try:
            from flask import g

            if hasattr(g, "request_email"):
                email = g.request_email

            # Get request number from g context
            if hasattr(g, "request_number"):
                request_number = g.request_number
        except (ImportError, RuntimeError):
            # Not in Flask context
            pass

        # If no email from g, try to get from request utils
        if not email:
            try:
                from server.utils.request_utils import get_sindarin_email

                email = get_sindarin_email()
            except (ImportError, RuntimeError):
                pass

        # Get the formatted message from parent first
        formatted = super().format(record)

        # Insert the user email after file:line if we have one
        if email:
            import re

            # The format is: [LEVEL] [timestamp] filename:lineno message
            # We want to insert the email after the lineno and before the message
            # Look for pattern: file.py:123 (with optional ANSI codes)
            pattern = r"(.*\.py:\d+)(.*?\033\[0m)?(\s+)"
            match = re.search(pattern, formatted)
            if match:
                before_msg = match.group(1)  # file.py:123
                ansi_reset = match.group(2) or ""  # Optional ANSI reset
                spacing = match.group(3)  # Spacing before message
                after_msg = formatted[match.end() :]  # The rest (message)

                # Include request number if there are multiple requests
                if has_multiple_requests and request_number:
                    email_display = f"{email}[{request_number}]"
                else:
                    email_display = email

                # Insert [User: email] after file:line
                formatted = f"{before_msg}{ansi_reset} {GREEN}[{email_display}]{RESET}{spacing}{after_msg}"

        # Apply special formatting for request manager logs
        if is_request_manager_log:
            # For request manager logs, use BLUE as base color
            import re

            # First, apply BLUE to the entire message
            # Look for the message part after email or after filename:lineno
            if email:
                # Pattern with email: filename.py:123 [email][RESET] message
                # Need to handle both email and email[number] formats
                if has_multiple_requests and request_number:
                    email_pattern = rf"\[{re.escape(email)}\[{request_number}\]\].*?\033\[0m\s*"
                else:
                    email_pattern = rf"\[{re.escape(email)}\].*?\033\[0m\s*"
                match = re.search(email_pattern, formatted)
            else:
                # Pattern without email: filename.py:123[RESET] message
                match = re.search(r"(.*\.py:\d+.*?\033\[0m\s*)", formatted)

            if match:
                prefix = formatted[: match.end()]
                message = formatted[match.end() :]

                # Key status phrases to highlight in BOLD BLUE + CYAN
                important_patterns = [
                    r"(registered as active)",
                    r"(Starting state check)",
                    r"(Current state)",
                    r"(Starting new stream)",
                    r"(Creating streaming response)",
                    r"(Returning streaming response)",
                    r"(Starting generate_stream)",
                    r"(request key:)",
                    r"(Starting book retrieval)",
                    r"(Starting book stream)",
                    r"(Starting initial wait)",
                    r"(Updated current state)",
                    r"(AppState\.\w+)",  # Highlight state names
                    r"(merged|queued|deduplicating|cancelling|cancelled)",
                ]

                # Apply BLUE to entire message
                colored_message = f"{BLUE}{message}{RESET}"

                # Then highlight important parts with BOLD + CYAN
                for pattern in important_patterns:
                    colored_message = re.sub(pattern, f"{BOLD}{BRIGHT_CYAN}\\1{RESET}{BLUE}", colored_message)

                formatted = prefix + colored_message

            # Make the level indicator BLUE as well
            level_pattern = f"[{record.levelname:5.5s}]"
            colored_level = f"{BLUE}[{record.levelname:5.5s}]{RESET}"
            formatted = formatted.replace(level_pattern, colored_level, 1)

            return formatted

        # Get the color for this level
        level_color = self.level_colors.get(record.levelno, "")

        if level_color and level_color != WHITE:
            # Apply color to both the level name and the message
            # The format is: [LEVEL] [timestamp] filename:lineno [email] message

            # Color the level name in brackets
            level_pattern = f"[{record.levelname:5.5s}]"
            colored_level = f"{level_color}[{record.levelname:5.5s}]{RESET}"
            formatted = formatted.replace(level_pattern, colored_level, 1)

            # Also color the message part (after email if present, or after filename:lineno)
            import re

            # Look for the pattern that includes the email in brackets
            if email:
                # Pattern with email: filename.py:123 [email][RESET] message
                # Need to handle both email and email[number] formats
                if has_multiple_requests and request_number:
                    email_pattern = rf"\[{re.escape(email)}\[{request_number}\]\].*?\033\[0m\s*"
                else:
                    email_pattern = rf"\[{re.escape(email)}\].*?\033\[0m\s*"
                match = re.search(email_pattern, formatted)
            else:
                # Pattern without email: filename.py:123[RESET] message
                match = re.search(r"(.*\.py:\d+.*?\033\[0m\s*)", formatted)

            if match:
                # Split at the boundary
                prefix = formatted[: match.end()]
                message = formatted[match.end() :]

                # Check if the message already contains ANSI codes (like SQL logs)
                if "\033[" in message:
                    # Message already has colors, don't add level color
                    formatted = prefix + message
                else:
                    # Apply color to the message part
                    formatted = prefix + level_color + message + RESET
            else:
                # Fallback: try without ANSI codes
                if email:
                    # Need to handle both email and email[number] formats
                    if has_multiple_requests and request_number:
                        email_pattern = rf"\[{re.escape(email)}\[{request_number}\]\]\s+"
                    else:
                        email_pattern = rf"\[{re.escape(email)}\]\s+"
                    match = re.search(email_pattern, formatted)
                else:
                    match = re.search(r"(.*\.py:\d+\s+)", formatted)

                if match:
                    prefix_len = match.end()
                    prefix = formatted[:prefix_len]
                    message = formatted[prefix_len:]

                    # Check if the message already contains ANSI codes
                    if "\033[" in message:
                        # Message already has colors, don't add level color
                        formatted = prefix + message
                    else:
                        formatted = prefix + level_color + message + RESET

        return formatted


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


def get_idle_timer_handler():
    """Get a file handler for idle timer logs.

    Creates a dedicated file handler that writes to logs/idle_timer.log
    for tracking idle timer shutdown activity.

    Returns:
        logging.FileHandler: A file handler for idle timer logging
    """
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Create a file handler for idle timer logs
    log_file = "logs/idle_timer.log"
    file_handler = logging.FileHandler(log_file)

    # Use the same formatter as the main logger
    formatter = RelativePathFormatter(
        f"[%(levelname)5.5s] {GREEN}[%(asctime)s]{RESET} {YELLOW}%(pathname)22s:%(lineno)-4d{RESET} %(message)s",
        datefmt="%-m-%-d-%y %H:%M:%S %Z",
    )
    file_handler.setFormatter(formatter)

    # Add the custom filter
    file_handler.addFilter(CustomFilter())

    # Set the level to DEBUG to capture all relevant logs
    file_handler.setLevel(logging.DEBUG)

    return file_handler


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


class IdleTimerContext:
    """Context manager for idle timer logging that tees logs to both server.log and idle_timer.log."""

    def __init__(self, logger_name=None):
        self.logger_name = logger_name or __name__
        self.idle_handler = None
        self.logger = None

    def __enter__(self):
        # Get the logger
        self.logger = logging.getLogger(self.logger_name)

        # Create and add the idle timer handler
        self.idle_handler = get_idle_timer_handler()
        self.logger.addHandler(self.idle_handler)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Remove the idle timer handler
        if self.idle_handler and self.logger:
            self.logger.removeHandler(self.idle_handler)
            self.idle_handler.close()
        return False


def setup_logger():
    """Configure logging with timestamps including minutes, seconds, and milliseconds"""
    global _email_handler

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Clear the log files
    server_log_file = "logs/server.log"
    debug_log_file = "logs/debug_server.log"

    with open(server_log_file, "w") as f:
        f.truncate(0)
    with open(debug_log_file, "w") as f:
        f.truncate(0)

    # Create formatter - check if we should strip colors from console output
    if os.environ.get("NO_COLOR_CONSOLE"):
        console_formatter = RelativePathFormatter(
            "[%(levelname)5.5s] [%(asctime)s] %(pathname)22s:%(lineno)-4d %(message)s",
            datefmt="%-m-%-d-%y %H:%M:%S %Z",
        )
    else:
        console_formatter = RelativePathFormatter(
            f"[%(levelname)5.5s] {GREEN}[%(asctime)s]{RESET} {YELLOW}%(pathname)22s:%(lineno)-4d{RESET} %(message)s",
            datefmt="%-m-%-d-%y %H:%M:%S %Z",
        )

    # File formatters always have colors
    file_formatter = RelativePathFormatter(
        f"[%(levelname)5.5s] {GREEN}[%(asctime)s]{RESET} {YELLOW}%(pathname)22s:%(lineno)-4d{RESET} %(message)s",
        datefmt="%-m-%-d-%y %H:%M:%S %Z",
    )

    # Create the custom filter
    custom_filter = CustomFilter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler with color formatter (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(custom_filter)
    root_logger.addHandler(console_handler)

    # Add file handler for main server.log (INFO level)
    server_file_handler = logging.FileHandler(server_log_file)
    server_file_handler.setLevel(logging.INFO)
    server_file_handler.setFormatter(file_formatter)
    server_file_handler.addFilter(custom_filter)
    root_logger.addHandler(server_file_handler)

    # Add file handler for debug_server.log (DEBUG level)
    debug_file_handler = logging.FileHandler(debug_log_file)
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(file_formatter)
    debug_file_handler.addFilter(custom_filter)
    root_logger.addHandler(debug_file_handler)

    # Add dynamic email handler for user-specific logs with no-color formatter
    _email_handler = DynamicEmailHandler()
    _email_handler.setLevel(logging.DEBUG)
    _email_handler.setFormatter(file_formatter)
    _email_handler.addFilter(custom_filter)
    root_logger.addHandler(_email_handler)

    # Configure external libraries to use higher log level
    for lib_name in ["selenium", "urllib3", "PIL", "appium", "werkzeug"]:
        lib_logger = logging.getLogger(lib_name)
        lib_logger.setLevel(logging.INFO)

    # Disable Werkzeug's access logs (the "GET /path HTTP/1.1 200" logs)
    # since we have our own request logging
    werkzeug_logger = logging.getLogger("werkzeug._internal")
    werkzeug_logger.setLevel(logging.WARNING)

    # Configure SQL and Redis command loggers to only write to debug_server.log
    # These loggers don't propagate to avoid showing in email logs
    sql_logger = logging.getLogger("sql_commands")
    sql_logger.setLevel(logging.DEBUG)
    sql_logger.propagate = False  # Don't propagate to root logger (prevents email logs)
    sql_logger.addHandler(debug_file_handler)  # Only add to debug file handler

    redis_logger = logging.getLogger("redis_commands")
    redis_logger.setLevel(logging.DEBUG)
    redis_logger.propagate = False  # Don't propagate to root logger (prevents email logs)
    redis_logger.addHandler(debug_file_handler)  # Only add to debug file handler

    # Log that we've set up the email-specific logging
    logger.info(
        "Direct email-specific logging configured - all logs will be directed to both global and user-specific log files based on request context"
    )
