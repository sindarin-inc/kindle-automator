"""Request manager for deduplication and cancellation of Kindle requests."""

import hashlib
import json
import logging
import pickle
import time
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from flask import Response, request

from server.core.redis_connection import get_redis_client

logger = logging.getLogger(__name__)


class WaitResult(Enum):
    """Result of waiting for a higher priority request."""

    READY = "ready"  # Can proceed with execution
    CANCELLED = "cancelled"  # Request was cancelled while waiting
    TIMEOUT = "timeout"  # Timed out waiting
    ERROR = "error"  # Error occurred while waiting


class DeduplicationStatus(Enum):
    """Status of a deduplicated request."""

    COMPLETED = "completed"  # Request completed successfully
    ERROR = "error"  # Request encountered an error
    IN_PROGRESS = "in_progress"  # Request is still being processed


# Request priority levels (higher number = higher priority)
PRIORITY_LEVELS = {
    "/open-book": 100,  # Highest - user wants to read
    "/open-random-book": 100,
    "/close-book": 90,
    "/navigate": 50,
    "/state": 40,  # Medium - quick state check
    "/books": 30,  # Low - library scanning
    "/books-stream": 30,
    "/auth": 20,
    "/screenshot": 10,  # Lowest
}

# Endpoints where newer requests should cancel older ones (last-one-wins)
LAST_ONE_WINS_ENDPOINTS = {
    "/open-random-book",  # User wants the most recent random book choice
}

# Default TTL for cached responses and locks
DEFAULT_TTL = 130  # seconds
MAX_WAIT_TIME = 125  # seconds


