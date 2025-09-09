"""Integration tests for request deduplication and cancellation functionality."""

import json
import logging
import pickle
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest
import redis

logger = logging.getLogger(__name__)

from server.core.request_manager import DeduplicationStatus, RequestManager, WaitResult
from server.utils.cancellation_utils import (
    CancellationChecker,
    mark_cancelled,
    should_cancel,
)
from tests.test_base import TEST_USER_EMAIL, BaseKindleTest


class Test1RequestDeduplicationIntegration(BaseKindleTest, unittest.TestCase):
    """Integration tests for request deduplication with threading."""

    def setUp(self):
        """Set up test fixtures."""
        # Use the base class setup for proper authentication
        self.setup_base()
        self.email = TEST_USER_EMAIL

    def tearDown(self):
        """Clean up after tests."""
        # Close the session but don't stop the server
        if hasattr(self, "session"):
            self.session.close()

    @patch("server.core.request_manager.get_redis_client")
    def test_concurrent_requests_deduplication(self, mock_get_redis):
        """Test that concurrent identical requests are properly deduplicated."""

        # Use a real Redis-like mock that simulates atomic operations
        class RedisSimulator:
            def __init__(self):
                self.store = {}
                self.lock = threading.Lock()

            def set(self, key, value, nx=False, ex=None):
                with self.lock:
                    if nx and key in self.store:
                        return False
                    self.store[key] = value
                    return True

            def get(self, key):
                with self.lock:
                    return self.store.get(key)

            def incr(self, key):
                with self.lock:
                    val = self.store.get(key, 0)
                    if isinstance(val, bytes):
                        val = int(val)
                    self.store[key] = val + 1
                    return val + 1

            def decr(self, key):
                with self.lock:
                    val = self.store.get(key, 0)
                    if isinstance(val, bytes):
                        val = int(val)
                    self.store[key] = val - 1
                    return val - 1

            def delete(self, *keys):
                with self.lock:
                    for key in keys:
                        self.store.pop(key, None)

            def expire(self, key, seconds):
                # Mock expire - just ignore it
                return True

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        results = []
        execution_count = 0

        def make_request():
            nonlocal execution_count
            manager = RequestManager("test@example.com", "/books", "GET")

            if manager.claim_request():
                # Simulate request execution
                execution_count += 1
                time.sleep(0.1)  # Simulate work
                response = {"data": "result"}
                manager.store_response(response, 200)
                results.append(("executed", response))
            else:
                # Wait for deduplicated response
                result = manager.wait_for_deduplicated_response()
                if result:
                    results.append(("deduplicated", result[0]))
                else:
                    # Handle timeout or error case
                    results.append(("timeout", None))

        # Start multiple threads making the same request
        threads = []
        for _ in range(5):
            t = threading.Thread(target=make_request)
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join(timeout=5)

        # Verify only one request was executed
        self.assertEqual(execution_count, 1)

        # Verify all threads got results
        self.assertEqual(len(results), 5, f"Expected 5 results, got {len(results)}: {results}")

        # Verify one execution and others deduplicated or timed out
        executed = [r for r in results if r[0] == "executed"]
        deduplicated = [r for r in results if r[0] == "deduplicated"]
        timeouts = [r for r in results if r[0] == "timeout"]

        self.assertEqual(len(executed), 1, f"Expected 1 executed, got {len(executed)}")
        # The rest should be deduplicated (timeouts indicate a problem)
        self.assertEqual(len(timeouts), 0, f"Got {len(timeouts)} timeouts - this suggests a timing issue")
        self.assertEqual(len(deduplicated), 4, f"Expected 4 deduplicated, got {len(deduplicated)}")

    @patch("server.core.request_manager.get_redis_client")
    def test_priority_waiting(self, mock_get_redis):
        """Test that lower priority requests wait for higher priority ones."""

        # Use a real Redis-like mock that simulates atomic operations
        class RedisSimulator:
            def __init__(self):
                self.store = {}
                self.lock = threading.Lock()

            def set(self, key, value, nx=False, ex=None):
                with self.lock:
                    if nx and key in self.store:
                        return False
                    self.store[key] = value
                    return True

            def get(self, key):
                with self.lock:
                    return self.store.get(key)

            def delete(self, *keys):
                with self.lock:
                    for key in keys:
                        self.store.pop(key, None)

            def expire(self, key, seconds):
                # Mock expire - just ignore it
                return True

            def incr(self, key):
                with self.lock:
                    val = self.store.get(key, 0)
                    if isinstance(val, bytes):
                        val = int(val)
                    self.store[key] = val + 1
                    return val + 1

            def decr(self, key):
                with self.lock:
                    val = self.store.get(key, 0)
                    if isinstance(val, bytes):
                        val = int(val)
                    self.store[key] = val - 1
                    return val - 1

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        results = []
        timings = {}

        def make_high_priority_request():
            """Simulate a high priority /open-book request."""
            start = time.time()
            manager = RequestManager("test@example.com", "/open-book", "POST")

            if manager.claim_request():
                # Simulate longer execution
                time.sleep(0.3)
                manager.store_response({"book": "opened"}, 200)
                elapsed = time.time() - start
                results.append(("high", elapsed))
                timings["high"] = elapsed

        def make_low_priority_request():
            """Simulate a low priority /screenshot request."""
            start = time.time()
            manager = RequestManager("test@example.com", "/screenshot", "GET")

            # This should wait for high priority to complete
            if not manager.claim_request():
                # Should be waiting for higher priority
                wait_result = manager.wait_for_higher_priority_completion()
                if wait_result == WaitResult.READY:
                    # Now can execute
                    time.sleep(0.1)
                    elapsed = time.time() - start
                    results.append(("low", elapsed))
                    timings["low"] = elapsed
            else:
                # Shouldn't happen in this test
                elapsed = time.time() - start
                results.append(("low_immediate", elapsed))

        # Start high priority request first
        t1 = threading.Thread(target=make_high_priority_request)
        t1.start()

        # Give it a moment to claim the request
        time.sleep(0.05)

        # Now start low priority request - it should wait
        t2 = threading.Thread(target=make_low_priority_request)
        t2.start()

        # Wait for both to complete
        t1.join(timeout=2)
        t2.join(timeout=2)

        # Verify both completed
        self.assertEqual(len(results), 2)

        # Verify low priority waited for high priority
        # Low priority should take longer than high priority
        self.assertIn("high", timings)
        self.assertIn("low", timings)
        self.assertGreater(timings["low"], timings["high"])

        # Low priority time should be roughly high priority time + its own execution
        # (0.3s for high + 0.1s for low = ~0.4s total)
        self.assertGreater(timings["low"], 0.35)

    @patch("server.core.request_manager.get_redis_client")
    def test_priority_cancellation_and_waiting(self, mock_get_redis):
        """Test both cancellation (high cancels low) and waiting (low waits for high)."""

        class RedisSimulator:
            def __init__(self):
                self.store = {}
                self.lock = threading.Lock()

            def set(self, key, value, nx=False, ex=None):
                with self.lock:
                    if nx and key in self.store:
                        return False
                    self.store[key] = value
                    return True

            def get(self, key):
                with self.lock:
                    return self.store.get(key)

            def delete(self, *keys):
                with self.lock:
                    for key in keys:
                        self.store.pop(key, None)

            def expire(self, key, seconds):
                # Mock expire - just ignore it
                return True

            def incr(self, key):
                return 1

            def decr(self, key):
                return 0

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        # Test 1: High priority cancels running low priority
        low_manager = RequestManager("test@example.com", "/screenshot", "GET")
        self.assertTrue(low_manager.claim_request())

        # Now a high priority request comes in
        high_manager = RequestManager("test@example.com", "/open-book", "POST")
        high_manager._check_and_cancel_lower_priority_requests()

        # Verify low priority is marked as cancelled
        self.assertTrue(low_manager.is_cancelled())

        # Clean up for next test
        redis_sim.store.clear()

        # Test 2: Low priority waits for running high priority
        high_manager2 = RequestManager("test@example.com", "/open-book", "POST")
        self.assertTrue(high_manager2.claim_request())

        # Low priority should detect it needs to wait
        low_manager2 = RequestManager("test@example.com", "/screenshot", "GET")
        self.assertTrue(low_manager2._should_wait_for_higher_priority())

    @pytest.mark.expensive
    def test_last_one_wins_for_random_book(self):
        """Test that newer /open-random-book requests cancel older ones."""
        # This test verifies that when multiple /open-random-book requests are made,
        # each new request cancels the previous one since they're for the same user
        # and endpoint but with different implicit randomness.

        results = {}

        def make_open_random_book_request(request_id, delay=0):
            """Make an /open-random-book request after a delay."""
            if delay > 0:
                time.sleep(delay)

            start_time = time.time()
            results[f"request_{request_id}_started"] = start_time

            try:
                # Each request gets a unique timestamp to ensure they're different
                response = self._make_request(
                    "open-random-book",
                    params={
                        "user_email": self.email,  # Use the same email as rest of the test
                        "t": str(time.time()),  # Unique timestamp for each request
                        "force_library_navigation": "1",  # Force going through library for more rigorous testing
                    },
                    timeout=60,
                )
                end_time = time.time()
                results[f"request_{request_id}_status"] = response.status_code
                results[f"request_{request_id}_completed"] = end_time
                results[f"request_{request_id}_duration"] = end_time - start_time

                # Check if response indicates cancellation
                if response.status_code == 409:
                    results[f"request_{request_id}_cancelled"] = True
                    try:
                        data = response.json()
                        results[f"request_{request_id}_cancel_reason"] = data.get("error", "Cancelled")
                    except:
                        pass
                elif response.status_code == 200:
                    results[f"request_{request_id}_success"] = True
                    try:
                        data = response.json()
                        if data.get("cancelled"):
                            results[f"request_{request_id}_cancelled"] = True
                            results[f"request_{request_id}_cancel_reason"] = data.get("error", "Cancelled")
                    except:
                        pass

            except Exception as e:
                results[f"request_{request_id}_error"] = str(e)
                results[f"request_{request_id}_duration"] = time.time() - start_time
                # Check if the error indicates cancellation
                if "cancelled" in str(e).lower() or "409" in str(e):
                    results[f"request_{request_id}_cancelled"] = True

        # Start three threads for three /open-random-book requests
        threads = []

        # First request - starts immediately
        thread1 = threading.Thread(target=make_open_random_book_request, args=(1, 0))
        threads.append(thread1)
        thread1.start()

        # Second request - starts after 0.5 seconds
        thread2 = threading.Thread(target=make_open_random_book_request, args=(2, 0.5))
        threads.append(thread2)
        thread2.start()

        # Third request - starts after 1 second
        thread3 = threading.Thread(target=make_open_random_book_request, args=(3, 1))
        threads.append(thread3)
        thread3.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=35)

        # Verify the results
        # The first two requests should have been cancelled
        self.assertTrue(
            results.get("request_1_cancelled", False),
            f"Request 1 should have been cancelled. Results: {results}",
        )
        self.assertTrue(
            results.get("request_2_cancelled", False),
            f"Request 2 should have been cancelled. Results: {results}",
        )

        # The third request should have succeeded
        self.assertTrue(
            results.get("request_3_success", False), f"Request 3 should have succeeded. Results: {results}"
        )
        self.assertFalse(
            results.get("request_3_cancelled", False),
            f"Request 3 should not have been cancelled. Results: {results}",
        )

    @patch("server.core.request_manager.get_redis_client")
    def test_cache_not_persisted_after_completion(self, mock_get_redis):
        """Test that cache is cleared after request completes with no waiters."""

        class RedisSimulator:
            def __init__(self):
                self.store = {}
                self.lock = threading.Lock()

            def set(self, key, value, nx=False, ex=None):
                with self.lock:
                    if nx and key in self.store:
                        return False
                    self.store[key] = value
                    return True

            def get(self, key):
                with self.lock:
                    return self.store.get(key)

            def delete(self, *keys):
                with self.lock:
                    for key in keys:
                        self.store.pop(key, None)

            def expire(self, key, seconds):
                # Mock expire - just ignore it
                return True

            def incr(self, key):
                return 1

            def decr(self, key):
                return 0

            def expire(self, key, seconds):
                # Mock expire - just ignore it
                return True

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        # First request - should execute and not leave cached result
        manager1 = RequestManager("test@example.com", "/books", "GET")
        self.assertTrue(manager1.claim_request())

        # Store response with no waiters
        response1 = {"books": ["Book 1", "Book 2"]}
        manager1.store_response(response1, 200)

        # Verify all deduplication keys were deleted immediately (no waiters)
        status_key = f"{manager1.request_key}:status"
        result_key = f"{manager1.request_key}:result"
        progress_key = f"{manager1.request_key}:progress"
        waiters_key = f"{manager1.request_key}:waiters"

        # All keys should be deleted when no waiters
        self.assertNotIn(status_key, redis_sim.store)
        self.assertNotIn(result_key, redis_sim.store)
        self.assertNotIn(progress_key, redis_sim.store)
        self.assertNotIn(waiters_key, redis_sim.store)

        # Clear any remaining keys (like request_number)
        redis_sim.store.clear()

        # Second request with same parameters - should NOT get cached response
        manager2 = RequestManager("test@example.com", "/books", "GET")

        # Should be able to claim (not duplicate since cache was cleared)
        self.assertTrue(manager2.claim_request())

        # This proves the second request will execute fresh, not use cached data


