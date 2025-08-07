"""Utilities for checking request cancellation status."""

import logging
from typing import Optional

from server.core.redis_connection import get_redis_client
from server.core.request_manager import RequestManager

logger = logging.getLogger(__name__)


def should_cancel(user_email: str, request_key: Optional[str] = None) -> bool:
    """
    Check if the current request should be cancelled.

    Args:
        user_email: The user's email address
        request_key: Optional specific request key to check. If not provided,
                     tries to get from current context.

    Returns:
        True if the request should be cancelled, False otherwise
    """
    redis_client = get_redis_client()
    if not redis_client:
        return False

    try:
        # If no request_key provided, try to get the active request for this user
        if not request_key:
            active_key = f"kindle:user:{user_email}:active_request"
            active_data = redis_client.get(active_key)
            if active_data:
                import json

                active_request = json.loads(active_data)
                request_key = active_request.get("request_key")
                logger.debug(f"Got request_key from active request: {request_key}")

        if not request_key:
            logger.debug(f"No request_key found for {user_email}")
            return False

        # Check the cancellation flag
        cancel_key = f"{request_key}:cancelled"
        is_cancelled = bool(redis_client.get(cancel_key))
        logger.debug(f"Checking cancellation for {cancel_key}: {is_cancelled}")

        if is_cancelled:
            import time

            logger.info(
                f"[{time.time():.3f}] CANCELLATION DETECTED: Request {request_key} has been cancelled for user {user_email}"
            )

        return is_cancelled

    except Exception as e:
        logger.error(f"Error checking cancellation status: {e}")
        return False


def mark_cancelled(user_email: str, request_key: Optional[str] = None) -> bool:
    """
    Mark a request as cancelled.

    Args:
        user_email: The user's email address
        request_key: Optional specific request key to cancel. If not provided,
                     cancels the active request for this user.

    Returns:
        True if successfully marked as cancelled, False otherwise
    """
    redis_client = get_redis_client()
    if not redis_client:
        return False

    try:
        # If no request_key provided, get the active request for this user
        if not request_key:
            active_key = f"kindle:user:{user_email}:active_request"
            active_data = redis_client.get(active_key)
            if active_data:
                import json

                active_request = json.loads(active_data)
                request_key = active_request.get("request_key")

        if not request_key:
            logger.warning(f"No active request found to cancel for user {user_email}")
            return False

        # Set the cancellation flag
        cancel_key = f"{request_key}:cancelled"
        redis_client.set(cancel_key, "1", ex=130)  # Same TTL as other request keys

        import time

        logger.info(
            f"[{time.time():.3f}] CANCELLATION SET: Marked request {request_key} as cancelled for user {user_email}"
        )
        return True

    except Exception as e:
        logger.error(f"Error marking request as cancelled: {e}")
        return False


def get_active_request_info(user_email: str) -> Optional[dict]:
    """
    Get information about the active request for a user.

    Args:
        user_email: The user's email address

    Returns:
        Dictionary with active request info, or None if no active request
    """
    redis_client = get_redis_client()
    if not redis_client:
        return None

    try:
        active_key = f"kindle:user:{user_email}:active_request"
        active_data = redis_client.get(active_key)

        if active_data:
            import json

            return json.loads(active_data)

        return None

    except Exception as e:
        logger.error(f"Error getting active request info: {e}")
        return None


class CancellationChecker:
    """
    Context manager for periodically checking cancellation during long operations.
    """

    def __init__(self, user_email: str, check_interval: int = 5):
        """
        Initialize the cancellation checker.

        Args:
            user_email: The user's email address
            check_interval: How often to check for cancellation (in iterations/operations)
        """
        self.user_email = user_email
        self.check_interval = check_interval
        self.counter = 0
        self.request_key = None

        # Try to get the current request key
        active_info = get_active_request_info(user_email)
        if active_info:
            self.request_key = active_info.get("request_key")

    def check(self) -> bool:
        """
        Check if the operation should be cancelled.
        This method can be called frequently and will only actually check
        Redis every check_interval calls.

        Returns:
            True if should cancel, False otherwise
        """
        self.counter += 1
        if self.counter % self.check_interval == 0:
            return should_cancel(self.user_email, self.request_key)
        return False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        return False
