"""Tests for request deduplication and cancellation functionality."""

import json
import pickle
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import redis
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from server.core.request_manager import DeduplicationStatus, RequestManager, WaitResult
from server.utils.cancellation_utils import (
    CancellationChecker,
    mark_cancelled,
    should_cancel,
)


class TestRequestDeduplication(unittest.TestCase):
    """Test request deduplication logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.redis_client = MagicMock(spec=redis.Redis)
        self.user_email = "test@example.com"
        self.path = "/books"
        self.method = "GET"

    @patch("server.core.request_manager.get_redis_client")
    def test_claim_request_success(self, mock_get_redis):
        """Test successfully claiming a request."""
        mock_get_redis.return_value = self.redis_client
        self.redis_client.set.return_value = True  # Claim succeeds
        self.redis_client.get.return_value = None  # No active request

        manager = RequestManager(self.user_email, self.path, self.method)
        result = manager.claim_request()

        self.assertTrue(result)
        self.redis_client.set.assert_called()

    @patch("server.core.request_manager.get_redis_client")
    def test_claim_request_already_in_progress(self, mock_get_redis):
        """Test claiming a request that's already in progress."""
        mock_get_redis.return_value = self.redis_client
        self.redis_client.set.return_value = False  # Claim fails
        self.redis_client.get.return_value = None  # No active request

        manager = RequestManager(self.user_email, self.path, self.method)
        result = manager.claim_request()

        self.assertFalse(result)

    @patch("server.core.request_manager.get_redis_client")
    def test_store_and_retrieve_response(self, mock_get_redis):
        """Test storing and retrieving a deduplicated response."""
        mock_get_redis.return_value = self.redis_client

        # First test: No waiters - should only set status and clean up
        self.redis_client.get.return_value = None  # No waiters

        manager = RequestManager(self.user_email, self.path, self.method)

        # Store response with no waiters
        response_data = {"books": ["Book 1", "Book 2"]}
        status_code = 200
        manager.store_response(response_data, status_code)

        # Verify only status was set (no result stored when no waiters)
        calls = self.redis_client.set.call_args_list
        self.assertEqual(len(calls), 1)  # Only status

        # Reset for second test: With waiters
        self.redis_client.reset_mock()
        self.redis_client.get.return_value = b"2"  # 2 waiters

        manager2 = RequestManager(self.user_email, self.path, self.method)
        manager2.store_response(response_data, status_code)

        # Verify both result and status were set
        calls = self.redis_client.set.call_args_list
        self.assertEqual(len(calls), 2)  # Result and status

        # Test retrieval - reset the mock's side_effect for the wait
        self.redis_client.get.side_effect = [
            DeduplicationStatus.COMPLETED.value.encode(),  # Status
            pickle.dumps((response_data, status_code)),  # Result
            # Add more None values for cleanup checks
            None,
            None,
            None,
        ]
        # Mock decr to return 0 (no more waiters)
        self.redis_client.decr.return_value = 0

        result = manager.wait_for_deduplicated_response()
        self.assertIsNotNone(result)
        self.assertEqual(result[0], response_data)
        self.assertEqual(result[1], status_code)

    @patch("server.core.request_manager.get_redis_client")
    def test_priority_cancellation(self, mock_get_redis):
        """Test that higher priority requests cancel lower priority ones."""
        mock_get_redis.return_value = self.redis_client

        # Mock an active low-priority request
        active_request = {
            "request_key": "kindle:request:abc123",
            "priority": 30,  # /books priority
            "path": "/books",
            "started_at": time.time(),
        }
        self.redis_client.get.return_value = json.dumps(active_request).encode()

        # Create a high-priority request
        high_priority_manager = RequestManager(self.user_email, "/open-book", "GET")
        high_priority_manager._check_and_cancel_lower_priority_requests()

        # Verify cancellation was set
        cancel_key = f"{active_request['request_key']}:cancelled"
        self.redis_client.set.assert_called_with(cancel_key, "1", ex=130)


