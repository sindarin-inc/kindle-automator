"""Utilities for handling Appium-related errors."""

import logging

from selenium.common import exceptions as selenium_exceptions

logger = logging.getLogger(__name__)


def is_appium_error(exception):
    """Check if an exception is related to Appium/WebDriver issues that should trigger a retry.

    Args:
        exception: The exception to check

    Returns:
        bool: True if this is an Appium-related error that should be retried
    """
    error_message = str(exception)

    # Check for specific exception types
    if isinstance(
        exception, (selenium_exceptions.WebDriverException, selenium_exceptions.NoSuchDriverException)
    ):
        return True

    # Check for specific error messages that indicate Appium/driver issues
    appium_error_patterns = [
        "cannot be proxied to UiAutomator2 server because the instrumentation process is not running",
        "instrumentation process is not running",
        "Failed to establish a new connection",
        "Connection refused",
        "Connection reset by peer",
        "A session is either terminated or not started",
        "NoSuchDriverError",
        "InvalidSessionIdException",
        "Could not proxy command to the remote server",
        "socket hang up",
        "NoSuchContextException",
        "InvalidContextError",
        "The session identified by",
        "is not known",
    ]

    return any(pattern in error_message for pattern in appium_error_patterns)


def handle_driver_operation(operation_name, func, *args, **kwargs):
    """Execute a driver operation and re-raise Appium errors.

    Args:
        operation_name: Name of the operation for logging
        func: The function to execute
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The result of the function

    Raises:
        Any Appium-related exceptions are re-raised
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if is_appium_error(e):
            logger.debug(f"Appium error in {operation_name}, re-raising: {str(e)}")
            raise
        else:
            # Handle non-Appium errors normally
            logger.error(f"Non-Appium error in {operation_name}: {str(e)}")
            raise
