"""Integration tests for concurrent request handling.

This test verifies that the server properly handles multiple concurrent users
performing realistic workflows simultaneously.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import requests

from tests.test_base import BaseKindleTest

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Test configuration
TEST_USERS = [
    "kindle@solreader.com",
    "sam@solreader.com",
]


class ConcurrentRequestsTester(BaseKindleTest):
    """Test concurrent request handling with realistic user workflows."""

    def __init__(self):
        """Initialize the tester."""
        super().__init__()
        self.setup_base()  # Initialize session and other base attributes
        self.results = {}
        self.timing_data = {}
        self.lock = threading.Lock()

    def make_request(self, user_email: str, endpoint: str, step_name: str) -> Dict:
        """Make a single request and track timing."""
        start_time = time.time()

        try:
            # Build request parameters
            params = self._build_params({"user_email": user_email})

            # Determine method based on endpoint
            if "/shutdown" in endpoint:
                # Shutdown requires POST
                response = self.session.post(
                    f"{self.base_url}/kindle{endpoint}",
                    params=params,
                    timeout=120,
                )
            else:
                # Everything else uses GET
                response = self.session.get(
                    f"{self.base_url}/kindle{endpoint}",
                    params=params,
                    timeout=120,
                )

            end_time = time.time()
            duration = end_time - start_time

            result = {
                "step": step_name,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "duration": duration,
                "response_size": len(response.text) if response.text else 0,
            }

            # Check for deduplication headers
            if "X-Deduplication-Status" in response.headers:
                result["dedup_status"] = response.headers["X-Deduplication-Status"]

            # Store timing data for concurrency analysis
            with self.lock:
                key = f"{user_email}_{step_name}_{time.time()}"
                self.timing_data[key] = {
                    "start": start_time,
                    "end": end_time,
                    "user": user_email,
                    "step": step_name,
                }

            return result

        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time

            logger.error(f"Error in {step_name} for {user_email}: {e}")

            return {
                "step": step_name,
                "endpoint": endpoint,
                "status_code": -1,
                "duration": duration,
                "error": str(e),
            }

    def test_simultaneous_operations(self):
        """Test that specific operations can happen simultaneously for different users.

        This test ensures that both users can:
        - Load books at the same time
        - Open books at the same time
        - Navigate at the same time
        """
        logger.info(f"\n=== Testing simultaneous operations ===")

        operations = [
            ("Load Books", "/books"),
            ("Open Random Book", "/open-random-book"),
            ("Navigate forward", "/navigate?navigate=0&preview=1"),
            ("Shutdown", "/shutdown"),
        ]

        for op_name, endpoint in operations:
            logger.info(f"\nTesting simultaneous: {op_name}")

            with ThreadPoolExecutor(max_workers=len(TEST_USERS)) as executor:
                futures = []

                # Both users perform the same operation simultaneously
                for user in TEST_USERS:
                    future = executor.submit(self.make_request, user, endpoint, op_name)
                    futures.append((future, user))

                # Collect results
                results = []
                for future, user in futures:
                    try:
                        result = future.result(timeout=60)
                        results.append(result)
                        if result["status_code"] == 200:
                            logger.info(f"✅ {user} - {op_name} successful ({result['duration']:.2f}s)")
                        else:
                            logger.error(
                                f"❌ {user} - {op_name} failed: {result.get('error', 'Unknown error')}"
                            )
                    except Exception as e:
                        logger.error(f"❌ {user} - {op_name} exception: {e}")

                # Verify operations were concurrent
                if len(results) == 2 and all(r["status_code"] == 200 for r in results):
                    # Check if operations overlapped in time
                    overlap = self.check_overlap_for_operation(op_name)
                    if overlap:
                        logger.info(f"✅ Confirmed: Both users performed '{op_name}' concurrently")
                    else:
                        logger.warning(f"⚠️ Operations may not have been concurrent")

                # Small delay between different operations
                time.sleep(2)

    def check_overlap_for_operation(self, operation: str) -> bool:
        """Check if a specific operation was performed concurrently by different users."""
        op_timings = []

        with self.lock:
            for key, timing in self.timing_data.items():
                if timing["step"] == operation:
                    op_timings.append(timing)

        # Check if we have timings from both users
        users_involved = set(t["user"] for t in op_timings)
        if len(users_involved) < 2:
            return False

        # Check for time overlap between different users
        for i, t1 in enumerate(op_timings):
            for t2 in op_timings[i + 1 :]:
                if t1["user"] != t2["user"]:
                    # Check if they overlapped
                    if (t1["start"] <= t2["start"] <= t1["end"]) or (t2["start"] <= t1["start"] <= t2["end"]):
                        return True

        return False

    def verify_concurrency(self):
        """Verify that requests from different users actually ran concurrently."""
        logger.info(f"\n=== Concurrency Verification ===")

        overlapping_pairs = 0
        timing_list = list(self.timing_data.values())

        for i, t1 in enumerate(timing_list):
            for t2 in timing_list[i + 1 :]:
                # Only check overlaps between different users
                if t1["user"] != t2["user"]:
                    # Check if they overlapped in time
                    if (t1["start"] <= t2["start"] <= t1["end"]) or (t2["start"] <= t1["start"] <= t2["end"]):
                        overlapping_pairs += 1

        logger.info(f"Found {overlapping_pairs} overlapping request pairs between different users")

        if overlapping_pairs > 0:
            logger.info("✅ Confirmed: Users were making requests concurrently")
        else:
            logger.warning("⚠️ No concurrent requests detected between users")

        # Show which operations were concurrent
        concurrent_ops = set()
        for i, t1 in enumerate(timing_list):
            for t2 in timing_list[i + 1 :]:
                if t1["user"] != t2["user"]:
                    if (t1["start"] <= t2["start"] <= t1["end"]) or (t2["start"] <= t1["start"] <= t2["end"]):
                        concurrent_ops.add((t1["step"], t2["step"]))

        if concurrent_ops:
            logger.info("\nConcurrent operations detected:")
            for op1, op2 in concurrent_ops:
                logger.info(f"  • {op1} ↔ {op2}")


def main():
    """Run concurrent request test."""
    tester = ConcurrentRequestsTester()

    try:
        # Test that specific operations can happen simultaneously
        tester.test_simultaneous_operations()

        # Verify that requests actually ran concurrently
        tester.verify_concurrency()

        logger.info("\n✅ Concurrent request test completed")

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        raise


if __name__ == "__main__":
    main()
