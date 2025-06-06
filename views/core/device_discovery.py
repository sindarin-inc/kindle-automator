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

    def __init__(self, android_home, avd_dir, use_simplified_mode=False):
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.use_simplified_mode = use_simplified_mode

    # Only called by AVDProfileManager
    def find_running_emulator_for_email(
        self, email: str, profiles_index: Dict
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Find a running emulator that's associated with a specific email.

        Args:
            email: The email to find a running emulator for
            profiles_index: Dictionary mapping emails to AVD names

        Returns:
            Tuple of (is_running, emulator_id, avd_name) where:
            - is_running: Boolean indicating if a running emulator was found
            - emulator_id: The emulator ID (e.g., 'emulator-5554') if found, None otherwise
            - avd_name: The AVD name associated with the email/emulator if found, None otherwise
        """
        avd_name = None

        # First check if this email has a profile with an emulator_id stored directly
        if profiles_index and email in profiles_index:
            profile_entry = profiles_index.get(email)

            # Check if profile has emulator_id field
            if isinstance(profile_entry, dict):
                # Get the AVD name
                avd_name = profile_entry.get("avd_name")

                # Check if there's an emulator_id in VNC instance manager
                try:
                    from server.utils.vnc_instance_manager import VNCInstanceManager

                    vnc_manager = VNCInstanceManager.get_instance()
                    stored_emulator_id = vnc_manager.get_emulator_id(email)

                    if stored_emulator_id:
                        # Verify if this emulator is running
                        try:
                            result = subprocess.run(
                                [f"{self.android_home}/platform-tools/adb", "devices"],
                                check=False,
                                capture_output=True,
                                text=True,
                                timeout=3,
                            )
                            if stored_emulator_id in result.stdout and "device" in result.stdout:
                                # Double-check that this emulator is running the correct AVD
                                avd_check_result = subprocess.run(
                                    [f"{self.android_home}/platform-tools/adb", "-s", stored_emulator_id, "emu", "avd", "name"],
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                    timeout=3,
                                )
                                if avd_check_result.returncode == 0:
                                    running_avd = avd_check_result.stdout.strip()
                                    if running_avd != avd_name:
                                        logger.error(
                                            f"CROSS_USER_DEBUG: CRITICAL! VNC says {email} owns {stored_emulator_id}, "
                                            f"but it's running AVD {running_avd} instead of expected {avd_name}"
                                        )
                                        # Clear the incorrect emulator_id
                                        vnc_manager.clear_emulator_id_for_profile(email)
                                        return False, None, avd_name
                                
                                logger.info(
                                    f"Found emulator {stored_emulator_id} from VNC instance for {email} and it's running"
                                )
                                return True, stored_emulator_id, avd_name
                        except Exception as e:
                            logger.warning(
                                f"Error checking if VNC emulator {stored_emulator_id} is running: {e}"
                            )
                except Exception as e:
                    logger.warning(f"Error accessing VNC instance manager: {e}")
            elif isinstance(profile_entry, str):
                avd_name = profile_entry

        # Next, try to get emulator_id from VNC instance manager
        try:
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            vnc_emulator_id = vnc_manager.get_emulator_id(email)

            if vnc_emulator_id:
                # Verify if this emulator is running
                try:
                    result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if vnc_emulator_id in result.stdout and "device" in result.stdout:
                        logger.info(
                            f"Found emulator {vnc_emulator_id} in VNC instance for {email} and it's running"
                        )
                        return True, vnc_emulator_id, avd_name
                except Exception as e:
                    logger.warning(f"Error checking if VNC emulator {vnc_emulator_id} is running: {e}")
        except Exception as e:
            logger.warning(f"Error accessing VNC instance manager: {e}")

        # If we didn't find a running emulator through the direct methods above,
        # fall back to looking up the AVD in running emulators
        running_emulators = self.map_running_emulators(profiles_index)
        if not running_emulators:
            # No running emulators found, return failure
            return False, None, avd_name

        # Try to find the user's AVD in running emulators
        if avd_name and avd_name in running_emulators:
            emulator_id = running_emulators[avd_name]
            logger.info(f"Found AVD {avd_name} running on {emulator_id} for email {email}")

            # Update VNC instance with this emulator ID for future reference
            try:
                from server.utils.vnc_instance_manager import VNCInstanceManager

                vnc_manager = VNCInstanceManager.get_instance()
                vnc_manager.set_emulator_id(email, emulator_id)
                logger.info(f"Updated VNC instance with emulator ID {emulator_id} for {email}")
            except Exception as e:
                logger.error(f"Error updating VNC instance with emulator ID: {e}")

            # No longer storing emulator_id in profiles - VNC instance manager is the source of truth

            return True, emulator_id, avd_name

        # Never use another user's AVD
        # If we have a specific AVD for this user and it's not running, we should fail
        if avd_name and avd_name not in running_emulators:
            # Return failure to find the user's specific AVD
            logger.info(f"User's AVD {avd_name} exists but is not running")
            return False, None, avd_name

        # No running emulator found for this email
        logger.info(f"No running emulator found for {email}")
        return False, None, avd_name

    def _query_emulator_avd_name(self, emulator_id: str) -> Optional[str]:
        """
        Query the emulator directly to get its AVD name.

        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')

        Returns:
            Optional[str]: The AVD name or None if not found
        """
        try:
            # Query the emulator's AVD name directly via adb
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "avd", "name"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )

            if result.returncode == 0 and result.stdout:
                avd_name = result.stdout.strip()
                if avd_name:
                    logger.info(f"Queried emulator {emulator_id} directly, running AVD: {avd_name}")
                    return avd_name

        except Exception as e:
            logger.warning(f"Error querying emulator {emulator_id} for AVD name: {e}")

        return None

    def _get_avd_name_for_emulator(self, emulator_id: str, profiles_index: Dict) -> Optional[str]:
        """
        Get the AVD name for a running emulator using AVD Profile Manager.

        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')

        Returns:
            Optional[str]: The AVD name or None if not found
        """
        try:
            # First, try to query the emulator directly - this is the most reliable method
            avd_name = self._query_emulator_avd_name(emulator_id)
            if avd_name:
                return avd_name

            # In simplified mode, we may not have AVD names in profiles
            if self.use_simplified_mode:
                # Don't assume any email, just return None
                return None

            # Next, check VNC instances for this emulator ID
            try:
                from server.utils.vnc_instance_manager import VNCInstanceManager

                vnc_manager = VNCInstanceManager.get_instance()

                # Find which email is using this emulator
                matched_email = None
                for instance in vnc_manager.instances:
                    if instance.get("emulator_id") == emulator_id and instance.get("assigned_profile"):
                        matched_email = instance.get("assigned_profile")
                        break

                # If found, look up the AVD name for this email
                if matched_email and matched_email in profiles_index:
                    profile = profiles_index[matched_email]
                    avd_name = profile.get("avd_name")
                    if avd_name:
                        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
                        if os.path.exists(avd_path):
                            return avd_name
            except Exception as e:
                logger.warning(f"Error checking VNC instances for emulator {emulator_id}: {e}")

            # If we got here, we can't reliably determine which AVD this emulator is running
            # Instead of guessing, return None
            return None

        except Exception as e:
            logger.error(f"Error getting AVD name for emulator {emulator_id}: {e}")

        return None

    def map_running_emulators(
        self, profiles_index: Dict, cached_info: Optional[Tuple[str, str]] = None
    ) -> Dict[str, str]:
        """
        Map running emulators to their device IDs.
        This method never kills or restarts the ADB server if it's already running properly.
        It only starts the server if the initial version check indicates issues.

        Args:
            cached_info: Optional tuple of (avd_name, emulator_id) to skip ADB query for this specific emulator

        Returns:
            Dict[str, str]: Mapping of emulator names to device IDs
        """
        running_emulators = {}

        # If we have cached info, add it to the result without ADB query
        if cached_info:
            avd_name, emulator_id = cached_info
            running_emulators[avd_name] = emulator_id
            # Still check ADB for other emulators that might be running

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
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

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

                        # Only proceed if the emulator device is actually available (not 'offline')
                        if device_state != "offline":
                            # Query AVD name using AVD Profile Manager
                            avd_name = self._get_avd_name_for_emulator(emulator_id, profiles_index)
                            if avd_name:
                                running_emulators[avd_name] = emulator_id
                        else:
                            logger.warning(f"Emulator {emulator_id} is in 'offline' state - skipping")

            return running_emulators
        except subprocess.TimeoutExpired:
            logger.warning("Timeout mapping running emulators")
            return running_emulators
        except Exception as e:
            logger.error(f"Error mapping running emulators: {e}")
            return running_emulators
