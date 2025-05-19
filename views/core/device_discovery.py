import logging
import os
import subprocess
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class DeviceDiscovery:
    """
    Discovers and maps connections between devices, emulators, and AVD profiles.
    Handles detection of running emulators and device ID mapping.
    """

    def __init__(self, android_home, avd_dir):
        self.android_home = android_home
        self.avd_dir = avd_dir

    def find_running_emulator_for_email(
        self, email: str, profiles_index: Dict = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Find a running emulator that's associated with a specific email.

        Args:
            email: The email to find a running emulator for
            profiles_index: Optional dictionary mapping emails to AVD names

        Returns:
            Tuple of (is_running, emulator_id, avd_name) where:
            - is_running: Boolean indicating if a running emulator was found
            - emulator_id: The emulator ID (e.g., 'emulator-5554') if found, None otherwise
            - avd_name: The AVD name associated with the email/emulator if found, None otherwise
        """
        # Force refresh running emulator data from ADB to ensure accuracy
        # This avoids stale emulator information
        running_emulators = self.map_running_emulators()

        if not running_emulators:
            # Get the AVD name for this email from profiles_index or generate a standard one
            avd_name = None
            if profiles_index and email in profiles_index:
                profile_entry = profiles_index.get(email)

                # Handle different formats (backward compatibility)
                if isinstance(profile_entry, str):
                    avd_name = profile_entry
                elif isinstance(profile_entry, dict) and "avd_name" in profile_entry:
                    avd_name = profile_entry["avd_name"]

            return False, None, avd_name

        # First try the exact AVD name match based on email
        avd_name = None
        if profiles_index and email in profiles_index:
            profile_entry = profiles_index.get(email)
            avd_name = profile_entry.get("avd_name")

            if avd_name and avd_name in running_emulators:
                emulator_id = running_emulators[avd_name]
                logger.info(f"Found AVD {avd_name} running on {emulator_id} for email {email}")
                return True, emulator_id, avd_name

        # Never use another user's AVD
        # If we have a specific AVD for this user and it's not running, we should fail
        if avd_name and avd_name not in running_emulators:
            # Return failure to find the user's specific AVD
            return False, None, avd_name

        # No running emulator found for this email
        return False, None, avd_name

    def _get_avd_name_for_emulator(self, emulator_id: str, current_profile=None) -> Optional[str]:
        """
        Get the AVD name for a running emulator using AVD Profile Manager.

        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')
            current_profile: Optional current profile for quick lookup

        Returns:
            Optional[str]: The AVD name or None if not found
        """
        logger.info(f"[DIAG] Getting AVD name for emulator {emulator_id} using AVD Profile Manager")
        try:
            # First check current profile if we have a matching emulator ID
            if current_profile and current_profile.get("emulator_id") == emulator_id:
                avd_name = current_profile.get("avd_name")
                if avd_name:
                    logger.info(f"Found AVD {avd_name} in current profile for emulator {emulator_id}")
                    return avd_name

            # Use AVD Profile Manager to find the AVD name
            from server.utils.request_utils import get_sindarin_email
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager()
            sindarin_email = get_sindarin_email()

            # First check if the current sindarin email has a profile
            if sindarin_email and sindarin_email in avd_manager.profiles_index:
                profile = avd_manager.profiles_index[sindarin_email]
                avd_name = profile.get("avd_name")
                if avd_name:
                    avd_path = os.path.join(avd_manager.avd_dir, f"{avd_name}.avd")
                    if os.path.exists(avd_path):
                        logger.info(
                            f"[DIAG] Found AVD {avd_name} for current sindarin email {sindarin_email}"
                        )
                        return avd_name

            # Fallback: Check each profile to see if it could be running on this emulator
            for email, profile in avd_manager.profiles_index.items():
                avd_name = profile.get("avd_name")
                if avd_name:
                    # Check if this AVD exists and could be our emulator
                    avd_path = os.path.join(avd_manager.avd_dir, f"{avd_name}.avd")
                    if os.path.exists(avd_path):
                        logger.info(f"[DIAG] Found existing AVD {avd_name} for profile {email}")
                        # For now, assume first found AVD is the one
                        return avd_name

            logger.info(f"[DIAG] No AVD found for emulator {emulator_id} in profiles")
        except Exception as e:
            logger.error(f"Error getting AVD name for emulator {emulator_id}: {e}")

        return None

    def map_running_emulators(self) -> Dict[str, str]:
        """
        Map running emulators to their device IDs.
        This method never kills or restarts the ADB server if it's already running properly.
        It only starts the server if the initial version check indicates issues.

        Returns:
            Dict[str, str]: Mapping of emulator names to device IDs
        """
        running_emulators = {}
        logger.info("[DIAG] Starting map_running_emulators")

        try:
            # Try a faster check first
            # Clear any stale device listings first
            try:
                # Use much longer timeouts for production environments
                adb_timeout = 3

                # First check if ADB server is already running
                try:
                    version_check = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "version"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=adb_timeout,
                    )
                    if version_check.returncode != 0:
                        logger.warning(f"ADB server appears to have issues: {version_check.stderr}")
                        # Only attempt to start the server if there are issues
                        logger.debug("Starting ADB server due to issues detected")
                        start_result = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "start-server"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=adb_timeout,
                        )
                        if start_result.returncode == 0:
                            logger.debug("Successfully started ADB server")
                        else:
                            logger.warning(f"ADB start-server returned non-zero: {start_result.stderr}")
                except Exception as ve:
                    logger.warning(f"Error checking ADB version: {ve}")
            except Exception as e:
                logger.warning(f"Error resetting adb server: {e}")

            # Get list of running emulators with retry mechanism
            max_retries = 3
            retry_delay = 5  # seconds
            result = None

            for retry in range(max_retries):
                try:
                    result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )

                    if result.returncode == 0:
                        # Success
                        if retry > 0:
                            logger.info(f"Successfully got devices list after {retry+1} attempts")
                        break
                    else:
                        logger.warning(
                            f"Error getting devices (attempt {retry+1}/{max_retries}): {result.stderr}"
                        )
                        if retry < max_retries - 1:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            # Exponential backoff
                            retry_delay *= 2
                except Exception as e:
                    logger.warning(f"Exception getting devices (attempt {retry+1}/{max_retries}): {e}")
                    if retry < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        # Exponential backoff
                        retry_delay *= 2

            # After retries, check final result
            if not result or result.returncode != 0:
                logger.error(
                    f"Failed to get devices list after multiple attempts: {result.returncode if result else 'unknown'} {result.stderr if result else 'unknown'}"
                )
                # Log the error but return empty dict instead of raising exception
                # This prevents unnecessary errors when the emulator is actually running
                logger.debug("Returning empty emulator list rather than raising exception")
                return running_emulators

            # Parse output to get emulator IDs
            lines = result.stdout.strip().split("\n")
            logger.info(f"[DIAG] ADB devices output: {result.stdout}")

            # Make sure we get valid output - needs at least the header line
            if len(lines) < 1 or "List of devices attached" not in lines[0]:
                logger.error(f"Invalid ADB devices output format: {result.stdout}")
                return running_emulators

            # If we only have the header line, there are no devices
            if len(lines) <= 1:
                return running_emulators

            # Keep track of all emulators for better debugging
            all_devices = []
            emulator_count = 0

            for line in lines[1:]:  # Skip the first line which is the header
                if not line.strip():
                    continue

                parts = line.split("\t")
                if len(parts) >= 2:
                    device_id = parts[0].strip()
                    device_state = parts[1].strip() if len(parts) > 1 else "unknown"
                    all_devices.append((device_id, device_state))

                    if "emulator" in device_id:
                        emulator_count += 1

                    if len(parts) >= 2 and "emulator" in parts[0]:
                        emulator_id = parts[0].strip()
                        device_state = parts[1].strip()
                        logger.info(f"[DIAG] Found emulator {emulator_id} in state: {device_state}")

                        # Only proceed if the emulator device is actually available (not 'offline')
                        if device_state != "offline":
                            # Query AVD name using AVD Profile Manager
                            avd_name = self._get_avd_name_for_emulator(emulator_id)
                            logger.info(f"[DIAG] AVD name for {emulator_id}: {avd_name}")
                            if avd_name:
                                running_emulators[avd_name] = emulator_id
                                logger.info(f"[DIAG] Added to map: {avd_name} -> {emulator_id}")
                        else:
                            logger.warning(f"Emulator {emulator_id} is in 'offline' state - skipping")

            logger.info(f"[DIAG] Final emulator map: {running_emulators}")
            return running_emulators
        except subprocess.TimeoutExpired:
            logger.warning("Timeout mapping running emulators")
            return running_emulators
        except Exception as e:
            logger.error(f"Error mapping running emulators: {e}")
            return running_emulators
