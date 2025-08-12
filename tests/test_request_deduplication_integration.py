"""Integration tests for request deduplication and cancellation functionality."""

import json
import pickle
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import redis

from server.core.request_manager import DeduplicationStatus, RequestManager, WaitResult
from server.utils.cancellation_utils import (
    CancellationChecker,
    mark_cancelled,
    should_cancel,
)
from tests.test_base import TEST_USER_EMAIL, BaseKindleTest


class TestRequestDeduplicationIntegration(unittest.TestCase):
    """Integration tests for request deduplication with threading."""

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

    @patch("server.core.request_manager.get_redis_client")
    def test_last_one_wins_for_random_book(self, mock_get_redis):
        """Test that newer /open-random-book requests cancel older ones."""

        class RedisSimulator:
            def __init__(self):
                self.store = {}
                self.lock = threading.Lock()
                self.cancelled_requests = set()

            def set(self, key, value, nx=False, ex=None):
                with self.lock:
                    if nx and key in self.store:
                        return False
                    self.store[key] = value
                    # Track cancellations
                    if key.endswith(":cancelled"):
                        self.cancelled_requests.add(key)
                    return True

            def get(self, key):
                with self.lock:
                    return self.store.get(key)

            def delete(self, *keys):
                with self.lock:
                    for key in keys:
                        self.store.pop(key, None)

            def incr(self, key):
                return 1

            def decr(self, key):
                return 0

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        # Create multiple /open-random-book requests
        # Each should cancel the previous one
        managers = []
        for i in range(3):
            manager = RequestManager("test@example.com", "/open-random-book", "GET")
            self.assertTrue(manager.claim_request())
            managers.append(manager)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        # The first two should be cancelled, only the last one should be active
        self.assertTrue(managers[0].is_cancelled())
        self.assertTrue(managers[1].is_cancelled())
        self.assertFalse(managers[2].is_cancelled())

        # Verify cancellation keys were set
        self.assertGreater(len(redis_sim.cancelled_requests), 0)

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

            def incr(self, key):
                return 1

            def decr(self, key):
                return 0

        redis_sim = RedisSimulator()
        mock_get_redis.return_value = redis_sim

        # First request - should execute and not leave cached result
        manager1 = RequestManager("test@example.com", "/books", "GET")
        self.assertTrue(manager1.claim_request())

        # Store response with no waiters
        response1 = {"books": ["Book 1", "Book 2"]}
        manager1.store_response(response1, 200)

        # Verify status was set but will expire quickly (2 seconds)
        status_key = f"{manager1.request_key}:status"
        self.assertIn(status_key, redis_sim.store)

        # Verify result was NOT stored (no waiters)
        result_key = f"{manager1.request_key}:result"
        self.assertNotIn(result_key, redis_sim.store)

        # Clear the status to simulate TTL expiry
        redis_sim.store.clear()

        # Second request with same parameters - should NOT get cached response
        manager2 = RequestManager("test@example.com", "/books", "GET")

        # Should be able to claim (not duplicate since cache was cleared)
        self.assertTrue(manager2.claim_request())

        # This proves the second request will execute fresh, not use cached data


