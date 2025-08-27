"""
Comprehensive multi-user test that covers all scenarios.

This test:
1. Starts two users' emulators
2. Tests the snapshot-check endpoint (to verify fixes)
3. Performs basic operations if authenticated
4. Shuts down emulators independently
"""

import json
import logging
import os
import time
from typing import Dict

try:
    from tests.test_base import STAGING, BaseKindleTest
except ImportError:
    # When running as a script
    from test_base import STAGING, BaseKindleTest

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Test configuration - Get users from environment variables
# For multi-user testing, we need two distinct users
USER_A_EMAIL = os.environ.get("CONCURRENT_USER_A", "kindle@solreader.com")
USER_B_EMAIL = os.environ.get("CONCURRENT_USER_B", "sam@solreader.com")

logger.info(f"Multi-user test configuration: User A={USER_A_EMAIL}, User B={USER_B_EMAIL}")

# Note: Using /open-random-book instead of hardcoded ASINs for more flexible testing


class MultiUserTester(BaseKindleTest):
    def setup_test_state(self):
        # Initialize test state
        self.setup_base()
        self.user_a_status = {"email": USER_A_EMAIL, "initialized": False, "authenticated": False}
        self.user_b_status = {"email": USER_B_EMAIL, "initialized": False, "authenticated": False}
        self.test_results = {"passed": [], "failed": [], "warnings": []}

    def log_system_state(self, phase: str):
        """Log the current system state for debugging."""
        logger.info(f"\n{'='*60}")
        logger.info(f"SYSTEM STATE - {phase}")
        logger.info(f"{'='*60}")

        # Check active emulators via API
        response = self._make_request("emulators/active", method="GET")
        if response.status_code == 200:
            active = response.json()
            logger.info(f"Active emulators (API): {active.get('count', 0)}")
            for emulator in active.get("emulators", []):
                logger.info(f"  - {emulator}")

        logger.info(f"{'='*60}\n")

    def auth_user(self, email: str) -> Dict:
        """Authenticate a user and start their emulator."""
        logger.info(f"Authenticating {email}...")

        params = {"sindarin_email": email, "user_email": email, "staging": STAGING}
        response = self._make_request("auth", params=params, method="GET")

        if response.status_code != 200:
            logger.error(f"Failed to auth {email}: {response.text}")
            self.test_results["failed"].append(f"Auth failed for {email}")
            return {}

        data = response.json()
        logger.info(f"Auth response: {data.get('message', 'Unknown')}")

        # Update user status
        if email == USER_A_EMAIL:
            self.user_a_status["initialized"] = True
            self.user_a_status["authenticated"] = not data.get("manual_login_required", True)
        else:
            self.user_b_status["initialized"] = True
            self.user_b_status["authenticated"] = not data.get("manual_login_required", True)

        return data

    def check_snapshot(self, email: str) -> bool:
        """Test the snapshot-check endpoint for a user."""
        logger.info(f"Testing snapshot-check for {email}...")

        params = {"email": email, "staging": STAGING}
        response = self._make_request("snapshot-check", params=params, method="GET")

        if response.status_code != 200:
            logger.error(f"Snapshot check failed for {email}: {response.status_code}")
            self.test_results["failed"].append(f"Snapshot check failed for {email}")
            return False

        data = response.json()
        logger.info(f"Snapshot check successful for {email}")
        logger.debug(f"Snapshot data: {json.dumps(data, indent=2)}")
        self.test_results["passed"].append(f"Snapshot check passed for {email}")
        return True

    def navigate_home(self, email: str) -> bool:
        """Navigate to home screen for a user (if authenticated)."""
        user_status = self.user_a_status if email == USER_A_EMAIL else self.user_b_status

        if not user_status["authenticated"]:
            logger.info(f"Skipping navigation for {email} - not authenticated")
            self.test_results["warnings"].append(f"Skipped navigation for {email} - not authenticated")
            return True

        logger.info(f"Navigating to home for {email}...")

        params = {"sindarin_email": email, "user_email": email, "action": "home", "staging": STAGING}
        response = self._make_request("navigate", params=params, method="GET")

        if response.status_code != 200:
            logger.error(f"Failed to navigate home for {email}")
            self.test_results["failed"].append(f"Navigation failed for {email}")
            return False

        self.test_results["passed"].append(f"Navigation successful for {email}")
        return True

    def open_book(self, email: str) -> bool:
        """Open a random book for a user (if authenticated)."""
        user_status = self.user_a_status if email == USER_A_EMAIL else self.user_b_status

        if not user_status["authenticated"]:
            logger.info(f"Skipping book open for {email} - not authenticated")
            self.test_results["warnings"].append(f"Skipped book open for {email} - not authenticated")
            return True

        logger.info(f"Opening random book for {email}...")

        # Using open-random-book endpoint for more flexible testing
        params = {"sindarin_email": email, "user_email": email, "staging": STAGING}
        response = self._make_request("open-random-book", params=params, method="GET")

        if response.status_code != 200:
            logger.warning(f"Failed to open random book for {email}")
            self.test_results["warnings"].append(f"Random book open failed for {email}")
            return False

        self.test_results["passed"].append(f"Random book opened for {email}")
        return True

    def shutdown_user(self, email: str) -> bool:
        """Shutdown a user's emulator."""
        logger.info(f"Shutting down {email}...")

        # Using params instead of json for consistency with other endpoints
        params = {"sindarin_email": email, "user_email": email, "staging": STAGING}
        response = self._make_request("shutdown", params=params, method="POST")

        if response.status_code != 200:
            logger.error(f"Failed to shutdown {email}: {response.text}")
            self.test_results["failed"].append(f"Shutdown failed for {email}")
            return False

        logger.info(f"Shutdown successful for {email}")
        self.test_results["passed"].append(f"Shutdown successful for {email}")
        return True

    def run_test(self):
        """Run the comprehensive multi-user test."""
        try:
            # Initialize test state if not already done
            if not hasattr(self, "test_results"):
                self.setup_test_state()

            # Staff token is already set by BaseKindleTest

            # Initial state
            self.log_system_state("INITIAL")

            # Phase 1: Start User A
            logger.info("\n=== PHASE 1: Start User A ===")
            self.auth_user(USER_A_EMAIL)
            time.sleep(15)  # Wait for emulator to start
            self.log_system_state("AFTER USER A START")

            # Phase 2: Start User B
            logger.info("\n=== PHASE 2: Start User B ===")
            self.auth_user(USER_B_EMAIL)
            time.sleep(15)  # Wait for emulator to start
            self.log_system_state("AFTER USER B START")

            # Phase 3: Test snapshot-check for both users
            logger.info("\n=== PHASE 3: Test Snapshot Check ===")
            self.check_snapshot(USER_A_EMAIL)
            self.check_snapshot(USER_B_EMAIL)

            # Phase 4: Navigation (if authenticated)
            logger.info("\n=== PHASE 4: Navigation ===")
            self.navigate_home(USER_A_EMAIL)
            time.sleep(2)
            self.navigate_home(USER_B_EMAIL)

            # Phase 5: Open books (if authenticated)
            logger.info("\n=== PHASE 5: Open Books ===")
            self.open_book(USER_A_EMAIL)
            time.sleep(2)
            self.open_book(USER_B_EMAIL)

            # Phase 6: Shutdown User A
            logger.info("\n=== PHASE 6: Shutdown User A ===")
            self.shutdown_user(USER_A_EMAIL)
            time.sleep(5)

            # Verify User B still running by making a simple request
            try:
                response = self._make_request("screenshot", params={"user_email": USER_B_EMAIL})
                if response.status_code == 200:
                    logger.info("✅ User B still running after User A shutdown")
                    self.test_results["passed"].append("User B survived User A shutdown")
                else:
                    logger.error("❌ User B was affected by User A shutdown")
                    self.test_results["failed"].append("User B affected by User A shutdown")
            except Exception as e:
                logger.error(f"❌ User B was affected by User A shutdown: {e}")
                self.test_results["failed"].append("User B affected by User A shutdown")

            # Phase 7: Shutdown User B
            logger.info("\n=== PHASE 7: Shutdown User B ===")
            self.shutdown_user(USER_B_EMAIL)
            time.sleep(5)

            # Final state
            self.log_system_state("FINAL")

            # Print test summary
            logger.info("\n" + "=" * 60)
            logger.info("TEST SUMMARY")
            logger.info("=" * 60)
            logger.info(f"✅ Passed: {len(self.test_results['passed'])} tests")
            for test in self.test_results["passed"]:
                logger.info(f"   - {test}")

            if self.test_results["warnings"]:
                logger.info(f"\n⚠️  Warnings: {len(self.test_results['warnings'])}")
                for warning in self.test_results["warnings"]:
                    logger.info(f"   - {warning}")

            if self.test_results["failed"]:
                logger.info(f"\n❌ Failed: {len(self.test_results['failed'])} tests")
                for test in self.test_results["failed"]:
                    logger.info(f"   - {test}")
                logger.info("\n❌ Test completed with failures")
            else:
                logger.info("\n✅ All tests passed!")

        except Exception as e:
            logger.error(f"\n❌ Test failed with exception: {e}")
            raise


class TestMultiUserIntegration(MultiUserTester):
    """Pytest test class for multi-user integration tests."""

    def setup_method(self):
        """Setup for each test method."""
        self.setup_test_state()

    def test_multi_user_comprehensive(self):
        """Run the comprehensive multi-user test."""
        self.run_test()


def main():
    """Run the comprehensive multi-user test as a script."""
    tester = MultiUserTester()
    tester.setup_test_state()
    tester.run_test()


if __name__ == "__main__":
    main()
