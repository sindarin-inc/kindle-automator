"""
Post-boot device identifier randomization for Android emulators.
Handles identifiers that can't be set via config or command line.
"""

import logging
import subprocess
from typing import Optional

from server.utils.device_identifier_utils import generate_random_android_id

logger = logging.getLogger(__name__)


class PostBootRandomizer:
    """Handles randomization of device identifiers after emulator boot."""

    def __init__(self, android_home: str):
        self.android_home = android_home

    def randomize_android_id(self, emulator_id: str, new_android_id: Optional[str] = None) -> bool:
        """
        Randomize the Android ID on a running emulator.

        The Android ID is stored in the secure settings database.
        This requires root access (which emulators have by default).

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')
            new_android_id: Optional specific Android ID to use. If None, generates random.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not new_android_id:
                new_android_id = generate_random_android_id()

            logger.debug(f"Randomizing Android ID to {new_android_id} on {emulator_id}")

            # Wait for device to be fully online if needed
            import time

            max_wait = 10  # seconds
            wait_interval = 0.5  # Check every 500ms
            start_time = time.time()

            while time.time() - start_time < max_wait:
                # Check if device is online
                check_cmd = [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "get-state",
                ]
                check_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)

                if check_result.returncode == 0 and "device" in check_result.stdout.strip():
                    logger.debug(f"Device {emulator_id} is online after {time.time() - start_time:.1f}s")
                    break

                time.sleep(wait_interval)
            else:
                logger.error(f"Device {emulator_id} not online after {max_wait}s", exc_info=True)
                return False

            # First, ensure we have root access
            root_cmd = [
                f"{self.android_home}/platform-tools/adb",
                "-s",
                emulator_id,
                "root",
            ]
            root_result = subprocess.run(root_cmd, capture_output=True, text=True, timeout=5)
            if root_result.returncode != 0:
                logger.error(f"Failed to get root access: {root_result.stderr}", exc_info=True)
                return False

            # Method 1: Try using settings command (Android 8+)
            settings_cmd = [
                f"{self.android_home}/platform-tools/adb",
                "-s",
                emulator_id,
                "shell",
                "settings",
                "put",
                "secure",
                "android_id",
                new_android_id,
            ]

            settings_result = subprocess.run(settings_cmd, capture_output=True, text=True, timeout=5)
            if settings_result.returncode == 0:
                logger.debug(f"Successfully set Android ID via settings command")

                # Verify the change
                verify_cmd = [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "settings",
                    "get",
                    "secure",
                    "android_id",
                ]
                verify_result = subprocess.run(verify_cmd, capture_output=True, text=True, timeout=5)
                if verify_result.returncode == 0:
                    actual_id = verify_result.stdout.strip()
                    if actual_id == new_android_id:
                        logger.debug(f"Verified Android ID is now: {actual_id}")
                        return True
                    else:
                        logger.warning(
                            f"Android ID verification failed. Expected {new_android_id}, got {actual_id}"
                        )
            else:
                logger.warning(f"Settings command failed: {settings_result.stderr}")

            # Method 2: Direct database manipulation (fallback for older Android versions)
            logger.debug("Trying direct database manipulation method")

            # Update the settings database directly
            db_cmd = [
                f"{self.android_home}/platform-tools/adb",
                "-s",
                emulator_id,
                "shell",
                f"sqlite3 /data/data/com.android.providers.settings/databases/settings.db \"UPDATE secure SET value='{new_android_id}' WHERE name='android_id';\"",
            ]

            db_result = subprocess.run(db_cmd, capture_output=True, text=True, timeout=10)
            if db_result.returncode != 0:
                logger.error(f"Failed to update database: {db_result.stderr}", exc_info=True)
                return False

            logger.debug(f"Successfully updated Android ID in database")
            return True

        except Exception as e:
            logger.error(f"Error randomizing Android ID: {e}", exc_info=True)
            return False

    def randomize_system_properties(self, emulator_id: str, properties: dict) -> bool:
        """
        Set system properties on a running emulator.

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')
            properties: Dictionary of properties to set

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.debug(f"Setting system properties on {emulator_id}")

            # Ensure device is rooted
            root_cmd = [
                f"{self.android_home}/platform-tools/adb",
                "-s",
                emulator_id,
                "root",
            ]
            subprocess.run(root_cmd, capture_output=True, text=True, timeout=5)

            success = True
            for prop_name, prop_value in properties.items():
                try:
                    # Set the property
                    cmd = [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "shell",
                        "setprop",
                        prop_name,
                        str(prop_value),
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

                    if result.returncode != 0:
                        logger.warning(f"Failed to set property {prop_name}: {result.stderr}", exc_info=True)
                        success = False
                    else:
                        # Verify it was set
                        verify_cmd = [
                            f"{self.android_home}/platform-tools/adb",
                            "-s",
                            emulator_id,
                            "shell",
                            "getprop",
                            prop_name,
                        ]
                        verify_result = subprocess.run(verify_cmd, capture_output=True, text=True, timeout=5)
                        actual_value = verify_result.stdout.strip()

                        if actual_value == str(prop_value):
                            logger.debug(f"Successfully set {prop_name} = {prop_value}")
                        else:
                            logger.warning(
                                f"Property {prop_name} verification failed. Expected '{prop_value}', got '{actual_value}'"
                            )

                except Exception as e:
                    logger.error(f"Error setting property {prop_name}: {e}", exc_info=True)
                    success = False

            return success

        except Exception as e:
            logger.error(f"Error setting system properties: {e}", exc_info=True)
            return False

    def clear_google_play_services_data(self, emulator_id: str) -> bool:
        """
        Clear Google Play Services data to reset advertising ID and other identifiers.

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.debug(f"Clearing Google Play Services data on {emulator_id}")

            # Clear Google Play Services data
            clear_cmd = [
                f"{self.android_home}/platform-tools/adb",
                "-s",
                emulator_id,
                "shell",
                "pm",
                "clear",
                "com.google.android.gms",
            ]

            result = subprocess.run(clear_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.error(f"Failed to clear Google Play Services data: {result.stderr}", exc_info=True)
                return False

            logger.debug("Successfully cleared Google Play Services data")
            return True

        except Exception as e:
            logger.error(f"Error clearing Google Play Services data: {e}", exc_info=True)
            return False

    def randomize_all_post_boot_identifiers(
        self, emulator_id: str, android_id: Optional[str] = None, device_identifiers: Optional[dict] = None
    ) -> bool:
        """
        Randomize all post-boot identifiers on a running emulator.

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')
            android_id: Optional specific Android ID to use
            device_identifiers: Optional dict of device identifiers to set

        Returns:
            bool: True if all randomizations were successful, False if any failed
        """
        success = True

        # Randomize Android ID
        if not self.randomize_android_id(emulator_id, android_id):
            logger.error("Failed to randomize Android ID", exc_info=True)
            success = False

        # Set system properties if provided
        if device_identifiers:
            # Map our identifier keys to actual Android system properties
            property_mappings = {
                # "ro.serialno": device_identifiers.ro_serialno, # Not working
                # "ro.build.id": device_identifiers.ro_build_id, # Not working
                "ro.product.name": device_identifiers.ro_product_name,
            }

            # Filter out None values
            properties_to_set = {k: v for k, v in property_mappings.items() if v is not None}

            if properties_to_set:
                logger.debug(f"Setting system properties: {properties_to_set}")
                if not self.randomize_system_properties(emulator_id, properties_to_set):
                    logger.warning("Some system properties could not be set")
                    # Don't fail completely, as some properties might be read-only

        # Clear Google Play Services data to reset advertising ID
        if not self.clear_google_play_services_data(emulator_id):
            logger.warning("Failed to clear Google Play Services data (advertising ID may not be reset)")
            # Don't fail completely if this fails, as it's less critical

        return success
