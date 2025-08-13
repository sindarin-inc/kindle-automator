"""Middleware for request deduplication and cancellation."""

import functools
import logging
from typing import Any, Callable, Tuple

from flask import Response, g, request

from server.core.request_manager import RequestManager, WaitResult
from server.utils.ansi_colors import BOLD, BRIGHT_BLUE, RESET
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


def deduplicate_request(func: Callable) -> Callable:
    """
    Decorator to handle request deduplication.

    This decorator:
    1. Checks if an identical request is already in progress
    2. If so, waits for the result and returns it
    3. If not, executes the function and caches the result
    4. Handles cancellation for lower priority requests

    Args:
        func: The resource method to wrap

    Returns:
        Wrapped function with deduplication logic
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs) -> Tuple[Any, int]:
        # Get user email
        user_email = get_sindarin_email()
        if not user_email:
            # No email, can't deduplicate - just execute normally
            logger.debug("No user email found, skipping deduplication")
            return func(self, *args, **kwargs)

        # Get request path and method
        path = request.path if hasattr(request, "path") else "/"
        method = request.method if hasattr(request, "method") else "GET"

        logger.info(f"Deduplication middleware: Processing {method} {path} for {user_email}")

        # Create request manager
        manager = RequestManager(user_email, path, method)
        logger.info(f"Created RequestManager with key: {manager.request_key}")

        # Store request manager in Flask g context
        g.request_manager = manager

        # Check if request number was already assigned in before_request
        if hasattr(g, "request_number") and g.request_number:
            # Use the already-assigned number
            manager.request_number = g.request_number
        else:
            # Assign request number if not already done
            manager.request_number = manager._assign_request_number()
            if manager.request_number:
                g.request_number = manager.request_number
                manager._check_and_notify_multiple_requests()

        # Update the show_request_number flag based on current state
        if manager.redis_client:
            active_key = f"kindle:user:{user_email}:active_request_count"
            active_count = manager.redis_client.get(active_key)
            if active_count and int(active_count) > 1:
                g.show_request_number = True

        # Try to claim the request
        if manager.claim_request():
            # We own this request - execute it
            try:
                logger.info(
                    f"{BRIGHT_BLUE}Executing request {BOLD}{BRIGHT_BLUE}{manager.request_key}{RESET}{BRIGHT_BLUE} for {BOLD}{BRIGHT_BLUE}{user_email}{RESET}"
                )
                result = func(self, *args, **kwargs)

                # Handle different response types
                if isinstance(result, tuple) and len(result) == 2:
                    response_data, status_code = result
                elif isinstance(result, Response):
                    # Don't cache streaming responses
                    if result.direct_passthrough or result.is_streamed:
                        # For streaming responses, we still need to clean up the request number
                        # even though we don't cache the response
                        manager._cleanup_request_number()
                        return result
                    response_data = result.get_data(as_text=True)
                    status_code = result.status_code
                else:
                    response_data = result
                    status_code = 200

                # Store the response for waiting requests
                manager.store_response(response_data, status_code)

                return response_data, status_code

            except Exception as e:
                logger.error(f"Error executing request {manager.request_key}: {e}")

                # Check if this is a retryable UiAutomator2 crash
                error_message = str(e)
                is_retryable_crash = any(
                    [
                        "A session is either terminated or not started" in error_message,
                        "NoSuchDriverError" in error_message,
                        "InvalidSessionIdException" in error_message,
                        "instrumentation process is not running" in error_message,
                        "Could not proxy command to the remote server" in error_message,
                        "socket hang up" in error_message,
                    ]
                )

                # Only mark as error if it's NOT a retryable crash
                # Retryable crashes will be handled by the automator_middleware retry logic
                if not is_retryable_crash:
                    manager._mark_error()

                raise

        else:
            # Request couldn't be claimed - either duplicate or waiting for higher priority
            # IMPORTANT: We need to correctly determine WHY the claim failed
            # A duplicate request will have its progress key already set
            # A request waiting for higher priority won't have a progress key

            # Check if this exact request is already in progress (duplicate)
            if manager.is_duplicate_in_progress():
                logger.info(
                    f"{BRIGHT_BLUE}Waiting for deduplicated response for {BOLD}{BRIGHT_BLUE}{manager.request_key}{RESET}"
                )

                result = manager.wait_for_deduplicated_response()

                if result:
                    response_data, status_code = result
                    logger.info(f"Returning deduplicated response for {user_email}")
                    return response_data, status_code
                else:
                    # Timeout or error waiting - execute normally as fallback
                    logger.warning(
                        f"Failed to get deduplicated response, executing normally for {user_email}"
                    )
                    return func(self, *args, **kwargs)
            else:
                # Not a duplicate - must be waiting for higher priority request
                logger.info(
                    f"{BRIGHT_BLUE}Waiting for higher priority request to complete before executing {BOLD}{BRIGHT_BLUE}{path}{RESET}"
                )

                wait_result = manager.wait_for_higher_priority_completion()

                if wait_result == WaitResult.READY:
                    # Higher priority request finished, now try to execute
                    logger.info(
                        f"{BRIGHT_BLUE}Higher priority request completed, now executing {BOLD}{BRIGHT_BLUE}{path}{RESET}"
                    )
                    return func(self, *args, **kwargs)
                elif wait_result == WaitResult.CANCELLED:
                    # Log in blue to match the cancellation log
                    from server.utils.ansi_colors import BOLD, BRIGHT_BLUE, RESET

                    logger.info(
                        f"{BRIGHT_BLUE}Request {BOLD}{BRIGHT_BLUE}{manager.request_key}{RESET}{BRIGHT_BLUE} "
                        f"detected it was cancelled for user {BOLD}{BRIGHT_BLUE}{user_email}{RESET}"
                    )
                    # Clean up request number for cancelled requests
                    manager._cleanup_request_number()
                    return {"error": "Request was cancelled by higher priority operation"}, 409
                elif wait_result == WaitResult.TIMEOUT:
                    logger.warning(f"Request {path} timed out while waiting")
                    # Clean up request number for timed out requests
                    manager._cleanup_request_number()
                    return {"error": "Request timed out waiting for higher priority operation"}, 408
                else:  # WaitResult.ERROR
                    logger.error(f"Error occurred while {path} was waiting")
                    # Clean up request number for errored requests
                    manager._cleanup_request_number()
                    return {"error": "Error waiting for higher priority operation"}, 500

    return wrapper


def check_cancellation_periodically(func: Callable) -> Callable:
    """
    Decorator to periodically check for request cancellation during execution.

    This is meant for long-running operations that need to check if they should stop.

    Args:
        func: The function to wrap

    Returns:
        Wrapped function that checks for cancellation
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get user email from context
        user_email = get_sindarin_email()
        if not user_email:
            # No email, can't check cancellation
            return func(*args, **kwargs)

        # Pass the user_email to the function if it accepts it
        import inspect

        sig = inspect.signature(func)
        if "user_email" in sig.parameters:
            kwargs["user_email"] = user_email

        return func(*args, **kwargs)

    return wrapper