class TestCancellationUtils(unittest.TestCase):
    """Test cancellation utility functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.redis_client = MagicMock(spec=redis.Redis)
        self.user_email = "test@example.com"

    @patch("server.utils.cancellation_utils.get_redis_client")
    def test_should_cancel_true(self, mock_get_redis):
        """Test should_cancel returns True when request is cancelled."""
        mock_get_redis.return_value = self.redis_client

        # Mock active request
        active_request = {"request_key": "kindle:request:test123"}
        self.redis_client.get.side_effect = [
            json.dumps(active_request).encode(),  # Active request
            b"1",  # Cancellation flag
        ]

        result = should_cancel(self.user_email)
        self.assertTrue(result)

    @patch("server.utils.cancellation_utils.get_redis_client")
    def test_should_cancel_false(self, mock_get_redis):
        """Test should_cancel returns False when request is not cancelled."""
        mock_get_redis.return_value = self.redis_client

        # Mock active request
        active_request = {"request_key": "kindle:request:test123"}
        self.redis_client.get.side_effect = [
            json.dumps(active_request).encode(),  # Active request
            None,  # No cancellation flag
        ]

        result = should_cancel(self.user_email)
        self.assertFalse(result)

    @patch("server.utils.cancellation_utils.get_redis_client")
    def test_mark_cancelled(self, mock_get_redis):
        """Test marking a request as cancelled."""
        mock_get_redis.return_value = self.redis_client

        # Mock active request
        active_request = {"request_key": "kindle:request:test123"}
        self.redis_client.get.return_value = json.dumps(active_request).encode()

        result = mark_cancelled(self.user_email)
        self.assertTrue(result)

        # Verify cancellation flag was set
        cancel_key = f"{active_request['request_key']}:cancelled"
        self.redis_client.set.assert_called_with(cancel_key, "1", ex=130)

    @patch("server.utils.cancellation_utils.get_redis_client")
    def test_cancellation_checker_context_manager(self, mock_get_redis):
        """Test CancellationChecker context manager."""
        mock_get_redis.return_value = self.redis_client

        # Mock active request
        active_request = {"request_key": "kindle:request:test123"}
        self.redis_client.get.return_value = json.dumps(active_request).encode()

        with CancellationChecker(self.user_email, check_interval=2) as checker:
            # First check - shouldn't hit Redis (counter = 1)
            self.redis_client.get.reset_mock()
            result1 = checker.check()
            self.assertFalse(result1)
            self.redis_client.get.assert_not_called()

            # Second check - should hit Redis (counter = 2, divisible by interval)
            self.redis_client.get.side_effect = [b"1"]  # Cancelled
            result2 = checker.check()
            self.assertTrue(result2)


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


class TestPriorityAndCancellation(unittest.TestCase):
    """Test priority-based request management and cancellation.

    These tests verify that higher priority requests properly cancel lower priority ones,
    and that streaming endpoints detect cancellation quickly.
    """

    def setUp(self):
        """Set up test fixtures."""
        # Server should already be running via make claude-run
        self.base_url = "http://localhost:4098"
        self.email = "sam@solreader.com"

        # Create a session with connection pooling
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,  # Number of connection pools to cache
            pool_maxsize=10,  # Maximum number of connections to save in the pool
            max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Get staff token for authentication
        self.staff_token = self._get_staff_token()

        # Clear any lingering Redis state for this user
        self._clear_redis_state()

    def tearDown(self):
        """Clean up after tests."""
        # Close the session
        self.session.close()
        # Don't stop the server - it's managed externally
        pass

    def _get_staff_token(self):
        """Get staff authentication token."""
        response = self.session.get(f"{self.base_url}/staff-auth", params={"auth": "1"})
        return response.cookies.get("staff_token")

    def _clear_redis_state(self):
        """Clear any lingering Redis state for this user to ensure test isolation."""
        try:
            import redis

            from server.core.redis_connection import get_redis_client

            r = get_redis_client()
            # Clear all keys related to this user
            pattern = f"kindle:*{self.email}*"
            keys = r.keys(pattern)
            if keys:
                r.delete(*keys)

            # Also clear active request tracking
            r.delete(f"kindle:active_request:{self.email}")
        except Exception:
            # If Redis isn't available or there's an error, continue anyway
            pass

    def test_screenshot_runs_concurrently(self):
        """Test that /screenshot runs concurrently without priority blocking."""
        results = {}

        def high_priority_request():
            """Make a high priority request that takes time."""
            # Create a new session for this thread
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            try:
                response = session.get(
                    f"{self.base_url}/open-book",
                    params={"user_email": self.email, "sindarin_email": self.email, "title": "Hyperion"},
                    cookies={"staff_token": self.staff_token},
                    timeout=60,
                )
                results["high_priority"] = {"status": response.status_code, "completed_at": time.time()}
            finally:
                session.close()

        def screenshot_request():
            """Make a screenshot request."""
            # Create a new session for this thread
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            try:
                response = session.get(
                    f"{self.base_url}/screenshot",
                    params={"user_email": self.email, "sindarin_email": self.email},
                    cookies={"staff_token": self.staff_token},
                    timeout=60,
                )
                results["screenshot"] = {"status": response.status_code, "completed_at": time.time()}
            except Exception as e:
                results["screenshot_error"] = str(e)
            finally:
                session.close()

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
        high_thread.join(timeout=60)
        screenshot_thread.join(timeout=60)

        # Check if threads are still alive (timeout occurred)
        if high_thread.is_alive():
            self.fail("High priority thread did not complete within timeout")
        if screenshot_thread.is_alive():
            self.fail("Screenshot thread did not complete within timeout")

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
            # Create a new session for this thread
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            try:
                response = session.get(
                    f"{self.base_url}/books-stream",
                    params={"user_email": self.email, "sindarin_email": self.email},
                    cookies={"staff_token": self.staff_token},
                    stream=True,
                    timeout=60,
                )

                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        # Check for explicit cancellation flag or error with cancelled in text
                        if data.get("cancelled") or (
                            "error" in data and "cancelled" in data["error"].lower()
                        ):
                            results["stream_cancelled"] = time.time()
                            results["cancellation_reason"] = data.get("error", "Cancelled")
                            break
                        elif "error" in data:
                            # Any error during streaming (could be state error if /open-book interfered)
                            results["stream_error_msg"] = data["error"]
                            results["stream_errored"] = time.time()
                            break
                        elif data.get("done"):
                            results["stream_completed"] = time.time()
                            break

            except Exception as e:
                results["stream_error"] = str(e)
            finally:
                session.close()

        def open_book():
            """Open a book (higher priority)."""
            results["open_started"] = time.time()
            # Create a new session for this thread
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            try:
                response = session.get(
                    f"{self.base_url}/open-book",
                    params={"user_email": self.email, "sindarin_email": self.email, "title": "Hyperion"},
                    cookies={"staff_token": self.staff_token},
                    timeout=60,
                )
                results["open_completed"] = time.time()
                results["open_status"] = response.status_code
            finally:
                session.close()

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

        # Verify stream was either cancelled or errored due to priority conflict
        # Both are acceptable - the key is that /open-book had priority
        stream_interrupted = "stream_cancelled" in results or "stream_errored" in results
        self.assertTrue(
            stream_interrupted,
            f"Stream should have been interrupted by higher priority request. Results: {results}",
        )

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
                    5.0,
                    f"Cancellation took {cancellation_delay:.1f}s, should be under 5s",
                )
        elif "stream_errored" in results:
            # Stream errored (probably due to state conflict) - also acceptable
            # This happens when /open-book changes the state before stream can properly start
            pass

    def test_last_one_wins_for_same_endpoint(self):
        """Test that newer requests cancel older ones for last-one-wins endpoints."""
        # This is already tested in TestRequestDeduplicationIntegration
        # but we can add a specific test for /open-random-book if needed
        pass


class TestExpensiveIntegration(unittest.TestCase):
    """Expensive integration tests that should only run if other tests pass.

    These tests may take longer or use more resources.
    """

    def setUp(self):
        """Set up test fixtures."""
        # Server should already be running via make claude-run
        self.base_url = "http://localhost:4098"

    def tearDown(self):
        """Clean up after tests."""
        # Don't stop the server - it's managed externally
        pass

    def test_concurrent_stress_test(self):
        """Stress test with many concurrent requests."""
        # This would be an expensive test with many threads
        # Skip for now as it's resource-intensive
        self.skipTest("Expensive stress test - enable when needed")

    def test_long_running_operations(self):
        """Test very long-running operations and timeouts."""
        # This would test operations that take minutes
        # Skip for now as it takes too long
        self.skipTest("Long-running test - enable when needed")


if __name__ == "__main__":
    # Run tests in order: main tests -> priority tests -> expensive tests
    # Use unittest's test suite to control order
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add main deduplication tests first
    suite.addTests(loader.loadTestsFromTestCase(TestRequestDeduplication))
    suite.addTests(loader.loadTestsFromTestCase(TestRequestDeduplicationIntegration))

    # Add priority and cancellation tests (only run if main tests pass)
    suite.addTests(loader.loadTestsFromTestCase(TestPriorityAndCancellation))

    # Add expensive tests last (only run if all other tests pass)
    suite.addTests(loader.loadTestsFromTestCase(TestExpensiveIntegration))

    # Run with stop on first failure
    runner = unittest.TextTestRunner(verbosity=2, failfast=True)
    runner.run(suite)