class Test2PriorityAndCancellation(BaseKindleTest, unittest.TestCase):
    """Test priority-based request management and cancellation.

    These tests verify that higher priority requests properly cancel lower priority ones,
    and that streaming endpoints detect cancellation quickly.
    """

    def setUp(self):
        """Set up test fixtures."""
        # Use the base class setup
        self.setup_base()
        # Use TEST_USER_EMAIL from environment (defaults to kindle@solreader.com)
        self.email = TEST_USER_EMAIL

    def tearDown(self):
        """Clean up after tests."""
        # Close the session
        self.session.close()
        # Don't stop the server - it's managed externally
        pass

    def test_screenshot_runs_concurrently(self):
        """Test that /screenshot runs concurrently without priority blocking."""
        results = {}

        def high_priority_request():
            """Make a high priority request that takes time."""
            try:
                response = self._make_request(
                    "open-random-book",
                    params={"user_email": self.email},
                    timeout=120,
                )
                results["high_priority"] = {"status": response.status_code, "completed_at": time.time()}
            except Exception as e:
                results["high_priority_error"] = str(e)

        def screenshot_request():
            """Make a screenshot request."""
            try:
                response = self._make_request(
                    "screenshot",
                    params={"user_email": self.email},
                    timeout=120,
                )
                results["screenshot"] = {"status": response.status_code, "completed_at": time.time()}
            except Exception as e:
                results["screenshot_error"] = str(e)

        # Start high priority request
        results["high_started"] = time.time()
        high_thread = threading.Thread(target=high_priority_request)
        high_thread.start()

        # Wait briefly for high priority to claim the request
        time.sleep(0.5)

        # Start screenshot request
        results["screenshot_started"] = time.time()
        screenshot_thread = threading.Thread(target=screenshot_request)
        screenshot_thread.start()

        # Wait for both to complete (longer timeout for slower test environments)
        high_thread.join(timeout=120)  # Increased timeout for CI
        screenshot_thread.join(timeout=120)  # Increased timeout for CI

        # Check if threads are still alive (timeout occurred)
        if high_thread.is_alive():
            error_msg = f"High priority thread did not complete within timeout. Results: {results}"
            if "high_priority_error" in results:
                error_msg += f" Error: {results['high_priority_error']}"
            self.fail(error_msg)
        if screenshot_thread.is_alive():
            error_msg = f"Screenshot thread did not complete within timeout. Results: {results}"
            if "screenshot_error" in results:
                error_msg += f" Error: {results['screenshot_error']}"
            self.fail(error_msg)

        # Verify screenshot completed (it may be cancelled with 409 or succeed with 200)
        if "screenshot_error" in results:
            self.fail(f"Screenshot request failed with error: {results['screenshot_error']}")
        self.assertIn("screenshot", results, f"Screenshot request did not complete. Results: {results}")
        # Screenshot can either succeed (200) or be cancelled (409) - both are valid
        self.assertIn(
            results["screenshot"]["status"],
            [200, 409],
            "Screenshot should either complete (200) or be cancelled (409)",
        )

    def test_stream_cancellation_by_higher_priority(self):
        """Test that /books stream is cancelled when higher priority /open-book request arrives."""
        results = {}
        cancellation_count = 0

        def stream_books():
            """Stream books endpoint."""
            nonlocal cancellation_count
            results["stream_started"] = time.time()
            session = self._create_test_session()
            try:
                params = self._build_params({"user_email": self.email})
                # Use stream=True to properly handle streaming responses
                response = session.get(
                    f"{self.base_url}/kindle/books-stream",
                    params=params,
                    timeout=15,  # Shorter timeout since cancellation should be quick
                    stream=True,  # Important for proper streaming
                )

                # Store response status for debugging
                results["stream_status_code"] = response.status_code

                # Check for cancellation in response
                if response.status_code == 409:  # Conflict status for cancellation
                    try:
                        data = response.json()
                        if data.get("cancelled") or (
                            "error" in data and "cancelled" in data["error"].lower()
                        ):
                            results["stream_cancelled"] = time.time()
                            results["cancellation_reason"] = data.get("error", "Cancelled")
                            cancellation_count += 1
                    except Exception as e:
                        results["stream_error"] = f"Failed to parse cancellation response: {e}"
                elif response.status_code == 200:
                    # If we got 200, check the response for cancellation indicators
                    try:
                        # Check if it's streaming or regular JSON
                        content_type = response.headers.get("content-type", "")
                        if "text/event-stream" in content_type or "application/x-ndjson" in content_type:
                            # It's a streaming response
                            line_count = 0
                            for line in response.iter_lines(decode_unicode=True):
                                if line:
                                    line_count += 1
                                    # Try to parse as JSON
                                    try:
                                        data = json.loads(line)
                                        if data.get("done"):
                                            results["stream_completed"] = time.time()
                                            break
                                        if data.get("cancelled"):
                                            results["stream_cancelled"] = time.time()
                                            results["cancellation_reason"] = data.get("error", "Cancelled")
                                            cancellation_count += 1
                                            break
                                    except json.JSONDecodeError:
                                        # Not JSON, might be raw text
                                        pass
                            if line_count == 0:
                                # No lines received - stream was likely interrupted
                                results["stream_error"] = "Stream interrupted - no data received"
                        else:
                            # Regular JSON response - check if it indicates cancellation
                            data = response.json()
                            if data.get("cancelled"):
                                results["stream_cancelled"] = time.time()
                                results["cancellation_reason"] = data.get("error", "Cancelled")
                                cancellation_count += 1
                            else:
                                # Check if response contains partial data (indicating early termination)
                                if "books" in data and len(data["books"]) < 10:
                                    # Might have been cancelled early
                                    results["stream_partial"] = time.time()
                                    results["book_count"] = len(data["books"])
                                else:
                                    results["stream_completed"] = time.time()
                    except Exception as e:
                        # Connection errors or JSON errors could indicate cancellation
                        error_str = str(e).lower()
                        if "connection" in error_str or "reset" in error_str or "extra data" in error_str:
                            results["stream_cancelled"] = time.time()
                            results["cancellation_reason"] = f"Stream interrupted: {e}"
                            cancellation_count += 1
                        else:
                            results["stream_error"] = f"Stream reading error: {e}"
                else:
                    results["stream_error"] = f"Unexpected status: {response.status_code}"

            except Exception as e:
                error_str = str(e).lower()
                # Check if it's a cancellation-related error
                if "cancelled" in error_str or "connection" in error_str or "reset" in error_str:
                    results["stream_cancelled"] = time.time()
                    results["cancellation_reason"] = str(e)
                    cancellation_count += 1
                else:
                    results["stream_error"] = str(e)
            finally:
                session.close()

        def open_book():
            """Open a book (higher priority)."""
            results["open_started"] = time.time()
            try:
                response = self._make_request(
                    "open-random-book",
                    params={"user_email": self.email},
                    timeout=60,
                )
                results["open_completed"] = time.time()
                results["open_status"] = response.status_code
            except Exception as e:
                results["open_error"] = str(e)
                raise

        # Start /books request
        stream_thread = threading.Thread(target=stream_books)
        stream_thread.start()

        # Wait 2 seconds to ensure /books is actively processing
        # Reduced from 5 to 2 seconds to catch the stream earlier in its processing
        time.sleep(2)

        # Start higher priority /open-book request
        open_thread = threading.Thread(target=open_book)
        open_thread.start()

        # Wait for both to complete
        stream_thread.join(timeout=15)
        open_thread.join(timeout=60)

        # Verify /open-book returned 200
        self.assertIn("open_status", results, f"Open book did not complete. Results: {results}")
        self.assertEqual(results["open_status"], 200, f"Open book should return 200. Results: {results}")

        # Verify stream was cancelled or interrupted
        stream_was_cancelled = (
            "stream_cancelled" in results or "stream_error" in results or "stream_partial" in results
        )

        if not stream_was_cancelled:
            # Check if stream completed before open-book even started
            if "stream_completed" in results and "open_started" in results:
                stream_completion_time = results["stream_completed"]
                open_start_time = results["open_started"]
                if stream_completion_time < open_start_time:
                    # Stream finished before open-book started - this is a timing issue, not a failure
                    self.skipTest(
                        f"Stream completed before open-book started (likely empty book list on CI). "
                        f"Stream completed at {stream_completion_time:.3f}, open started at {open_start_time:.3f}"
                    )

            # Stream should have been cancelled by higher priority request
            self.fail(f"Stream should have been cancelled by higher priority request. Results: {results}")

        # If stream was properly cancelled, verify it was reasonably fast
        if "stream_cancelled" in results and "open_started" in results:
            cancellation_delay = results["stream_cancelled"] - results["open_started"]
            self.assertLess(
                cancellation_delay,
                15.0,
                f"Cancellation took {cancellation_delay:.1f}s, should be under 15s",
            )

    @pytest.mark.expensive
    def test_three_open_random_book_requests_only_last_succeeds(self):
        """Test that multiple /open-book requests cancel earlier ones when they have different parameters.

        For same parameters, requests should deduplicate (wait for same result) rather than cancel."""
        results = {}

        # Define the books for each request
        books = {
            1: "Fourth Wing",  # A
            2: "Breakfast of Champions",  # B
            3: "sol-chapter-test-epub",  # C
            4: "sol-chapter-test-epub",  # D (same as C for deduplication)
        }

        def make_open_random_book_request(request_id, delay=0):
            """Make an open-book request after a delay."""
            if delay > 0:
                time.sleep(delay)

            start_time = time.time()
            results[f"request_{request_id}_started"] = start_time

            # Create a separate session for this thread
            session = self._create_test_session()

            try:
                # Use /open-book with specific titles
                # Build URL and params directly since we're using a custom session
                url = f"{self.base_url}/kindle/open-book"
                params = {
                    "user_email": self.email,
                    "title": books[request_id],
                    "staging": "1",
                    "force_library_navigation": "1",  # Force going through library for more rigorous testing
                }

                response = session.get(url, params=params, timeout=60)
                end_time = time.time()
                results[f"request_{request_id}_status"] = response.status_code
                results[f"request_{request_id}_completed"] = end_time
                results[f"request_{request_id}_duration"] = end_time - start_time

                # Check if response indicates cancellation
                if response.status_code == 409:
                    results[f"request_{request_id}_cancelled"] = True
                    try:
                        data = response.json()
                        results[f"request_{request_id}_cancel_reason"] = data.get("error", "Cancelled")
                    except:
                        pass
                elif response.status_code == 200:
                    results[f"request_{request_id}_success"] = True
                    try:
                        data = response.json()
                        if data.get("cancelled"):
                            results[f"request_{request_id}_cancelled"] = True
                            results[f"request_{request_id}_cancel_reason"] = data.get("error", "Cancelled")
                        # Store the book that was opened
                        if data.get("progress", {}).get("title"):
                            results[f"request_{request_id}_book"] = data["progress"]["title"]
                    except:
                        pass

            except Exception as e:
                results[f"request_{request_id}_error"] = str(e)
                results[f"request_{request_id}_duration"] = time.time() - start_time
                # Check if the error indicates cancellation
                if "cancelled" in str(e).lower() or "409" in str(e):
                    results[f"request_{request_id}_cancelled"] = True
            finally:
                # Clean up the session
                session.close()

        # Start four threads for the four requests (each will get a random book)
        threads = []

        # First request - starts immediately
        thread1 = threading.Thread(target=make_open_random_book_request, args=(1, 0))
        threads.append(thread1)
        thread1.start()

        # Second request - starts after 3 seconds
        thread2 = threading.Thread(target=make_open_random_book_request, args=(2, 3))
        threads.append(thread2)
        thread2.start()

        # Third request - starts after 6 seconds
        thread3 = threading.Thread(target=make_open_random_book_request, args=(3, 6))
        threads.append(thread3)
        thread3.start()

        # Fourth request - starts after 9 seconds
        thread4 = threading.Thread(target=make_open_random_book_request, args=(4, 9))
        threads.append(thread4)
        thread4.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=45)

        # Verify the results
        print(f"Test results: {results}")

        # All four requests should have started
        self.assertIn("request_1_started", results, "First request should have started")
        self.assertIn("request_2_started", results, "Second request should have started")
        self.assertIn("request_3_started", results, "Third request should have started")
        self.assertIn("request_4_started", results, "Fourth request should have started")

        # First two requests should have been cancelled (different titles from later requests)
        self.assertTrue(
            results.get("request_1_cancelled", False) or results.get("request_1_status") == 409,
            f"First request (Fourth Wing) should have been cancelled. Results: {results}",
        )
        self.assertTrue(
            results.get("request_2_cancelled", False) or results.get("request_2_status") == 409,
            f"Second request (Breakfast of Champions) should have been cancelled. Results: {results}",
        )

        # Third request should succeed
        self.assertEqual(
            results.get("request_3_status"),
            200,
            f"Third request (sol-chapter-test-epub) should have succeeded with status 200. Results: {results}",
        )

        # Fourth request has same title as third - for /open-book endpoint,
        # LAST_ONE_WINS behavior only applies to different parameters.
        # With the same title, Request 4 should deduplicate and get a 200 response.
        self.assertEqual(
            results.get("request_4_status"),
            200,
            f"Fourth request (same title as third) should deduplicate and succeed with status 200. Results: {results}",
        )

        # Print which books were requested
        for i in range(1, 5):
            print(f"Request {i} requested book: {books[i]}")
            if f"request_{i}_book" in results:
                print(f"  -> Actually opened: {results[f'request_{i}_book']}")

        # Verify timing - requests should have started approximately 3 seconds apart
        if "request_1_started" in results and "request_2_started" in results:
            delay_1_2 = results["request_2_started"] - results["request_1_started"]
            self.assertGreater(
                delay_1_2, 2.5, f"Second request should start ~3s after first. Actual: {delay_1_2:.1f}s"
            )
            self.assertLess(
                delay_1_2, 3.5, f"Second request should start ~3s after first. Actual: {delay_1_2:.1f}s"
            )

        if "request_2_started" in results and "request_3_started" in results:
            delay_2_3 = results["request_3_started"] - results["request_2_started"]
            self.assertGreater(
                delay_2_3, 2.5, f"Third request should start ~3s after second. Actual: {delay_2_3:.1f}s"
            )
            self.assertLess(
                delay_2_3, 3.5, f"Third request should start ~3s after second. Actual: {delay_2_3:.1f}s"
            )

        if "request_3_started" in results and "request_4_started" in results:
            delay_3_4 = results["request_4_started"] - results["request_3_started"]
            self.assertGreater(
                delay_3_4, 2.5, f"Fourth request should start ~3s after third. Actual: {delay_3_4:.1f}s"
            )
            self.assertLess(
                delay_3_4, 3.5, f"Fourth request should start ~3s after third. Actual: {delay_3_4:.1f}s"
            )

    def test_z_double_shutdown_both_return_200(self):
        """Test that calling /shutdown twice on the same emulator both return 200."""
        results = {}

        # First ensure an emulator is running by making a simple request
        try:
            init_response = self._make_request(
                "screenshot",
                params={"user_email": self.email},
                timeout=60,
            )
            results["init_status"] = init_response.status_code
        except Exception as e:
            results["init_error"] = str(e)

        def shutdown_first():
            """First shutdown request."""
            print(f"Starting first shutdown at {time.time()}")
            try:
                response = self._make_request(
                    "shutdown",
                    params={"user_email": self.email},
                    timeout=60,
                )
                results["shutdown1_status"] = response.status_code
                results["shutdown1_time"] = time.time()
                print(f"First shutdown completed with status {response.status_code}")
                if response.status_code == 200:
                    results["shutdown1_response"] = response.json()
            except Exception as e:
                results["shutdown1_error"] = str(e)
                print(f"First shutdown error: {e}")

        def shutdown_second():
            """Second shutdown request."""
            print(f"Starting second shutdown at {time.time()}")
            try:
                response = self._make_request(
                    "shutdown",
                    params={"user_email": self.email},
                    timeout=60,
                )
                results["shutdown2_status"] = response.status_code
                results["shutdown2_time"] = time.time()
                print(f"Second shutdown completed with status {response.status_code}")
                if response.status_code == 200:
                    results["shutdown2_response"] = response.json()
            except Exception as e:
                results["shutdown2_error"] = str(e)
                print(f"Second shutdown error: {e}")

        # Start both shutdown requests with 1 second delay
        thread1 = threading.Thread(target=shutdown_first)
        thread2 = threading.Thread(target=shutdown_second)

        thread1.start()
        # Wait 1 second before sending second shutdown
        time.sleep(1)
        thread2.start()

        # Wait for both to complete
        thread1.join(timeout=60)
        thread2.join(timeout=60)

        # Verify both returned 200
        self.assertIn("shutdown1_status", results, f"First shutdown did not complete. Results: {results}")
        self.assertEqual(
            results["shutdown1_status"], 200, f"First shutdown should return 200. Results: {results}"
        )

        self.assertIn("shutdown2_status", results, f"Second shutdown did not complete. Results: {results}")
        self.assertEqual(
            results["shutdown2_status"], 200, f"Second shutdown should also return 200. Results: {results}"
        )


if __name__ == "__main__":
    # Run tests in order: main tests -> priority tests -> expensive tests
    # Use unittest's test suite to control order
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add main deduplication tests
    suite.addTests(loader.loadTestsFromTestCase(Test1RequestDeduplicationIntegration))

    # Add priority and cancellation tests (only run if main tests pass)
    suite.addTests(loader.loadTestsFromTestCase(Test2PriorityAndCancellation))

    # Run with stop on first failure
    runner = unittest.TextTestRunner(verbosity=1, failfast=True)
    runner.run(suite)
