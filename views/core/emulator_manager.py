import logging
import os
import platform
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from server.utils.request_utils import get_sindarin_email
from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)


class EmulatorManager:
    """
    Manages the lifecycle of Android emulators.

    Note that this model is shared between all users, so don't set any user-specific preferences here.

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

        # Cache for emulator state to avoid repeated ADB queries
        # Maps email to (emulator_id, avd_name, last_check_time)
        self._emulator_cache = {}

    def is_emulator_running(self, email: str) -> bool:
        """Check if an emulator is currently running for a specific email."""
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
            if result.returncode != 0:
                return False

            lines = [
                line.strip() for line in result.stdout.splitlines() if line.strip().startswith("emulator-")
            ]

            # Corroborate with the profiles index
            if lines:
                vnc_manager = VNCInstanceManager.get_instance()
                emulator_id = vnc_manager.get_emulator_id(email)
                if emulator_id and any(emulator_id in line for line in lines):
                    return True
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is running, assuming it's not running")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")
            return False

    def stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Public method for external use.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        success = self._stop_specific_emulator(emulator_id)
        if success:
            # Clear cache for this emulator
            for email, (cached_id, _, _) in list(self._emulator_cache.items()):
                if cached_id == emulator_id:
                    del self._emulator_cache[email]
                    logger.info(f"Cleared cache for emulator {emulator_id} (email: {email})")
                    break
        return success

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

    def start_emulator_with_retries(self, email: str) -> bool:
        """
        Start the specified AVD in headless mode.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # Check if we have cached emulator info for this email
            if email in self._emulator_cache:
                emulator_id, avd_name, cache_time = self._emulator_cache[email]
                logger.info(f"Found cached emulator info for {email}: {emulator_id}, {avd_name}")

                # Verify the cached emulator is still running
                if self.emulator_launcher._verify_emulator_running(emulator_id, email):
                    logger.info(f"Cached emulator {emulator_id} is still running for {email}")
                    return True
                else:
                    logger.info(f"Cached emulator {emulator_id} is no longer running, removing from cache")
                    del self._emulator_cache[email]

            # First check for stale cache entries and clean them before launching
            avd_name = self.emulator_launcher._extract_avd_name_from_email(email)
            if avd_name and avd_name in self.emulator_launcher.running_emulators:
                emulator_id, display_num = self.emulator_launcher.running_emulators[avd_name]

                # Verify the emulator is actually running via adb devices
                if not self.emulator_launcher._verify_emulator_running(emulator_id, email):
                    # Emulator not actually running according to adb, remove from cache
                    logger.info(
                        f"Cached emulator {emulator_id} for AVD {avd_name} not found in adb devices, removing from cache before launch"
                    )
                    # Remove stale cache entry before launching
                    del self.emulator_launcher.running_emulators[avd_name]

            # Directly check adb devices before launching to know the initial state
            try:
                devices_before = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                logger.info(f"ADB devices before launch: {devices_before.stdout.strip()}")
            except Exception as e:
                logger.error(f"Error checking ADB devices before launch: {e}")

            # Now use the Python-based launcher
            success, emulator_id, display_num = self.emulator_launcher.launch_emulator(email)

            if success:
                logger.info(f"Emulator {emulator_id} launched successfully on display :{display_num}")

                # Cache the emulator info to avoid repeated ADB queries
                self._emulator_cache[email] = (emulator_id, avd_name, time.time())
                logger.info(f"Cached emulator info for {email}: {emulator_id}, {avd_name}")

                # For macOS simplified mode, also ensure the profile has the proper AVD name
                if self.use_simplified_mode and avd_name:
                    from views.core.avd_profile_manager import AVDProfileManager

                    profile_manager = AVDProfileManager.get_instance()
                    if email in profile_manager.profiles_index:
                        profile = profile_manager.profiles_index[email]
                        if not profile.get("avd_name"):
                            profile["avd_name"] = avd_name
                            profile_manager._save_profiles_index()
                            logger.info(
                                f"Updated profile with AVD name {avd_name} for {email} in simplified mode"
                            )

                # Check adb devices immediately after launch to see if it's detected
                try:
                    devices_after = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    logger.info(f"ADB devices immediately after launch: {devices_after.stdout.strip()}")

                    # Check if our emulator ID appears in the output
                    if emulator_id in devices_after.stdout:
                        logger.info(f"Emulator {emulator_id} is visible to ADB immediately after launch")
                    else:
                        logger.warning(
                            f"Emulator {emulator_id} is NOT visible to ADB immediately after launch"
                        )
                except Exception as e:
                    logger.error(f"Error checking ADB devices after launch: {e}")

                # Wait for emulator to boot with active polling (should take ~7-8 seconds)
                logger.info("Waiting for emulator to boot...")
                deadline = time.time() + 30  # 30 seconds timeout

                # Active polling approach - check every second and log consistently
                check_count = 0
                last_check_time = 0
                while time.time() < deadline:
                    current_time = time.time()

                    # Ensure we're not logging more than once per second
                    if current_time - last_check_time >= 1.0:
                        check_count += 1
                        last_check_time = current_time

                        # Log each check with timestamp
                        logger.info(f"Checking if emulator is ready for {email} (check #{check_count})")

                        # Check if emulator is ready through the launcher
                        if self.emulator_launcher.is_emulator_ready(email):
                            return True

                logger.error(
                    f"Timeout waiting for emulator to boot for {email} after 30 seconds and {check_count} checks"
                )
                return False
            else:
                logger.error(f"Failed to launch emulator")
                return False

        except Exception as e:
            logger.error(f"Error starting emulator: {e}")
            return False
