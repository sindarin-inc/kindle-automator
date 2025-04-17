import logging
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

    def extract_email_from_avd_name(self, avd_name: str) -> Optional[str]:
        """
        Try to extract an email from an AVD name.
        This is an approximate reverse of get_avd_name_from_email.

        Args:
            avd_name: The AVD name to parse

        Returns:
            Optional[str]: Extracted email or None if pattern doesn't match
        """
        if not avd_name.startswith("KindleAVD_"):
            return None

        # Extract the email part
        email_part = avd_name[len("KindleAVD_") :]

        # This is imperfect since we can't know where . vs _ were originally
        # But for simple checking it should be sufficient
        return email_part

    def normalize_email_for_avd(self, email: str) -> str:
        """
        Normalize an email address to be used in an AVD name.

        Args:
            email: Email address to normalize

        Returns:
            str: Normalized email suitable for AVD name
        """
        return email.replace("@", "_").replace(".", "_")

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
        # Get all running emulators
        running_emulators = self.map_running_emulators()

        if not running_emulators:
            logger.debug(f"No running emulators found for email: {email}")
            logger.debug(f"Running emulators: {running_emulators}")
            # Get the AVD name for this email from profiles_index or generate a standard one
            avd_name = None
            if profiles_index and email in profiles_index:
                avd_name = profiles_index.get(email)
            return False, None, avd_name

        # First try the exact AVD name match based on email
        avd_name = None
        if profiles_index and email in profiles_index:
            avd_name = profiles_index.get(email)
            if avd_name and avd_name in running_emulators:
                emulator_id = running_emulators[avd_name]
                logger.info(f"Found exact AVD match: {avd_name} running on {emulator_id} for email {email}")
                return True, emulator_id, avd_name

        # If not found, look for any AVD name that might contain the normalized email
        normalized_email = self.normalize_email_for_avd(email)
        for running_avd_name, emulator_id in running_emulators.items():
            if normalized_email in running_avd_name:
                logger.info(
                    f"Found partial AVD match: {running_avd_name} running on {emulator_id} for email {email}"
                )
                return True, emulator_id, running_avd_name

        # No running emulator found for this email
        logger.debug(f"No running emulator found matching email: {email}")
        return False, None, avd_name

    def _get_avd_name_for_emulator(self, emulator_id: str, current_profile=None) -> Optional[str]:
        """
        Get the AVD name for a running emulator.

        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')
            current_profile: Optional current profile for quick lookup

        Returns:
            Optional[str]: The AVD name or None if not found
        """
        try:
            # First check current profile if we have a matching emulator ID
            if current_profile and current_profile.get("emulator_id") == emulator_id:
                avd_name = current_profile.get("avd_name")
                if avd_name:
                    logger.info(f"Found AVD {avd_name} in current profile for emulator {emulator_id}")
                    return avd_name

            # Use adb to get the AVD name via shell getprop with a short timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "avd", "name"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,  # Very short timeout to avoid hanging
            )

            if result.returncode == 0 and result.stdout.strip():
                # Clean the AVD name - remove any newlines or trailing OK messages
                raw_name = result.stdout.strip()

                # Clean the name - sometimes it comes with "OK" suffix or newlines
                if "\n" in raw_name:
                    # Split by newline and take the first part that's not empty
                    parts = [p.strip() for p in raw_name.split("\n") if p.strip()]
                    if parts:
                        clean_name = parts[0]
                        logger.info(f"Cleaned AVD name from '{raw_name}' to '{clean_name}'")
                        avd_name = clean_name
                    else:
                        avd_name = raw_name  # Fallback to raw if no good parts
                else:
                    avd_name = raw_name

                # Further cleanup - remove trailing "OK" which sometimes appears
                if avd_name.endswith(" OK") or avd_name.endswith("\nOK"):
                    avd_name = avd_name.replace(" OK", "").replace("\nOK", "")
                    logger.info(f"Removed trailing 'OK' from AVD name: {avd_name}")

                logger.info(f"Got AVD name '{avd_name}' directly from emulator {emulator_id}")
                return avd_name

            # Alternative approach - try to get product.device property with short timeout
            result = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "getprop",
                    "ro.build.product",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0 and result.stdout.strip():
                # This gives us the device name (e.g., 'pixel'), not the AVD name
                device_name = result.stdout.strip()
                logger.info(f"Got device name {device_name} for emulator {emulator_id}")

                # If we have a current profile and there's only one entry, use that
                if current_profile:
                    avd_name = current_profile.get("avd_name")
                    if avd_name:
                        logger.info(f"Using current profile AVD {avd_name} for emulator {emulator_id}")
                        return avd_name
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout getting AVD name for emulator {emulator_id}")
        except Exception as e:
            logger.error(f"Error getting AVD name for emulator {emulator_id}: {e}")

        return None

    def scan_for_avds_with_emails(self, profiles_index: Dict = None) -> Dict[str, str]:
        """
        Scan all running AVDs to find ones with email patterns in their names.
        This helps to discover and register email-to-AVD mappings automatically.

        Args:
            profiles_index: Optional dictionary for updating with discovered mappings

        Returns:
            Dict[str, str]: Dictionary mapping emails to AVD names
        """
        # First get all running emulators
        running_emulators = self.map_running_emulators()

        discovered_mappings = {}

        # Check each AVD name for email patterns
        for avd_name in running_emulators.keys():
            email_part = self.extract_email_from_avd_name(avd_name)
            if email_part:
                logger.info(f"Found email pattern in AVD name: {avd_name} -> {email_part}")
                discovered_mappings[email_part] = avd_name

                # Also update profiles index if provided and this mapping is new
                if profiles_index is not None and email_part not in profiles_index:
                    logger.info(f"Adding new email-to-AVD mapping: {email_part} -> {avd_name}")
                    profiles_index[email_part] = avd_name

        return discovered_mappings

    def map_running_emulators(self) -> Dict[str, str]:
        """
        Map running emulators to their device IDs.
        This method never kills or restarts the ADB server if it's already running properly.
        It only starts the server if the initial version check indicates issues.

        Returns:
            Dict[str, str]: Mapping of emulator names to device IDs
        """
        running_emulators = {}

        try:
            # Try a faster check first
            logger.debug("Checking for running emulators")

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
                    if version_check.returncode == 0:
                        # Server is already running correctly, no need to restart it
                        logger.debug("ADB server is running correctly, skipping restart")
                    else:
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
            if not hasattr(locals(), "result") or result.returncode != 0:
                error_msg = (
                    f"Failed to get devices list after multiple attempts: {result.stderr}/{result.stdout}"
                )
                logger.error(error_msg)
                # Log the error but return empty dict instead of raising exception
                # This prevents unnecessary errors when the emulator is actually running
                logger.debug("Returning empty emulator list rather than raising exception")
                return running_emulators

            # Parse output to get emulator IDs
            lines = result.stdout.strip().split("\n")

            logger.debug(f"Raw adb devices output: {result.stdout}")

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

                        logger.debug(f"Found emulator device {emulator_id} in state: {device_state}")

                        # Only proceed if the emulator device is actually available (not 'offline')
                        if device_state != "offline":
                            # Query emulator for AVD name with timeout
                            avd_name = self._get_avd_name_for_emulator(emulator_id)
                            if avd_name:
                                running_emulators[avd_name] = emulator_id

                                # If this AVD name has an email pattern, we might be able to extract the email
                                extracted_email = self.extract_email_from_avd_name(avd_name)
                                if extracted_email:
                                    logger.info(
                                        f"Found AVD with email pattern: {avd_name} -> {extracted_email}"
                                    )
                                    # Handle mapping in the caller
                            else:
                                logger.warning(f"Could not determine AVD name for emulator {emulator_id}")
                        else:
                            logger.warning(f"Emulator {emulator_id} is in 'offline' state - skipping")

            # Enhanced debug info
            if all_devices:
                logger.debug(f"All detected devices: {all_devices}")
                logger.debug(f"Total devices: {len(all_devices)}, Emulators: {emulator_count}")

            # Log emulator mapping results for debugging
            if running_emulators:
                logger.info(f"Found running emulators: {running_emulators}")
            else:
                logger.info("No running emulators found")

            return running_emulators
        except subprocess.TimeoutExpired:
            logger.warning("Timeout mapping running emulators")
            return running_emulators
        except Exception as e:
            logger.error(f"Error mapping running emulators: {e}")
            return running_emulators
