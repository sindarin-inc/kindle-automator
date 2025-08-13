"""Streaming request manager for handling reconnectable streams with accumulation."""

import json
import logging
import pickle
import time
from typing import Any, Generator, Optional

from server.core.request_manager import RequestManager
from server.utils.ansi_colors import BOLD, BRIGHT_BLUE, RESET

logger = logging.getLogger(__name__)

# TTL for streaming data
STREAM_TTL = 300  # 5 minutes


class StreamingRequestManager(RequestManager):
    """
    Manages streaming requests with accumulation and replay for reconnecting clients.

    This is used for endpoints like /books-stream where:
    1. Results are accumulated as the stream progresses
    2. Reconnecting clients get all accumulated data + continue the live stream
    3. Higher priority requests can still cancel the stream
    """

    def __init__(self, user_email: str, path: str, method: str = "GET"):
        """Initialize streaming request manager."""
        super().__init__(user_email, path, method)
        self.accumulated_key = f"{self.request_key}:accumulated"
        self.stream_active_key = f"{self.request_key}:streaming"

    def start_streaming(self) -> bool:
        """
        Start a new streaming session or join an existing one.

        Returns:
            True if this is a new stream (caller should execute)
            False if joining existing stream (caller should replay + follow)
        """
        if not self.redis_client:
            return True  # No Redis, always execute

        try:
            # Check if stream is already active
            if self.redis_client.get(self.stream_active_key):
                logger.info(
                    f"{BRIGHT_BLUE}Joining existing stream for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}"
                )
                return False

            # Try to claim the stream
            if self.redis_client.set(self.stream_active_key, "1", nx=True, ex=STREAM_TTL):
                logger.info(
                    f"{BRIGHT_BLUE}Started new stream for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}"
                )

                # Initialize accumulated data list
                self.redis_client.delete(self.accumulated_key)

                # Check for and cancel lower priority requests
                self._check_and_cancel_lower_priority_requests()

                # Set as active request
                self._set_active_request()

                return True
            else:
                logger.info(
                    f"{BRIGHT_BLUE}Stream already active for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_BLUE}, will join{RESET}"
                )
                return False

        except Exception as e:
            logger.error(f"Error starting stream: {e}")
            return True  # Execute on error

    def accumulate_data(self, data: Any):
        """
        Accumulate data for replay to reconnecting clients.

        Args:
            data: The data chunk to accumulate (will be pickled)
        """
        if not self.redis_client:
            return

        try:
            # Append to the accumulated list
            pickled_data = pickle.dumps(data)
            self.redis_client.rpush(self.accumulated_key, pickled_data)
            self.redis_client.expire(self.accumulated_key, STREAM_TTL)

        except Exception as e:
            logger.error(f"Error accumulating stream data: {e}")

    def get_accumulated_data(self) -> Generator[Any, None, None]:
        """
        Get all accumulated data so far.

        Yields:
            Accumulated data chunks in order
        """
        if not self.redis_client:
            return

        try:
            # Get all accumulated data
            accumulated = self.redis_client.lrange(self.accumulated_key, 0, -1)

            for pickled_chunk in accumulated:
                try:
                    chunk = pickle.loads(pickled_chunk)
                    yield chunk
                except Exception as e:
                    logger.error(f"Error unpickling accumulated chunk: {e}")

        except Exception as e:
            logger.error(f"Error getting accumulated data: {e}")

    def follow_stream(self, start_index: int = 0) -> Generator[Any, None, None]:
        """
        Follow the live stream starting from a given index.

        Args:
            start_index: The index to start from (for resuming after accumulated data)

        Yields:
            New data chunks as they arrive
        """
        if not self.redis_client:
            return

        last_index = start_index
        consecutive_empty = 0
        max_consecutive_empty = 10  # Stop after 10 consecutive empty polls

        while consecutive_empty < max_consecutive_empty:
            try:
                # Check if stream is still active
                if not self.redis_client.get(self.stream_active_key):
                    logger.info(
                        f"{BRIGHT_BLUE}Stream {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}{BRIGHT_BLUE} has ended{RESET}"
                    )
                    break

                # Get new items since last index
                new_items = self.redis_client.lrange(self.accumulated_key, last_index, -1)

                if new_items:
                    consecutive_empty = 0
                    for pickled_chunk in new_items:
                        try:
                            chunk = pickle.loads(pickled_chunk)
                            yield chunk
                            last_index += 1
                        except Exception as e:
                            logger.error(f"Error unpickling stream chunk: {e}")
                            last_index += 1
                else:
                    consecutive_empty += 1
                    time.sleep(0.5)  # Wait before polling again

            except Exception as e:
                logger.error(f"Error following stream: {e}")
                break

    def end_streaming(self):
        """Mark the stream as ended and clean up."""
        if not self.redis_client:
            return

        try:
            # Clear the streaming flag
            self.redis_client.delete(self.stream_active_key)

            # Clear active request
            self._clear_active_request()

            # Keep accumulated data for a bit for late joiners
            self.redis_client.expire(self.accumulated_key, 60)  # Keep for 1 minute

            logger.info(f"{BRIGHT_BLUE}Ended stream for {BOLD}{BRIGHT_BLUE}{self.request_key}{RESET}")

        except Exception as e:
            logger.error(f"Error ending stream: {e}")