class RequestManager:
    """Manages request deduplication and cancellation using Redis."""

    def __init__(self, user_email: str, path: str, method: str = "GET"):
        self.user_email = user_email
        self.path = path
        self.method = method.upper()
        self.redis_client = get_redis_client()
        self.request_key = self._generate_request_key()
        self.priority = PRIORITY_LEVELS.get(path, 0)

    def _generate_request_key(self) -> str:
        """Generate a unique key for this request based on user, path, method, and params."""
        # For last-one-wins endpoints, add timestamp to make each request unique
        if self.path in LAST_ONE_WINS_ENDPOINTS:
            import time

            signature = f"{self.user_email}:{self.path}:{self.method}:{time.time()}"
            request_hash = hashlib.md5(signature.encode()).hexdigest()
            return f"kindle:request:{request_hash}"

        # Get query parameters, excluding certain ones
        params = {}
        try:
            from flask import has_request_context

            if has_request_context() and hasattr(request, "args"):
                params = dict(request.args)
        except Exception:
            pass

        excluded_params = {"staging", "_t", "timestamp", "cache_buster"}
        filtered_params = {k: v for k, v in params.items() if k not in excluded_params}

        # Sort params for consistent hashing
        sorted_params = json.dumps(filtered_params, sort_keys=True)

        # Create a hash of the request signature
        signature = f"{self.user_email}:{self.path}:{self.method}:{sorted_params}"
        request_hash = hashlib.md5(signature.encode()).hexdigest()

        return f"kindle:request:{request_hash}"

    def should_deduplicate(self) -> bool:
        """Check if this request type should be deduplicated."""
        # Only deduplicate GET and POST requests
        if self.method not in ["GET", "POST"]:
            return False

        # Skip deduplication for certain paths
        skip_paths = ["/staff-auth", "/staff-tokens"]
        if any(self.path.startswith(skip) for skip in skip_paths):
            return False

        return True

    def claim_request(self) -> bool:
        """Try to claim this request. Returns True if we should execute it."""
        if not self.redis_client or not self.should_deduplicate():
            return True

        progress_key = f"{self.request_key}:progress"

        try:
            # For last-one-wins endpoints, always try to claim and cancel previous
            if self.path in LAST_ONE_WINS_ENDPOINTS:
                # Cancel any existing request for this endpoint
                self._cancel_existing_same_endpoint_request()

                # Force claim this request (overwrite any existing)
                self.redis_client.set(progress_key, DeduplicationStatus.IN_PROGRESS.value, ex=DEFAULT_TTL)
                logger.info(f"Claimed request {self.request_key} for {self.user_email} (last-one-wins)")

                # Record this as the active request for the user
                self._set_active_request()
                return True

            # Check if there's a higher priority request already running
            if self._should_wait_for_higher_priority():
                logger.info(
                    f"Request {self.request_key} (priority {self.priority}) waiting for higher priority request"
                )
                return False  # Will trigger wait logic in middleware

            # Normal deduplication logic
            # Try to atomically set the progress key
            if self.redis_client.set(
                progress_key, DeduplicationStatus.IN_PROGRESS.value, nx=True, ex=DEFAULT_TTL
            ):
                logger.info(f"Claimed request {self.request_key} for {self.user_email}")

                # Check for lower priority active requests and cancel them
                self._check_and_cancel_lower_priority_requests()

                # Record this as the active request for the user
                self._set_active_request()

                return True
            else:
                logger.info(f"Request {self.request_key} already in progress, will wait for result")
                return False

        except Exception as e:
            logger.error(f"Error claiming request: {e}")
            return True  # Fall back to executing on Redis errors

    def _should_wait_for_higher_priority(self) -> bool:
        """Check if there's a higher priority request running that we should wait for."""
        if not self.redis_client:
            return False

        try:
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = self.redis_client.get(active_key)

            if active_data:
                active_request = json.loads(active_data)
                active_priority = active_request.get("priority", 0)

                # If there's a higher priority request running, we should wait
                if active_priority > self.priority:
                    logger.info(
                        f"Higher priority request (priority {active_priority}) is running, "
                        f"lower priority {self.path} (priority {self.priority}) will wait"
                    )
                    return True

        except Exception as e:
            logger.error(f"Error checking for higher priority requests: {e}")

        return False

    def _cancel_existing_same_endpoint_request(self):
        """Cancel any existing request for the same endpoint (for last-one-wins logic)."""
        if not self.redis_client:
            return

        try:
            # Get the active request for this user
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = self.redis_client.get(active_key)

            if active_data:
                active_request = json.loads(active_data)
                active_path = active_request.get("path")

                # If it's the same endpoint, cancel it
                if active_path == self.path:
                    active_request_key = active_request.get("request_key")
                    if active_request_key and active_request_key != self.request_key:
                        cancel_key = f"{active_request_key}:cancelled"
                        self.redis_client.set(cancel_key, "1", ex=DEFAULT_TTL)
                        logger.info(
                            f"Cancelling previous {self.path} request {active_request_key} "
                            f"for newer request {self.request_key} (last-one-wins)"
                        )

        except Exception as e:
            logger.error(f"Error cancelling existing same-endpoint request: {e}")

    def _check_and_cancel_lower_priority_requests(self):
        """Check for and cancel any lower priority requests for this user."""
        if not self.redis_client:
            return

        try:
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = self.redis_client.get(active_key)

            if active_data:
                active_request = json.loads(active_data)
                active_priority = active_request.get("priority", 0)

                # If our priority is higher, cancel the active request
                if self.priority > active_priority:
                    active_request_key = active_request.get("request_key")
                    if active_request_key:
                        cancel_key = f"{active_request_key}:cancelled"
                        self.redis_client.set(cancel_key, "1", ex=DEFAULT_TTL)
                        logger.info(
                            f"Cancelling lower priority request {active_request_key} "
                            f"(priority {active_priority}) for higher priority {self.path} "
                            f"(priority {self.priority})"
                        )

        except Exception as e:
            logger.error(f"Error checking for lower priority requests: {e}")

    def _set_active_request(self):
        """Record this as the active request for the user."""
        if not self.redis_client:
            return

        try:
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = {
                "request_key": self.request_key,
                "priority": self.priority,
                "path": self.path,
                "started_at": time.time(),
            }
            self.redis_client.set(active_key, json.dumps(active_data), ex=DEFAULT_TTL)

        except Exception as e:
            logger.error(f"Error setting active request: {e}")

    def wait_for_deduplicated_response(self) -> Optional[Tuple[Any, int]]:
        """Wait for a deduplicated response from another request."""
        if not self.redis_client:
            return None

        result_key = f"{self.request_key}:result"
        status_key = f"{self.request_key}:status"
        waiters_key = f"{self.request_key}:waiters"

        # Increment waiter count
        try:
            self.redis_client.incr(waiters_key)
        except Exception:
            pass

        start_time = time.time()
        poll_interval = 0.5  # Start with 500ms polling

        while (time.time() - start_time) < MAX_WAIT_TIME:
            try:
                # Check if request completed
                status = self.redis_client.get(status_key)
                if status:
                    status = status.decode("utf-8") if isinstance(status, bytes) else status

                    if status == DeduplicationStatus.COMPLETED.value:
                        # Get the cached result
                        result_data = self.redis_client.get(result_key)
                        if result_data:
                            result = pickle.loads(result_data)
                            logger.info(f"Retrieved deduplicated response for {self.request_key}")

                            # Cleanup if we're the last waiter
                            self._cleanup_if_last_waiter()

                            return result

                    elif status == DeduplicationStatus.ERROR.value:
                        logger.warning(f"Original request failed for {self.request_key}")
                        self._cleanup_if_last_waiter()
                        return None

            except Exception as e:
                logger.error(f"Error waiting for deduplicated response: {e}")

            # Adaptive polling - increase interval over time
            time.sleep(min(poll_interval, 2.0))
            if poll_interval < 2.0:
                poll_interval *= 1.5

        logger.warning(f"Timeout waiting for deduplicated response for {self.request_key}")
        self._cleanup_if_last_waiter()
        return None

    def store_response(self, response_data: Any, status_code: int):
        """Store the response in Redis for other waiting requests."""
        if not self.redis_client or not self.should_deduplicate():
            return

        try:
            result_key = f"{self.request_key}:result"
            status_key = f"{self.request_key}:status"
            waiters_key = f"{self.request_key}:waiters"

            # Check if there are any waiters
            waiters_count = self.redis_client.get(waiters_key)
            has_waiters = waiters_count and int(waiters_count) > 0

            if has_waiters:
                # There are waiters, store the response for them with a short TTL
                # 10 seconds should be enough for waiters to retrieve it
                short_ttl = 10
                
                # Pickle the response data
                pickled_data = pickle.dumps((response_data, status_code))

                # Store the result and status with short TTL
                self.redis_client.set(result_key, pickled_data, ex=short_ttl)
                self.redis_client.set(status_key, DeduplicationStatus.COMPLETED.value, ex=short_ttl)

                logger.info(f"Stored response for {self.request_key} with {short_ttl}s TTL for {waiters_count} waiters")
            else:
                # No waiters, just mark as completed and clean up immediately
                self.redis_client.set(status_key, DeduplicationStatus.COMPLETED.value, ex=2)
                logger.info(f"No waiters for {self.request_key}, marked as completed and will clean up")
                
                # Clean up immediately since there are no waiters
                keys_to_delete = [
                    f"{self.request_key}:progress",
                    f"{self.request_key}:cancelled",
                ]
                self.redis_client.delete(*keys_to_delete)

            # Clear active request if it's ours
            self._clear_active_request()

        except Exception as e:
            logger.error(f"Error storing response: {e}")
            self._mark_error()

    def _mark_error(self):
        """Mark the request as failed."""
        if not self.redis_client:
            return

        try:
            status_key = f"{self.request_key}:status"
            self.redis_client.set(status_key, DeduplicationStatus.ERROR.value, ex=DEFAULT_TTL)

            # Clear active request
            self._clear_active_request()

        except Exception as e:
            logger.error(f"Error marking request as failed: {e}")

    def _clear_active_request(self):
        """Clear the active request for this user if it's ours."""
        if not self.redis_client:
            return

        try:
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = self.redis_client.get(active_key)

            if active_data:
                active_request = json.loads(active_data)
                if active_request.get("request_key") == self.request_key:
                    self.redis_client.delete(active_key)

        except Exception as e:
            logger.error(f"Error clearing active request: {e}")

    def _cleanup_if_last_waiter(self):
        """Clean up Redis keys if we're the last waiter."""
        if not self.redis_client:
            return

        try:
            waiters_key = f"{self.request_key}:waiters"

            # Decrement and check if we're the last
            remaining = self.redis_client.decr(waiters_key)
            if remaining <= 0:
                # Clean up all keys for this request
                keys_to_delete = [
                    f"{self.request_key}:progress",
                    f"{self.request_key}:result",
                    f"{self.request_key}:status",
                    f"{self.request_key}:waiters",
                    f"{self.request_key}:cancelled",
                ]
                self.redis_client.delete(*keys_to_delete)
                logger.info(f"Cleaned up Redis keys for {self.request_key}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def is_cancelled(self) -> bool:
        """Check if this request has been cancelled by a higher priority request."""
        if not self.redis_client:
            return False

        try:
            cancel_key = f"{self.request_key}:cancelled"
            return bool(self.redis_client.get(cancel_key))

        except Exception as e:
            logger.error(f"Error checking cancellation status: {e}")
            return False

    def is_duplicate_in_progress(self) -> bool:
        """Check if this exact request is already in progress (duplicate)."""
        if not self.redis_client:
            return False

        try:
            progress_key = f"{self.request_key}:progress"
            return bool(self.redis_client.get(progress_key))

        except Exception as e:
            logger.error(f"Error checking duplicate status: {e}")
            return False

    def wait_for_higher_priority_completion(self) -> WaitResult:
        """Wait for a higher priority request to complete before proceeding."""
        if not self.redis_client:
            return WaitResult.ERROR

        start_time = time.time()
        poll_interval = 0.5

        while (time.time() - start_time) < MAX_WAIT_TIME:
            try:
                # Check if we've been cancelled
                if self.is_cancelled():
                    logger.info(f"Request {self.request_key} was cancelled while waiting")
                    return WaitResult.CANCELLED

                # Check if higher priority request is still running
                active_key = f"kindle:user:{self.user_email}:active_request"
                active_data = self.redis_client.get(active_key)

                if not active_data:
                    # No active request, we can proceed
                    logger.info(f"No active request found, {self.request_key} can proceed")
                    return WaitResult.READY

                active_request = json.loads(active_data)
                active_priority = active_request.get("priority", 0)

                if active_priority <= self.priority:
                    # Higher priority request finished, we can proceed
                    logger.info(f"Higher priority request completed, {self.request_key} can proceed")
                    return WaitResult.READY

                # Still waiting
                logger.debug(
                    f"Request {self.request_key} still waiting for priority {active_priority} request"
                )

            except Exception as e:
                logger.error(f"Error waiting for higher priority completion: {e}")
                return WaitResult.ERROR

            # Adaptive polling
            time.sleep(min(poll_interval, 2.0))
            if poll_interval < 2.0:
                poll_interval *= 1.5

        logger.warning(f"Timeout waiting for higher priority request for {self.request_key}")
        return WaitResult.TIMEOUT

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - handle errors."""
        if exc_type is not None:
            self._mark_error()
        return False
