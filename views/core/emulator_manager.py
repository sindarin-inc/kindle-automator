import logging
import os
import platform
import subprocess
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmulatorManager:
    """
    Manages the lifecycle of Android emulators.
    Handles starting, stopping, and monitoring emulator instances.
    """

    def __init__(self, android_home, avd_dir, host_arch, use_simplified_mode=False):
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.host_arch = host_arch
        self.use_simplified_mode = use_simplified_mode

        # Initialize the Python-based emulator launcher - this is now required
        from server.utils.emulator_launcher import EmulatorLauncher

        self.emulator_launcher = EmulatorLauncher(android_home, avd_dir, host_arch)
        logger.info("Using Python-based emulator launcher")

    def is_emulator_running(self) -> bool:
        """Check if an emulator is currently running."""
        try:
            # Execute with a shorter timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,  # Add a timeout to prevent potential hang
            )

            # More precise check - look for "emulator-" followed by a port number
            if result.returncode == 0:
                return any(line.strip().startswith("emulator-") for line in result.stdout.splitlines())
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is running, assuming it's not running")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")
            return False

    def is_emulator_ready(self) -> bool:
        """Check if an emulator is running and fully booted."""
        try:
            # First check if any device is connected with a short timeout
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

            # More precise check for emulator
            has_emulator = False
            for line in devices_result.stdout.splitlines():
                # Looking for "emulator-XXXX device"
                if line.strip().startswith("emulator-") and "device" in line and not "offline" in line:
                    has_emulator = True
                    break

            if not has_emulator:
                return False

            # Check if boot is completed with a timeout
            boot_completed = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

            return boot_completed.stdout.strip() == "1"
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is ready, assuming it's not ready")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is ready: {e}")
            return False

    def _force_cleanup_emulators(self):
        """Force kill all emulator processes and reset adb."""
        logger.warning("Force cleaning up any running emulators")
        try:
            # Kill all emulator processes forcefully
            subprocess.run(["pkill", "-9", "-f", "emulator"], check=False, timeout=5)

            # Kill all qemu processes too
            subprocess.run(["pkill", "-9", "-f", "qemu"], check=False, timeout=5)

            # No longer force resetting adb server as it can cause issues
            logger.info("Skipping ADB server reset during cleanup")

            logger.info("Emulator cleanup completed")
            return True
        except Exception as e:
            logger.error(f"Error during emulator cleanup: {e}")
            return False

    def _check_running_emulators(self, target_avd_name: str = None) -> dict:
        """
        Check for running emulators and their status.

        Args:
            target_avd_name: Optional AVD name we're looking for

        Returns:
            dict: Status of running emulators, including matching and other emulators
        """
        result = {"any_emulator_running": False, "matching_emulator_id": None, "other_emulators": []}

        try:
            # Get list of running emulators from device discovery
            from views.core.device_discovery import DeviceDiscovery

            device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
            running_emulators = device_discovery.map_running_emulators()
            logger.info(f"Found running emulators: {running_emulators}")

            if running_emulators:
                result["any_emulator_running"] = True

                # Check if our target AVD is running
                if target_avd_name and target_avd_name in running_emulators:
                    result["matching_emulator_id"] = running_emulators[target_avd_name]

                # Identify other running emulators
                for avd_name, emulator_id in running_emulators.items():
                    if not target_avd_name or avd_name != target_avd_name:
                        result["other_emulators"].append(emulator_id)

            return result

        except Exception as e:
            logger.error(f"Error checking running emulators: {e}")
            return result

    def _is_specific_emulator_ready(self, emulator_id: str) -> bool:
        """
        Check if a specific emulator is ready.

        Args:
            emulator_id: The emulator ID to check (e.g. emulator-5554)

        Returns:
            bool: True if the emulator is ready, False otherwise
        """
        try:
            # First check if the device is connected
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            device_connected = False
            for line in devices_result.stdout.strip().split("\n"):
                if emulator_id in line and "device" in line and not "offline" in line:
                    device_connected = True
                    break

            if not device_connected:
                logger.warning(f"Emulator {emulator_id} not found in connected devices")
                return False

            # Check boot completed with specific emulator ID
            boot_completed = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "getprop",
                    "sys.boot_completed",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            logger.info(f"Boot check for {emulator_id}: [{boot_completed.stdout.strip()}]")
            return boot_completed.stdout.strip() == "1"

        except Exception as e:
            logger.error(f"Error checking if emulator {emulator_id} is ready: {e}")
            return False

    def stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Public method for external use.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        return self._stop_specific_emulator(emulator_id)

    def _stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Internal implementation.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Stopping specific emulator: {emulator_id}")

            # First try graceful shutdown
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                check=False,
                timeout=5,
            )

            # Wait briefly for emulator to shut down
            for i in range(10):
                devices_result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if emulator_id not in devices_result.stdout:
                    logger.info(f"Emulator {emulator_id} stopped successfully")
                    return True

                logger.info(f"Waiting for emulator {emulator_id} to stop... ({i+1}/10)")
                time.sleep(1)

            # If still running, force kill
            logger.warning(f"Emulator {emulator_id} didn't stop gracefully, forcing termination")
            return False

        except Exception as e:
            logger.error(f"Error stopping emulator {emulator_id}: {e}")
            return False

    def stop_emulator(self) -> bool:
        """Stop the currently running emulator."""
        # Always preserve emulators when server is stopping
        if self.use_simplified_mode:
            logger.info("Always preserving emulators in simplified mode for faster reconnection")
            return True

        try:
            # First do a quick check if emulator is actually running
            if not self.is_emulator_running():
                logger.info("No emulator running, nothing to stop")
                return True

            # Get list of running emulators from adb for validation
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            # Extract emulator IDs
            emulator_ids = []
            lines = result.stdout.strip().split("\n")
            for line in lines[1:]:  # Skip header
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and "emulator" in parts[0]:
                    emulator_id = parts[0].strip()
                    emulator_ids.append(emulator_id)

            # Stop each emulator using the launcher
            success = True
            for email in list(self.emulator_launcher.running_emulators.keys()):
                logger.info(f"Stopping emulator for {email}")
                if not self.emulator_launcher.stop_emulator(email):
                    logger.warning(f"Failed to stop emulator for {email}")
                    success = False

            # If there are still emulators running according to adb, force kill them
            if emulator_ids:
                logger.warning(
                    f"Launcher reports stopping all emulators, but {len(emulator_ids)} still showing up in adb"
                )
                # Force kill as last resort with pkill
                subprocess.run(["pkill", "-f", "emulator"], check=False, timeout=3)
                time.sleep(1)

            # Final check
            if not self.is_emulator_running():
                logger.info("All emulators stopped successfully")
                return True
            else:
                logger.warning("Failed to completely terminate all emulator processes")
                return False
        except Exception as e:
            logger.error(f"Error stopping emulator: {e}")
            return False

    def start_emulator(self, avd_name: str) -> bool:
        """
        Start the specified AVD in headless mode.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # First check if the AVD actually exists
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            if not os.path.exists(avd_path):
                logger.error(f"Cannot start emulator: AVD {avd_name} does not exist at {avd_path}")
                return False

            # Get email from AVD name using DeviceDiscovery first
            from views.core.device_discovery import DeviceDiscovery

            device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
            email = device_discovery.extract_email_from_avd_name(avd_name)

            # Use the Python-based launcher
            success, emulator_id, display_num = self.emulator_launcher.launch_emulator(avd_name, email)

            if success:
                logger.info(
                    f"Emulator {emulator_id} launched successfully for {avd_name} on display :{display_num}"
                )

                # Wait for emulator to boot
                logger.info("Waiting for emulator to boot...")
                deadline = time.time() + 120  # 120 seconds timeout

                while time.time() < deadline:
                    if self.emulator_launcher.is_emulator_ready(email):
                        logger.info(f"Emulator for {email} is ready")
                        return True

                    time.sleep(1)

                logger.error(f"Timeout waiting for emulator to boot for {email}")
                return False
            else:
                logger.error(f"Failed to launch emulator for {avd_name}")
                return False

        except Exception as e:
            logger.error(f"Error starting emulator: {e}")
            return False