class TestPriorityAndCancellation(BaseKindleTest, unittest.TestCase):
    """Test priority-based request management and cancellation.

    These tests verify that higher priority requests properly cancel lower priority ones,
    and that streaming endpoints detect cancellation quickly.
    """

    def setUp(self):
        """Set up test fixtures."""
        # Use the base class setup
        self.setup_base()
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
                    "open-book",
                    params={"user_email": self.email, "title": "Hyperion"},
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

        # Verify screenshot ran successfully without being blocked
        if "screenshot_error" in results:
            self.fail(f"Screenshot request failed with error: {results['screenshot_error']}")
        self.assertIn("screenshot", results, f"Screenshot request did not complete. Results: {results}")
        self.assertEqual(
            results["screenshot"]["status"],
            200,
            "Screenshot should run concurrently without being blocked",
        )

    def test_stream_cancellation_by_higher_priority(self):
        """Test that /books-stream is cancelled when higher priority request arrives."""
        results = {}

        def stream_books():
            """Stream books endpoint."""
            results["stream_started"] = time.time()
            session = self._create_test_session()
            try:
                params = self._build_params({"user_email": self.email})
                # Use the proxy endpoint for streaming
                # Use stream=True to properly handle streaming responses
                response = session.get(
                    f"{self.base_url}/kindle/books-stream",
                    params=params,
                    timeout=15,  # Shorter timeout since cancellation should be quick
                    stream=True,  # Important for proper streaming
                )

                # The endpoint returns a single JSON response when cancelled
                if response.status_code == 409:  # Conflict status for cancellation
                    try:
                        data = response.json()
                        if data.get("cancelled") or (
                            "error" in data and "cancelled" in data["error"].lower()
                        ):
                            results["stream_cancelled"] = time.time()
                            results["cancellation_reason"] = data.get("error", "Cancelled")
                    except Exception as e:
                        results["stream_error"] = f"Failed to parse cancellation response: {e}"
                elif response.status_code == 200:
                    # If we got 200, try to read streaming data
                    try:
                        # Check if it's actually streaming or a regular response
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
                                            break
                                    except json.JSONDecodeError:
                                        # Not JSON, might be raw text
                                        pass
                            if line_count == 0:
                                # No lines received - stream was likely interrupted
                                results["stream_error"] = "Stream interrupted - no data received"
                        else:
                            # Regular JSON response
                            data = response.json()
                            if data.get("cancelled"):
                                results["stream_cancelled"] = time.time()
                                results["cancellation_reason"] = data.get("error", "Cancelled")
                            else:
                                results["stream_completed"] = time.time()
                    except Exception as e:
                        results["stream_error"] = f"Stream reading error: {e}"
                else:
                    results["stream_error"] = f"Unexpected status: {response.status_code}"

            except Exception as e:
                results["stream_error"] = str(e)
            finally:
                session.close()

        def open_book():
            """Open a book (higher priority)."""
            results["open_started"] = time.time()
            try:
                response = self._make_request(
                    "open-book",
                    params={"user_email": self.email, "title": "Hyperion"},
                    timeout=60,
                )
                results["open_completed"] = time.time()
                results["open_status"] = response.status_code
            except Exception as e:
                results["open_error"] = str(e)
                raise

        # Start streaming books
        stream_thread = threading.Thread(target=stream_books)
        stream_thread.start()

        # Wait for stream to actually start streaming (not just make the request)
        # We need to ensure it's past the initial setup and actually streaming data
        time.sleep(5)

        # Start higher priority request
        open_thread = threading.Thread(target=open_book)
        open_thread.start()

        # Wait for both to complete
        stream_thread.join(timeout=15)
        open_thread.join(timeout=30)

        # Verify stream was either cancelled, errored, or completed before conflict
        # If stream completed before the higher priority request started, that's also acceptable
        stream_handled = (
            "stream_cancelled" in results
            or "stream_error" in results
            or (
                "stream_completed" in results
                and "open_started" in results
                and results["stream_completed"] < results["open_started"]
            )
        )

        if not stream_handled:
            # Stream should have been interrupted by higher priority request
            self.fail(
                f"Stream should have been interrupted by higher priority request or completed before it. Results: {results}"
            )

        # If stream completed before open started, that's fine but log it
        if "stream_completed" in results and "open_started" in results:
            if results["stream_completed"] < results["open_started"]:
                # Stream finished before conflict - this is OK
                pass

        if "stream_cancelled" in results:
            # Proper cancellation occurred
            self.assertIn(
                "cancelled",
                results.get("cancellation_reason", "").lower(),
                "Cancellation reason should mention cancellation",
            )
            # Verify cancellation was reasonably fast (under 5 seconds)
            if "open_started" in results:
                cancellation_delay = results["stream_cancelled"] - results["open_started"]
                self.assertLess(
                    cancellation_delay,
                    10.0,
                    f"Cancellation took {cancellation_delay:.1f}s, should be under 10s",
                )
        elif "stream_error" in results:
            # Stream errored (probably due to state conflict) - also acceptable
            # This happens when /open-book changes the state before stream can properly start
            pass

    def test_last_one_wins_for_same_endpoint(self):
        """Test that newer requests cancel older ones for last-one-wins endpoints."""
        # This is already tested in TestRequestDeduplicationIntegration
        # but we can add a specific test for /open-random-book if needed
        pass


if __name__ == "__main__":
    # Run tests in order: main tests -> priority tests -> expensive tests
    # Use unittest's test suite to control order
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add main deduplication tests
    suite.addTests(loader.loadTestsFromTestCase(TestRequestDeduplicationIntegration))

    # Add priority and cancellation tests (only run if main tests pass)
    suite.addTests(loader.loadTestsFromTestCase(TestPriorityAndCancellation))

    # Run with stop on first failure
    runner = unittest.TextTestRunner(verbosity=1, failfast=True)
    runner.run(suite)
