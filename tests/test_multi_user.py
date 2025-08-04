"""
Comprehensive multi-user test that covers all scenarios.

This test:
1. Starts two users' emulators
2. Checks port forwarding integrity
3. Tests the snapshot-check endpoint (to verify fixes)
4. Performs basic operations if authenticated
5. Shuts down emulators independently
"""

import json
import logging
import subprocess
import time
from typing import Dict, List, Optional, Tuple

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Test configuration
BASE_URL = "http://localhost:4098"
USER_A_EMAIL = "test_user_a@solreader.com"
USER_B_EMAIL = "test_user_b@solreader.com"

# Book ASINs to test with
BOOK_A_ASIN = "B09XWD3C3K"  # Example ASIN for user A
BOOK_B_ASIN = "B08N5LPQY1"  # Example ASIN for user B


class MultiUserTester:
    def __init__(self):
        self.session = requests.Session()
        self.user_a_status = {"email": USER_A_EMAIL, "initialized": False, "authenticated": False}
        self.user_b_status = {"email": USER_B_EMAIL, "initialized": False, "authenticated": False}
        self.test_results = {"passed": [], "failed": [], "warnings": []}

    def get_staff_token(self):
        """Get and set staff authentication token."""
        response = self.session.get(f"{BASE_URL}/staff-auth", params={"auth": "1"})
        response.raise_for_status()
        token = response.json()["token"]
        self.session.cookies.set("staff_token", token)
        logger.info("Obtained staff token")

    def check_adb_devices(self) -> Tuple[Dict[str, str], List[str]]:
        """Check which emulators are currently running and their port forwards."""
        devices = {}
        port_forwards = {}

        # Get list of devices
        result = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if "emulator-" in line and "device" in line:
                parts = line.split()
                device_id = parts[0]
                # Try to find AVD name in the line
                avd_name = "unknown"
                if "avd:" in line:
                    avd_start = line.index("avd:") + 4
                    avd_parts = line[avd_start:].split()
                    if avd_parts:
                        avd_name = avd_parts[0]
                devices[device_id] = avd_name

                # Get port forwards for this device
                try:
                    result = subprocess.run(
                        ["adb", "-s", device_id, "forward", "--list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    forwards = result.stdout.strip().splitlines()
                    port_forwards[device_id] = forwards
                except Exception as e:
                    logger.error(f"Error checking port forwards for {device_id}: {e}")
                    port_forwards[device_id] = []

        return devices, port_forwards

    def log_system_state(self, phase: str):
        """Log the current system state for debugging."""
        logger.info(f"\n{'='*60}")
        logger.info(f"SYSTEM STATE - {phase}")
        logger.info(f"{'='*60}")

        # Check running emulators and port forwards
        devices, port_forwards = self.check_adb_devices()
        logger.info(f"Running emulators: {len(devices)}")
        for device_id, avd_name in devices.items():
            logger.info(f"  - {device_id} (AVD: {avd_name})")
            if device_id in port_forwards:
                for forward in port_forwards[device_id]:
                    logger.info(f"      {forward}")

        # Check active emulators via API
        response = self.session.get(f"{BASE_URL}/emulators/active")
        if response.status_code == 200:
            active = response.json()
            logger.info(f"Active emulators (API): {active.get('count', 0)}")
            for emulator in active.get("emulators", []):
                logger.info(f"  - {emulator}")

        logger.info(f"{'='*60}\n")

    def auth_user(self, email: str) -> Dict:
        """Authenticate a user and start their emulator."""
        logger.info(f"Authenticating {email}...")

        params = {"sindarin_email": email, "user_email": email}
        response = self.session.get(f"{BASE_URL}/auth", params=params)

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

    def test_snapshot_check(self, email: str) -> bool:
        """Test the snapshot-check endpoint for a user."""
        logger.info(f"Testing snapshot-check for {email}...")

        params = {"email": email}
        response = self.session.get(f"{BASE_URL}/snapshot-check", params=params)

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

        params = {"sindarin_email": email, "user_email": email, "action": "home"}
        response = self.session.get(f"{BASE_URL}/navigate", params=params)

        if response.status_code != 200:
            logger.error(f"Failed to navigate home for {email}")
            self.test_results["failed"].append(f"Navigation failed for {email}")
            return False

        self.test_results["passed"].append(f"Navigation successful for {email}")
        return True

    def open_book(self, email: str, asin: str) -> bool:
        """Open a book for a user (if authenticated)."""
        user_status = self.user_a_status if email == USER_A_EMAIL else self.user_b_status

        if not user_status["authenticated"]:
            logger.info(f"Skipping book open for {email} - not authenticated")
            self.test_results["warnings"].append(f"Skipped book open for {email} - not authenticated")
            return True

        logger.info(f"Opening book {asin} for {email}...")

        json_data = {"sindarin_email": email, "user_email": email, "asin": asin}
        response = self.session.post(f"{BASE_URL}/open-book", json=json_data)

        if response.status_code != 200:
            logger.warning(f"Failed to open book for {email}")
            self.test_results["warnings"].append(f"Book open failed for {email}")
            return False

        self.test_results["passed"].append(f"Book opened for {email}")
        return True

    def shutdown_user(self, email: str) -> bool:
        """Shutdown a user's emulator."""
        logger.info(f"Shutting down {email}...")

        json_data = {"sindarin_email": email, "user_email": email}
        response = self.session.post(f"{BASE_URL}/shutdown", json=json_data)

        if response.status_code != 200:
            logger.error(f"Failed to shutdown {email}: {response.text}")
            self.test_results["failed"].append(f"Shutdown failed for {email}")
            return False

        logger.info(f"Shutdown successful for {email}")
        self.test_results["passed"].append(f"Shutdown successful for {email}")
        return True

    def verify_port_forwards(
        self, before_state: Dict[str, List[str]], after_state: Dict[str, List[str]], operation: str
    ) -> bool:
        """Verify that port forwards remain intact after an operation."""
        all_good = True

        for device_id, original_forwards in before_state.items():
            if device_id in after_state:
                current_forwards = after_state[device_id]
                original_set = set(original_forwards)
                current_set = set(current_forwards)

                # Check if any forwards were lost
                lost_forwards = original_set - current_set
                if lost_forwards:
                    logger.warning(
                        f"⚠️  Lost port forwards for {device_id} after {operation}: {lost_forwards}"
                    )
                    self.test_results["failed"].append(f"Lost port forwards after {operation}")
                    all_good = False
                else:
                    logger.info(f"✅ Port forwards intact for {device_id} after {operation}")

        if all_good:
            self.test_results["passed"].append(f"Port forwards intact after {operation}")

        return all_good

    def run_test(self):
        """Run the comprehensive multi-user test."""
        try:
            # Get staff token
            self.get_staff_token()

            # Initial state
            self.log_system_state("INITIAL")

            # Phase 1: Start User A
            logger.info("\n=== PHASE 1: Start User A ===")
            self.auth_user(USER_A_EMAIL)
            time.sleep(15)  # Wait for emulator to start

            # Get port forwards after User A
            _, user_a_forwards = self.check_adb_devices()
            self.log_system_state("AFTER USER A START")

            # Phase 2: Start User B
            logger.info("\n=== PHASE 2: Start User B ===")
            self.auth_user(USER_B_EMAIL)
            time.sleep(15)  # Wait for emulator to start

            # Get port forwards after User B
            _, user_b_forwards = self.check_adb_devices()
            self.log_system_state("AFTER USER B START")

            # Verify port forwards remain intact
            self.verify_port_forwards(user_a_forwards, user_b_forwards, "User B start")

            # Phase 3: Test snapshot-check for both users
            logger.info("\n=== PHASE 3: Test Snapshot Check ===")
            if self.test_snapshot_check(USER_A_EMAIL):
                _, after_a_snapshot = self.check_adb_devices()
                self.verify_port_forwards(user_b_forwards, after_a_snapshot, "User A snapshot check")

            if self.test_snapshot_check(USER_B_EMAIL):
                _, after_b_snapshot = self.check_adb_devices()
                self.verify_port_forwards(
                    after_a_snapshot if "after_a_snapshot" in locals() else user_b_forwards,
                    after_b_snapshot,
                    "User B snapshot check",
                )

            # Phase 4: Navigation (if authenticated)
            logger.info("\n=== PHASE 4: Navigation ===")
            self.navigate_home(USER_A_EMAIL)
            time.sleep(2)
            self.navigate_home(USER_B_EMAIL)

            # Phase 5: Open books (if authenticated)
            logger.info("\n=== PHASE 5: Open Books ===")
            self.open_book(USER_A_EMAIL, BOOK_A_ASIN)
            time.sleep(2)
            self.open_book(USER_B_EMAIL, BOOK_B_ASIN)

            # Phase 6: Shutdown User A
            logger.info("\n=== PHASE 6: Shutdown User A ===")
            self.shutdown_user(USER_A_EMAIL)
            time.sleep(5)

            # Verify User B still running
            devices, _ = self.check_adb_devices()
            if len(devices) > 0:
                logger.info("✅ User B still running after User A shutdown")
                self.test_results["passed"].append("User B survived User A shutdown")
            else:
                logger.error("❌ User B was affected by User A shutdown")
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


def main():
    """Run the comprehensive multi-user test."""
    tester = MultiUserTester()
    tester.run_test()


if __name__ == "__main__":
    main()
