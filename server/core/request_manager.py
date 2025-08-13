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
from server.utils.ansi_colors import (
    BOLD,
    BRIGHT_BLUE,
    BRIGHT_GREEN,
    BRIGHT_RED,
    BRIGHT_YELLOW,
    RESET,
    style_text,
)

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
    "/shutdown": 200,  # Highest - system shutdown, must not be blocked
    "/open-book": 100,  # High - user wants to read
    "/open-random-book": 100,
    "/close-book": 90,
    "/navigate": 50,
    "/state": 40,  # Medium - quick state check
    "/books": 30,  # Low - library scanning
    "/books-stream": 30,
    "/auth": 20,
    # "/screenshot" is excluded - it can run concurrently without priority blocking
}

# Endpoints where newer requests should cancel older ones (last-one-wins)
# NOTE: This is now handled dynamically based on parameter differences
LAST_ONE_WINS_ENDPOINTS = {
    # Keeping empty for now as the logic is handled by parameter comparison
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
        self.request_number = None  # Will be assigned when claimed or waiting
        self.is_executor = False  # Track if this request is actually executing
        # Unique instance ID to track if THIS specific instance incremented counters
        import uuid

        self.instance_id = str(uuid.uuid4())

        logger.debug(
            f"RequestManager initialized for {self.user_email} on {self.path} with method {self.method} with instance ID {self.instance_id}"
        )

    def _generate_request_key(self) -> str:
        """Generate a unique key for this request based on user, path, method, and params."""
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

        # Create a hash of the request signature - always include params
        # This ensures same params = same key (deduplicate), different params = different key
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

        logger.info(f"Attempting to claim request {self.request_key} for {self.user_email} on {self.path}")

        try:
            # Assign request number if not already assigned
            if not self.request_number:
                self.request_number = self._assign_request_number()
                # Check for multiple requests
                self._check_and_notify_multiple_requests()

            # Check if there's an active request for the same endpoint with different params
            active_info = self._get_active_request_info()
            if active_info and active_info.get("path") == self.path:
                # Check if it's the same request (same request_key means same params)
                if active_info.get("request_key") != self.request_key:
                    # Different params - cancel the previous request
                    self._cancel_existing_same_endpoint_request()

                    # Force claim this request (overwrite any existing)
                    self.redis_client.set(progress_key, DeduplicationStatus.IN_PROGRESS.value, ex=DEFAULT_TTL)
                    logger.debug(
                        f"{BRIGHT_BLUE}Claimed request {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_BLUE} "
                        f"for {BOLD}{BRIGHT_BLUE}{self.user_email}{RESET}{BRIGHT_BLUE} (different params, last-one-wins){RESET}"
                    )

                    # Record this as the active request for the user
                    self._set_active_request()
                    self.is_executor = True
                    return True
                # else: Same params - fall through to normal deduplication logic

            # For last-one-wins endpoints (legacy, keeping for compatibility)
            if self.path in LAST_ONE_WINS_ENDPOINTS:
                # Cancel any existing request for this endpoint
                self._cancel_existing_same_endpoint_request()

                # Force claim this request (overwrite any existing)
                self.redis_client.set(progress_key, DeduplicationStatus.IN_PROGRESS.value, ex=DEFAULT_TTL)
                logger.debug(
                    f"{BRIGHT_BLUE}Claimed request {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_BLUE} "
                    f"for {BOLD}{BRIGHT_BLUE}{self.user_email}{RESET}{BRIGHT_BLUE} (last-one-wins){RESET}"
                )

                # Record this as the active request for the user
                self._set_active_request()
                self.is_executor = True
                return True

            # Check if there's a higher priority request already running
            if self._should_wait_for_higher_priority():
                logger.info(
                    f"{BRIGHT_BLUE}Request {self.request_key} (priority {self.priority}) {BOLD}{BRIGHT_BLUE}waiting{RESET}{BRIGHT_BLUE} for higher priority request{RESET}"
                )
                return False  # Will trigger wait logic in middleware

            # Normal deduplication logic
            # Try to atomically set the progress key
            if self.redis_client.set(
                progress_key, DeduplicationStatus.IN_PROGRESS.value, nx=True, ex=DEFAULT_TTL
            ):
                logger.debug(
                    f"{BRIGHT_BLUE}Claimed request {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_BLUE} "
                    f"for {BOLD}{BRIGHT_BLUE}{self.user_email}{RESET}"
                )

                # Check for lower priority active requests and cancel them
                self._check_and_cancel_lower_priority_requests()

                # Record this as the active request for the user
                self._set_active_request()
                self.is_executor = True

                return True
            else:
                logger.info(
                    f"{BRIGHT_BLUE}Request {self.request_key} already in progress, will {BOLD}{BRIGHT_BLUE}wait{RESET}{BRIGHT_BLUE} for result{RESET}"
                )
                return False

        except Exception as e:
            logger.error(f"Error claiming request: {e}")
            return True  # Fall back to executing on Redis errors

    def _get_active_request_info(self) -> Optional[dict]:
        """Get information about the active request for this user."""
        if not self.redis_client:
            return None

        try:
            active_key = f"kindle:user:{self.user_email}:active_request"
            active_data = self.redis_client.get(active_key)

            if active_data:
                return json.loads(active_data)

            return None

        except Exception as e:
            logger.error(f"Error getting active request info: {e}")
            return None

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
                        f"{BRIGHT_BLUE}Higher priority request (priority {BOLD}{BRIGHT_BLUE}{active_priority}{RESET}{BRIGHT_BLUE}) is running, "
                        f"lower priority {self.path} (priority {self.priority}) will {BOLD}{BRIGHT_BLUE}wait{RESET}"
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

                        # CRITICAL: Also delete the progress key so future requests don't think they're duplicates
                        progress_key = f"{active_request_key}:progress"
                        self.redis_client.delete(progress_key)

                        logger.info(
                            f"{BRIGHT_YELLOW}Cancelling previous {BOLD}{BRIGHT_BLUE}{self.path}{RESET}{BRIGHT_YELLOW} request "
                            f"{active_request_key} for newer request {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_YELLOW} "
                            f"(last-one-wins){RESET}"
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
                        import time

                        cancel_key = f"{active_request_key}:cancelled"
                        self.redis_client.set(cancel_key, "1", ex=DEFAULT_TTL)

                        # CRITICAL: Also delete the progress key so future requests don't think they're duplicates
                        progress_key = f"{active_request_key}:progress"
                        self.redis_client.delete(progress_key)

                        logger.info(
                            f"{BRIGHT_RED}[{time.time():.3f}] PRIORITY CANCELLATION: {BRIGHT_YELLOW}Cancelling lower priority request "
                            f"{active_request_key} (priority {active_priority}) for higher priority "
                            f"{BOLD}{BRIGHT_BLUE}{self.path}{RESET}{BRIGHT_YELLOW} (priority {self.priority}){RESET}"
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
                "request_number": self.request_number,
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
            # Assign request number if we don't have one yet (though it should already be assigned)
            if not self.request_number:
                self.request_number = self._assign_request_number()
        except Exception:
            pass

        start_time = time.time()
        poll_interval = 0.5  # Start with 500ms polling
        last_check_time = 0

        while (time.time() - start_time) < MAX_WAIT_TIME:
            try:
                # Check for other waiters periodically (every 2 seconds)
                if time.time() - last_check_time > 2:
                    self._check_and_notify_multiple_requests()
                    last_check_time = time.time()

                # Check if request completed
                status = self.redis_client.get(status_key)
                if status:
                    status = status.decode("utf-8") if isinstance(status, bytes) else status

                    if status == DeduplicationStatus.COMPLETED.value:
                        # Get the cached result
                        result_data = self.redis_client.get(result_key)
                        if result_data:
                            result = pickle.loads(result_data)
                            logger.info(
                                f"{BRIGHT_BLUE}Retrieved {BOLD}{BRIGHT_BLUE}deduplicated response{RESET}{BRIGHT_BLUE} for {self.request_key}{RESET}"
                            )

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

        logger.warning(
            f"{BRIGHT_BLUE}Timeout waiting for deduplicated response for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}"
        )
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

                logger.info(
                    f"{BRIGHT_BLUE}Stored response for {self.request_key} with {short_ttl}s TTL for {BOLD}{BRIGHT_BLUE}{waiters_count} waiters{RESET}"
                )
            else:
                # No waiters, just mark as completed and clean up immediately
                self.redis_client.set(status_key, DeduplicationStatus.COMPLETED.value, ex=2)
                logger.debug(f"No waiters for {self.request_key}, marked as completed and will clean up")

                # Clean up immediately since there are no waiters
                keys_to_delete = [
                    f"{self.request_key}:progress",
                    f"{self.request_key}:cancelled",
                ]
                self.redis_client.delete(*keys_to_delete)

            # Clear active request if it's ours
            self._clear_active_request()

            # Clean up request number and potentially reset counter
            self._cleanup_request_number()

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

            # Clean up request number and potentially reset counter
            self._cleanup_request_number()

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
                logger.debug(f"Cleaned up Redis keys for {self.request_key}")

            # Clean up request number for waiters too
            self._cleanup_request_number()

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

        # Assign request number if we don't have one yet (though it should already be assigned)
        if not self.request_number:
            self.request_number = self._assign_request_number()

        start_time = time.time()
        poll_interval = 0.5
        last_check_time = 0

        while (time.time() - start_time) < MAX_WAIT_TIME:
            try:
                # Check for other waiters periodically (every 2 seconds)
                if time.time() - last_check_time > 2:
                    self._check_and_notify_multiple_requests()
                    last_check_time = time.time()

                # Check if we've been cancelled
                if self.is_cancelled():
                    logger.info(
                        f"{BRIGHT_BLUE}Request {self.request_key} was {BOLD}{BRIGHT_BLUE}cancelled{RESET}{BRIGHT_BLUE} while waiting{RESET}"
                    )
                    return WaitResult.CANCELLED

                # Check if higher priority request is still running
                active_key = f"kindle:user:{self.user_email}:active_request"
                active_data = self.redis_client.get(active_key)

                if not active_data:
                    # No active request, we can proceed
                    logger.debug(
                        f"{BRIGHT_BLUE}No active request found, {self.request_key} can {BOLD}{BRIGHT_BLUE}proceed{RESET}"
                    )
                    return WaitResult.READY

                active_request = json.loads(active_data)
                active_priority = active_request.get("priority", 0)

                if active_priority <= self.priority:
                    # Higher priority request finished, we can proceed
                    logger.info(
                        f"{BRIGHT_BLUE}Higher priority request {BOLD}{BRIGHT_BLUE}completed{RESET}{BRIGHT_BLUE}, {self.request_key} can {BOLD}{BRIGHT_BLUE}proceed{RESET}"
                    )
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

        logger.warning(
            f"{BRIGHT_BLUE}Timeout waiting for higher priority request for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}"
        )
        return WaitResult.TIMEOUT

    def __enter__(self):
        """Context manager entry."""
        return self

    def _assign_request_number(self) -> int:
        """Assign a request number to this request for the user."""
        if not self.redis_client:
            return 1

        try:
            # Check if we already have a request number stored
            req_num_key = f"{self.request_key}:request_number"
            existing_num = self.redis_client.get(req_num_key)
            if existing_num:
                # Already have a number, just return it
                return int(existing_num)

            # Key for tracking request numbers per user
            counter_key = f"kindle:user:{self.user_email}:request_counter"
            active_requests_key = f"kindle:user:{self.user_email}:active_request_count"

            # Only increment counter and active count once per request instance
            # Use instance_id to ensure only THIS specific instance can decrement later
            increment_key = f"kindle:instance:{self.instance_id}:incremented_active"
            if self.redis_client.set(increment_key, "1", nx=True, ex=DEFAULT_TTL):
                # First time this request is getting a number
                request_num = self.redis_client.incr(counter_key)
                active_count = self.redis_client.incr(active_requests_key)

                # Store the request number for this specific request key
                self.redis_client.set(req_num_key, str(request_num), ex=DEFAULT_TTL)

                # Set expiration on both keys
                self.redis_client.expire(counter_key, DEFAULT_TTL)
                self.redis_client.expire(active_requests_key, DEFAULT_TTL)

                logger.debug(
                    f"Assigned NEW request number {request_num} to {self.user_email} (active count: {active_count})"
                )
                return request_num
            else:
                # Should not happen - we already checked for existing number
                logger.warning(f"Request {self.request_key} already incremented but missing number")
                return 1

        except Exception as e:
            logger.error(f"Error assigning request number: {e}")
            return 1

    def _check_and_notify_multiple_requests(self):
        """Check if there are multiple requests and set flag in Redis."""
        if not self.redis_client:
            return

        try:
            # Check active request count
            active_requests_key = f"kindle:user:{self.user_email}:active_request_count"
            active_count = self.redis_client.get(active_requests_key)

            # Set or clear the multiple requests flag
            multi_key = f"kindle:user:{self.user_email}:has_multiple_requests"
            if active_count and int(active_count) > 1:
                self.redis_client.set(multi_key, "1", ex=DEFAULT_TTL)
            else:
                self.redis_client.delete(multi_key)

        except Exception as e:
            logger.error(f"Error checking for multiple requests: {e}")

    def get_request_number(self) -> Optional[int]:
        """Get the request number for this request."""
        if self.request_number:
            return self.request_number

        if not self.redis_client:
            return None

        try:
            req_num_key = f"{self.request_key}:request_number"
            num = self.redis_client.get(req_num_key)
            if num:
                self.request_number = int(num)
                return self.request_number
        except Exception:
            pass

        return None

    def _cleanup_request_number(self):
        """Decrement active request count and reset counter if needed."""
        if not self.redis_client or not self.request_number:
            return

        try:
            # Check if THIS SPECIFIC instance incremented the active count
            # Use instance_id to ensure only the instance that incremented can decrement
            increment_key = f"kindle:instance:{self.instance_id}:incremented_active"
            decrement_key = f"kindle:instance:{self.instance_id}:decremented_active"

            # Only decrement if THIS instance incremented AND hasn't already decremented
            if self.redis_client.get(increment_key) and self.redis_client.set(
                decrement_key, "1", nx=True, ex=10
            ):
                active_requests_key = f"kindle:user:{self.user_email}:active_request_count"
                counter_key = f"kindle:user:{self.user_email}:request_counter"

                # Decrement the active request count
                remaining = self.redis_client.decr(active_requests_key)

                # If no more active requests, reset the counter back to 0
                if remaining <= 0:
                    self.redis_client.delete(counter_key)
                    self.redis_client.delete(active_requests_key)
                    # Also clear the multiple requests flag
                    multi_key = f"kindle:user:{self.user_email}:has_multiple_requests"
                    self.redis_client.delete(multi_key)
                    logger.info(
                        f"{BRIGHT_BLUE}Reset request counter for {self.user_email} - {BOLD}{BRIGHT_BLUE}no active requests remaining{RESET}"
                    )
                else:
                    # Update the multiple requests flag
                    self._check_and_notify_multiple_requests()
                    logger.debug(f"Decremented active count for {self.user_email}, {remaining} still active")

                # Clean up instance-specific keys
                self.redis_client.delete(increment_key, decrement_key)
            else:
                logger.debug(
                    f"Skipping decrement for {self.user_email} - already decremented or never incremented"
                )

        except Exception as e:
            logger.error(f"Error cleaning up request number: {e}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - handle errors."""
        if exc_type is not None:
            self._mark_error()
        return False
