import json
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AVDProfileManager:
    """
    Manages Android Virtual Device (AVD) profiles for different Kindle user accounts.

    This class provides functionality to:
    1. Store and track multiple AVDs mapped to email addresses
    2. Switch between AVDs when a new authentication request comes in
    3. Create new AVD profiles when needed
    4. Track the currently active AVD/email
    """

    def __init__(self, base_dir: str = "/opt/android-sdk"):
        # Detect host architecture and operating system first
        self.host_arch = self._detect_host_architecture()
        self.is_macos = platform.system() == "Darwin"
        self.is_dev_mode = os.environ.get("FLASK_ENV") == "development"

        # Detect if we should use simplified mode (Mac dev environment)
        self.use_simplified_mode = self.is_macos and self.is_dev_mode

        # Get Android home from environment or fallback to default
        self.android_home = os.environ.get("ANDROID_HOME", base_dir)

        # Use a different base directory for Mac development environments
        if self.use_simplified_mode:
            # Use a directory under the user's home folder to avoid permission issues
            user_home = os.path.expanduser("~")
            base_dir = os.path.join(user_home, ".kindle-automator")
            logger.info("Mac development environment detected - using simplified emulator mode")
            logger.info(f"Using {base_dir} for profile storage instead of /opt/android-sdk")
            logger.info("Will use any available emulator instead of managing profiles")

            # In macOS, the AVD directory is typically in the .android folder
            # This ensures we're pointing to the right place for AVDs in Android Studio
            if self.android_home:
                logger.info(f"Using Android home from environment: {self.android_home}")
                self.avd_dir = os.path.join(user_home, ".android", "avd")
            else:
                # Fallback if ANDROID_HOME isn't set
                self.avd_dir = os.path.join(user_home, ".android", "avd")
                logger.info(f"ANDROID_HOME not set, using default AVD directory: {self.avd_dir}")
        else:
            logger.info(f"Using full profile management mode for {platform.system()} {self.host_arch}")
            # For non-Mac or non-dev environments, use standard directory structure
            self.avd_dir = os.path.join(base_dir, "avd")

        self.base_dir = base_dir
        self.profiles_dir = os.path.join(base_dir, "profiles")
        self.index_file = os.path.join(self.profiles_dir, "profiles_index.json")
        self.current_profile_file = os.path.join(self.profiles_dir, "current_profile.json")
        self.preferences_file = os.path.join(self.profiles_dir, "user_preferences.json")

        # Ensure directories exist
        try:
            os.makedirs(self.profiles_dir, exist_ok=True)
        except PermissionError:
            if not self.use_simplified_mode:
                # If not in simplified mode, re-raise the exception
                raise
            else:
                # This should rarely happen since we're already trying to use a home directory in simplified mode
                logger.warning(
                    f"Permission error creating {self.profiles_dir}, falling back to temporary directory"
                )
                import tempfile

                temp_dir = tempfile.gettempdir()
                self.base_dir = os.path.join(temp_dir, "kindle-automator")
                self.profiles_dir = os.path.join(self.base_dir, "profiles")
                self.index_file = os.path.join(self.profiles_dir, "profiles_index.json")
                self.current_profile_file = os.path.join(self.profiles_dir, "current_profile.json")
                self.preferences_file = os.path.join(self.profiles_dir, "user_preferences.json")
                os.makedirs(self.profiles_dir, exist_ok=True)
                logger.info(f"Successfully created fallback directory at {self.profiles_dir}")

        # Load profile index if it exists, otherwise create empty one
        self.profiles_index = self._load_profiles_index()
        self.current_profile = self._load_current_profile()
        self.user_preferences = self._load_user_preferences()

        # Scan for running emulators with email patterns on initialization
        try:
            self.scan_for_avds_with_emails()
        except Exception as e:
            logger.warning(f"Error scanning for AVDs with emails on init: {e}")

    def normalize_email_for_avd(self, email: str) -> str:
        """
        Normalize an email address to be used in an AVD name.

        Args:
            email: Email address to normalize

        Returns:
            str: Normalized email suitable for AVD name
        """
        return email.replace("@", "_").replace(".", "_")

    def get_avd_name_from_email(self, email: str) -> str:
        """
        Generate a standardized AVD name from an email address.

        Args:
            email: Email address

        Returns:
            str: Complete AVD name
        """
        email_formatted = self.normalize_email_for_avd(email)
        return f"KindleAVD_{email_formatted}"

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

    def _detect_host_architecture(self) -> str:
        """
        Detect the host machine's architecture.

        Returns:
            str: One of 'arm64', 'x86_64', or 'unknown'
        """
        machine = platform.machine().lower()

        if machine in ("arm64", "aarch64"):
            return "arm64"
        elif machine in ("x86_64", "amd64", "x64"):
            return "x86_64"
        else:
            # Log the actual architecture for debugging
            logger.warning(f"Unknown architecture: {machine}, defaulting to x86_64")
            return "unknown"

    def get_compatible_system_image(self, available_images: List[str]) -> Optional[str]:
        """
        Get the most compatible system image based on host architecture.

        Args:
            available_images: List of available system images

        Returns:
            Optional[str]: Most compatible system image or None if not found
        """
        # Important: Even on ARM Macs (M1/M2/M4), we need to use x86_64 images
        # because the ARM64 emulation in Android emulator is not fully supported yet.
        # The emulator will use Rosetta 2 to translate x86_64 to ARM.

        # First choice: Android 30 with Google Play Store (x86_64)
        for img in available_images:
            if "system-images;android-30;google_apis_playstore;x86_64" in img:
                return img

        # Second choice: Android 30 with Google APIs (x86_64)
        for img in available_images:
            if "system-images;android-30;google_apis;x86_64" in img:
                return img

        # Third choice: Any Android 30 x86_64 image
        for img in available_images:
            if "system-images;android-30;" in img and "x86_64" in img:
                return img

        # Fourth choice: Any modern Android x86_64 image
        for img in available_images:
            if "x86_64" in img:
                return img

        # Fallback to any image
        if available_images:
            return available_images[0]

        return None

    def _load_profiles_index(self) -> Dict[str, str]:
        """Load profiles index from JSON file or create if it doesn't exist."""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading profiles index: {e}")
                return {}
        else:
            return {}

    def _save_profiles_index(self) -> None:
        """Save profiles index to JSON file."""
        try:
            with open(self.index_file, "w") as f:
                json.dump(self.profiles_index, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving profiles index: {e}")

    def _load_current_profile(self) -> Optional[Dict]:
        """Load current profile from JSON file or return None if it doesn't exist."""
        if os.path.exists(self.current_profile_file):
            try:
                with open(self.current_profile_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading current profile: {e}")
                return None
        else:
            return None

    def find_running_emulator_for_email(self, email: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Find a running emulator that's associated with a specific email.

        Args:
            email: The email to find a running emulator for

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
            # Get the AVD name for this email even if not running
            avd_name = self.get_avd_for_email(email)
            return False, None, avd_name

        # First try the exact AVD name match based on email
        avd_name = self.get_avd_for_email(email)
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
                # If we found a match but it's different from our registered AVD, update the registration
                if avd_name != running_avd_name:
                    logger.info(f"Updating AVD mapping for email {email}: {avd_name} -> {running_avd_name}")
                    self.register_profile(email, running_avd_name)
                    avd_name = running_avd_name
                return True, emulator_id, running_avd_name

        # No running emulator found for this email
        logger.debug(f"No running emulator found matching email: {email}")
        return False, None, avd_name

    def _save_current_profile(self, email: str, avd_name: str, emulator_id: Optional[str] = None) -> None:
        """
        Save current profile to JSON file.

        Args:
            email: Email address of the profile
            avd_name: Name of the AVD
            emulator_id: Optional emulator device ID (e.g., 'emulator-5554')
        """
        # Prepare new profile data
        current = {"email": email, "avd_name": avd_name, "last_used": int(time.time())}

        # Add emulator ID if provided
        if emulator_id:
            current["emulator_id"] = emulator_id

        # Load any existing preferences for this email from user_preferences
        if email in self.user_preferences:
            # Copy styling preferences from user_preferences to current profile if they exist
            if "styles_updated" in self.user_preferences[email]:
                current["styles_updated"] = self.user_preferences[email]["styles_updated"]
        # Fallback to preserving existing preferences if they exist in the current profile
        elif self.current_profile and self.current_profile.get("email") == email:
            # Copy over any preferences that should be preserved
            if "styles_updated" in self.current_profile:
                current["styles_updated"] = self.current_profile["styles_updated"]
                # Also update user_preferences to ensure consistency
                if email not in self.user_preferences:
                    self.user_preferences[email] = {}
                self.user_preferences[email]["styles_updated"] = self.current_profile["styles_updated"]
                self._save_user_preferences()

        try:
            with open(self.current_profile_file, "w") as f:
                json.dump(current, f, indent=2)
            self.current_profile = current
        except Exception as e:
            logger.error(f"Error saving current profile: {e}")

    def get_avd_for_email(self, email: str) -> Optional[str]:
        """
        Get the AVD name for a given email address.

        Args:
            email: Email address to lookup

        Returns:
            Optional[str]: The associated AVD name or None if not found
        """
        # First check if we have a mapping in the profiles index
        if email in self.profiles_index:
            return self.profiles_index.get(email)

        # If not found, create a standardized AVD name
        return self.get_avd_name_from_email(email)

    def get_emulator_id_for_avd(self, avd_name: str) -> Optional[str]:
        """
        Get the emulator device ID for a given AVD name.

        Args:
            avd_name: Name of the AVD to find

        Returns:
            Optional[str]: The emulator ID if found, None otherwise
        """
        # Look for running emulators with this AVD name
        running_emulators = self.map_running_emulators()
        return running_emulators.get(avd_name)

    def get_emulator_id_for_email(self, email: str) -> Optional[str]:
        """
        Get the emulator device ID for a given email address.

        Args:
            email: Email address to find an emulator for

        Returns:
            Optional[str]: The emulator ID if found, None otherwise
        """
        # Use our dedicated method to find running emulator for email
        return self.find_running_emulator_for_email(email)

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
                error_msg = "Failed to get devices list after multiple attempts"
                logger.error(error_msg)
                # Raise exception instead of silently returning empty dict
                # This will allow the response_handler to catch and restart the emulator
                if not hasattr(locals(), "result"):
                    raise Exception(f"{error_msg}: No result after {max_retries} attempts")
                else:
                    raise Exception(f"{error_msg}: ADB returned error code {result.returncode}")
                # Return empty dict as fallback if the exception is caught higher up
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

                                    # If this email isn't already in our profiles_index, add it
                                    if extracted_email not in self.profiles_index:
                                        logger.info(
                                            f"Adding email {extracted_email} to profiles_index for AVD {avd_name}"
                                        )
                                        self.profiles_index[extracted_email] = avd_name
                                        self._save_profiles_index()
                            else:
                                # If we couldn't get the AVD name but we know an emulator is running,
                                # check if it matches our current profile
                                if self.current_profile and self.current_profile.get("avd_name"):
                                    current_avd = self.current_profile.get("avd_name")
                                    current_emu_id = self.current_profile.get("emulator_id")

                                    # If we have a matching emulator ID, use that mapping
                                    if current_emu_id == emulator_id:
                                        logger.info(
                                            f"Using known mapping for current profile: {current_avd} -> {emulator_id}"
                                        )
                                        running_emulators[current_avd] = emulator_id
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

    def _get_avd_name_for_emulator(self, emulator_id: str) -> Optional[str]:
        """
        Get the AVD name for a running emulator.

        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')

        Returns:
            Optional[str]: The AVD name or None if not found
        """
        try:
            # First check current profile if we have a matching emulator ID
            if self.current_profile and self.current_profile.get("emulator_id") == emulator_id:
                avd_name = self.current_profile.get("avd_name")
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

                # Look in our profiles index to find matches
                for email, avd_name in self.profiles_index.items():
                    if device_name.lower() in avd_name.lower():
                        logger.info(f"Matched AVD {avd_name} for device {device_name}")
                        return avd_name

                # No additional search needed - this code path is obsolete
                pass

                # If we still can't find it but there's only one profile, use that
                if len(self.profiles_index) == 1:
                    avd_name = next(iter(self.profiles_index.values()))
                    logger.info(f"Using only available AVD {avd_name} for emulator {emulator_id}")
                    return avd_name
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout getting AVD name for emulator {emulator_id}")
        except Exception as e:
            logger.error(f"Error getting AVD name for emulator {emulator_id}: {e}")

        return None

    def update_avd_name_for_email(self, email: str, avd_name: str) -> bool:
        """
        Update the AVD name associated with an email address.

        Args:
            email: The email address
            avd_name: The new AVD name to associate with this email

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Update the mapping in profiles_index
            self.profiles_index[email] = avd_name
            self._save_profiles_index()

            # Update current profile if this is the current email
            if self.current_profile and self.current_profile.get("email") == email:
                self.current_profile["avd_name"] = avd_name
                self._save_current_profile(email, avd_name, self.current_profile.get("emulator_id"))

            logger.info(f"Updated AVD name for {email} to {avd_name}")
            return True
        except Exception as e:
            logger.error(f"Error updating AVD name for {email}: {e}")
            return False

    def list_profiles(self) -> List[Dict]:
        """
        List all available profiles with their details.

        Returns:
            List[Dict]: List of profile information dictionaries
        """
        # First get running emulators
        running_emulators = self.map_running_emulators()

        result = []
        for email, avd_name in self.profiles_index.items():
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")

            # Get emulator ID if the AVD is running
            emulator_id = running_emulators.get(avd_name)

            # If we didn't find it, check if any running emulator has email in its name
            if not emulator_id:
                emulator_id = self.find_running_emulator_for_email(email)

            profile_info = {
                "email": email,
                "avd_name": avd_name,
                "exists": os.path.exists(avd_path),
                "current": self.current_profile and self.current_profile.get("email") == email,
                "emulator_id": emulator_id,
            }

            result.append(profile_info)
        return result

    def get_current_profile(self) -> Optional[Dict]:
        """
        Get information about the currently active profile.

        Returns:
            Optional[Dict]: Current profile information or None if no profile is active
        """
        if self.current_profile:
            # Get the current email and AVD name
            email = self.current_profile.get("email")
            avd_name = self.current_profile.get("avd_name")

            if email and avd_name:
                # Look for a running emulator for this email/AVD
                is_running, emulator_id, _ = self.find_running_emulator_for_email(email)

                # If we found one and it's different from what we have stored, update it
                if is_running and emulator_id and emulator_id != self.current_profile.get("emulator_id"):
                    logger.info(f"Updating emulator ID for current profile: {emulator_id}")
                    self.current_profile["emulator_id"] = emulator_id
                    self._save_current_profile(email, avd_name, emulator_id)

        return self.current_profile

    def scan_for_avds_with_emails(self) -> Dict[str, str]:
        """
        Scan all running AVDs to find ones with email patterns in their names.
        This helps to discover and register email-to-AVD mappings automatically.

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

                # Also update our profiles index if this mapping is new
                if email_part not in self.profiles_index:
                    logger.info(f"Adding new email-to-AVD mapping: {email_part} -> {avd_name}")
                    self.profiles_index[email_part] = avd_name
                    self._save_profiles_index()

        return discovered_mappings

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
            # Get list of running emulators
            running_emulators = self.map_running_emulators()
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

    def _stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID.

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
        try:
            # First do a quick check if emulator is actually running
            if not self.is_emulator_running():
                logger.info("No emulator running, nothing to stop")
                return True

            # First try graceful shutdown with shorter timeout
            logger.info("Attempting graceful emulator shutdown")
            subprocess.run([f"{self.android_home}/platform-tools/adb", "emu", "kill"], check=False, timeout=5)

            # Wait for emulator to shut down with shorter timeout
            deadline = time.time() + 10  # Reduced from 30 to 10 seconds
            start_time = time.time()
            while time.time() < deadline:
                # Check more frequently
                time.sleep(0.5)
                if not self.is_emulator_running():
                    elapsed = time.time() - start_time
                    logger.info(f"Emulator shut down gracefully in {elapsed:.2f} seconds")
                    return True

            # Try killing specific emulator processes rather than all emulator processes
            logger.info("Graceful shutdown timed out, trying forceful termination")
            try:
                # Get list of running emulators to kill specifically
                result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                # Parse out emulator IDs and kill them specifically
                lines = result.stdout.strip().split("\n")
                for line in lines[1:]:  # Skip header
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2 and "emulator" in parts[0]:
                        emulator_id = parts[0].strip()
                        logger.info(f"Killing specific emulator: {emulator_id}")
                        subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                            check=False,
                            timeout=3,
                        )
            except Exception as inner_e:
                logger.warning(f"Error during specific emulator kill: {inner_e}")

            # Force kill as last resort with pkill
            subprocess.run(["pkill", "-f", "emulator"], check=False, timeout=3)

            # Final check
            time.sleep(1)
            if not self.is_emulator_running():
                logger.info("Emulator forcibly terminated")
                return True
            else:
                logger.warning("Failed to completely terminate emulator processes")
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

            # First check if emulators are already running and log the status
            current_emulator_state = self._check_running_emulators(avd_name)

            # Check for matching running emulator
            if current_emulator_state["matching_emulator_id"]:
                logger.info(
                    f"Emulator for requested AVD {avd_name} is already running with ID: {current_emulator_state['matching_emulator_id']}"
                )

                # Double-check it's ready
                if self._is_specific_emulator_ready(current_emulator_state["matching_emulator_id"]):
                    logger.info(
                        f"Emulator {current_emulator_state['matching_emulator_id']} is ready, using existing instance"
                    )

                    # Update current profile with the emulator ID
                    if self.current_profile and self.current_profile.get("avd_name") == avd_name:
                        self.current_profile["emulator_id"] = current_emulator_state["matching_emulator_id"]

                    return True

                logger.info(
                    f"Emulator {current_emulator_state['matching_emulator_id']} is running but not ready, will restart it"
                )

            # If we have other emulators running, stop them before continuing
            if current_emulator_state["other_emulators"]:
                logger.warning(
                    f"Found {len(current_emulator_state['other_emulators'])} other emulator(s) running, stopping them first"
                )
                for emu_id in current_emulator_state["other_emulators"]:
                    logger.info(f"Stopping unrelated emulator: {emu_id}")
                    self._stop_specific_emulator(emu_id)

            # If any emulators are still running, do a full stop
            if self.is_emulator_running():
                logger.warning("Still have running emulators, performing full emulator stop")
                start_time = time.time()
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulators")
                    return False
                elapsed = time.time() - start_time
                logger.info(f"Emulator stop operation completed in {elapsed:.2f} seconds")

            # Always force x86_64 architecture for all hosts
            config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config_content = f.read()

                    # Force x86_64 for all hosts
                    if "arm64" in config_content:
                        logger.warning("Found arm64 architecture in AVD. Changing to x86_64...")
                        self._configure_avd(avd_name)  # Force reconfiguration to x86_64
                except Exception as e:
                    logger.error(f"Error checking AVD compatibility: {e}")

            # Set environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir
            env["ANDROID_HOME"] = self.android_home

            # Set DISPLAY for VNC if we're on Linux
            if platform.system() != "Darwin":
                env["DISPLAY"] = ":1"  # Use Xvfb display for VNC

            # Check if we're on a headless server with VNC
            vnc_launcher = "/usr/local/bin/vnc-emulator-launcher.sh"
            use_vnc = os.path.exists(vnc_launcher) and platform.system() != "Darwin"

            # Build emulator command with architecture-specific options
            if use_vnc:
                # Use the VNC launcher script for headless server
                logger.info(f"Using VNC-enabled emulator launcher for AVD {avd_name}")
                emulator_cmd = [
                    vnc_launcher,  # VNC launcher script
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-writable-system",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-port",
                    "5554",
                ]
            elif self.host_arch == "arm64":
                # For ARM Macs, try to use a different approach
                # Use arch command to force x86_64 mode via Rosetta 2
                emulator_cmd = [
                    "arch",
                    "-x86_64",
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-window",
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-feature",
                    "-HVF",  # Disable Hardware Virtualization
                    "-accel",
                    "off",
                ]

                logger.info("Using arch -x86_64 to run the emulator through Rosetta 2 on ARM Mac")
            else:
                # For x86_64 hosts (Linux servers), use standard command
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-window",
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-accel",
                    "on",  # Use hardware acceleration if available
                    "-feature",
                    "HVF",  # Hardware Virtualization Features
                    "-feature",
                    "KVM",  # Enable KVM (Linux)
                ]

            # Force a specific port to avoid conflicts with multiple emulators
            emulator_cmd.extend(["-port", "5554"])

            # Start emulator in background
            logger.info(f"Starting emulator with AVD {avd_name}")
            logger.info(f"Using command: {' '.join(emulator_cmd)}")

            process = subprocess.Popen(emulator_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Wait for emulator to boot with more frequent checks
            logger.info("Waiting for emulator to boot...")
            deadline = time.time() + 120  # 120 seconds total timeout
            last_progress_time = time.time()
            device_found = False
            expected_emulator_id = "emulator-5554"  # We specified port 5554 above
            boot_check_attempts = 0
            no_progress_timeout = 60  # 60 seconds with no progress triggers termination (increased from 30)
            check_interval = 1  # Check every 1 second (more frequent checks)

            while time.time() < deadline:
                boot_check_attempts += 1
                logger.info(
                    f"Emulator boot check attempt #{boot_check_attempts}, elapsed: {int(time.time() - last_progress_time)}s"
                )

                try:
                    # First check if the device is visible to adb
                    if not device_found:
                        devices_result = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "devices"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.info(f"ADB devices output: {devices_result.stdout.strip()}")

                        if expected_emulator_id in devices_result.stdout:
                            logger.info(
                                f"Emulator device {expected_emulator_id} detected by adb, waiting for boot to complete..."
                            )
                            device_found = True
                            last_progress_time = time.time()

                            # Store the emulator ID in current profile if matching
                            if self.current_profile and self.current_profile.get("avd_name") == avd_name:
                                self.current_profile["emulator_id"] = expected_emulator_id
                        elif "emulator" in devices_result.stdout:
                            logger.info(
                                f"Some emulator device detected, but not our expected {expected_emulator_id}"
                            )

                            # Parse the device list to get all emulator IDs
                            other_emulators = []
                            for line in devices_result.stdout.strip().split("\n"):
                                if "emulator-" in line and "device" in line:
                                    emulator_id = line.split("\t")[0].strip()
                                    other_emulators.append(emulator_id)

                            if other_emulators:
                                logger.warning(f"Found unexpected emulators: {other_emulators}")
                                device_found = True  # We'll try to use what we found
                                last_progress_time = time.time()
                                expected_emulator_id = other_emulators[0]  # Use the first one

                                # Update the mapping with what we found
                                logger.info(f"Will use existing emulator {expected_emulator_id}")
                                # No longer tracking emulator map

                    # Use the expected (or found) emulator ID for all further commands
                    if device_found:
                        # Check boot_completed with specific emulator ID
                        boot_completed = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "-s",
                                expected_emulator_id,
                                "shell",
                                "getprop",
                                "sys.boot_completed",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )

                        if boot_check_attempts % 10 == 0:
                            logger.info(
                                f"Boot progress for {expected_emulator_id} (sys.boot_completed): [{boot_completed.stdout.strip()}] [{boot_completed.stderr.strip()}]"
                            )

                        # If we get any response, even if not "1", update progress time
                        if boot_completed.stdout.strip():
                            last_progress_time = time.time()

                        # Check boot animation with specific emulator ID
                        boot_anim = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "-s",
                                expected_emulator_id,
                                "shell",
                                "getprop",
                                "init.svc.bootanim",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )

                        if boot_check_attempts % 10 == 0:
                            logger.info(
                                f"Boot animation for {expected_emulator_id}: [{boot_anim.stdout.strip()}] [{boot_anim.stderr.strip()}]"
                            )

                        if boot_anim.stdout.strip():
                            last_progress_time = time.time()

                            # 'stopped' means the boot animation has finished
                            if boot_anim.stdout.strip() == "stopped":
                                logger.info(
                                    f"Boot animation on {expected_emulator_id} has stopped, emulator is likely almost ready"
                                )

                        # Check if launcher is ready with specific emulator ID
                        try:
                            launcher_check = subprocess.run(
                                [
                                    f"{self.android_home}/platform-tools/adb",
                                    "-s",
                                    expected_emulator_id,
                                    "shell",
                                    "pidof",
                                    "com.android.launcher3",
                                ],
                                check=False,
                                capture_output=True,
                                text=True,
                                timeout=2,
                            )

                            if boot_check_attempts % 10 == 0:
                                logger.info(
                                    f"Launcher check for {expected_emulator_id}: [{launcher_check.stdout.strip()}] [{launcher_check.stderr.strip()}]"
                                )

                            if launcher_check.stdout.strip():
                                logger.info(f"Launcher is running on {expected_emulator_id}")
                                last_progress_time = time.time()
                        except Exception as launcher_e:
                            logger.warning(f"Launcher check failed: {launcher_e}")

                        # Only consider boot complete when we get "1" for sys.boot_completed
                        if boot_completed.stdout.strip() == "1":
                            logger.info(f"Emulator {expected_emulator_id} booted successfully")

                            # If we're using VNC, log the connection info
                            if use_vnc:
                                logger.info("VNC server is available for captcha solving")
                                logger.info(
                                    "Connect to the server's IP address on port 5900 using any VNC client"
                                )
                                logger.info("For web access: http://SERVER_IP:6080/vnc.html")
                                logger.info(
                                    "For mobile app integration: http://SERVER_IP:6080/kindle_captcha.html?password=PASSWORD&autoconnect=true"
                                )

                            # Additional verification - check for package manager
                            try:
                                pm_check = subprocess.run(
                                    [
                                        f"{self.android_home}/platform-tools/adb",
                                        "-s",
                                        expected_emulator_id,
                                        "shell",
                                        "pm",
                                        "list",
                                        "packages",
                                        "|",
                                        "grep",
                                        "amazon.kindle",
                                    ],
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                    timeout=3,
                                )

                                logger.info(
                                    f"Package check for {expected_emulator_id}: [{pm_check.stdout.strip()}] [{pm_check.stderr.strip()}]"
                                )

                                if "amazon.kindle" in pm_check.stdout:
                                    logger.info(
                                        f"Kindle package confirmed to be installed on {expected_emulator_id}"
                                    )
                                else:
                                    logger.warning(
                                        f"Emulator {expected_emulator_id} booted but Kindle package not found. Will proceed anyway."
                                    )
                            except Exception as e:
                                logger.warning(f"Error checking for Kindle package: {e}")

                            # Final success - store the mapping again to be sure
                            # No longer tracking emulator map

                            # Allow a bit more time for system services to stabilize
                            logger.info("Waiting 2 seconds for system services to stabilize...")
                            time.sleep(2)
                            return True
                    else:
                        logger.warning("Emulator not booted yet, continuing to wait...")
                        # Show what we have so far
                        logger.warning(f"Boot progress: {boot_completed.stdout.strip()}")
                        logger.warning(f"Boot animation: {boot_anim.stdout.strip()}")
                        logger.warning(f"Launcher: {launcher_check.stdout.strip()}")

                except Exception as e:
                    # Log but continue polling
                    logger.debug(f"Exception during boot check: {e}")

                # Check for no progress with the timeout
                elapsed_since_progress = time.time() - last_progress_time
                if elapsed_since_progress > no_progress_timeout:
                    logger.warning(
                        f"No progress detected for {elapsed_since_progress:.1f} seconds, collecting debug info before cleanup"
                    )

                    # Collect debug information before terminating
                    try:
                        # Check boot state again
                        boot_state = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "shell",
                                "getprop",
                                "sys.boot_completed",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.warning(f"Final boot_completed state: [{boot_state.stdout.strip()}]")

                        # Get list of running services
                        services = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "shell", "getprop | grep init.svc"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.warning(f"Running services: {services.stdout.strip()}")

                        # Check emulator process status
                        if process.poll() is not None:
                            logger.warning(
                                f"Emulator process already terminated with return code: {process.returncode}"
                            )
                            if process.stderr:
                                stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                                logger.warning(f"Emulator stderr: {stderr_output}")
                    except Exception as debug_e:
                        logger.warning(f"Error collecting debug info: {debug_e}")

                    logger.warning("Cleaning up emulator after no progress detected")

                    # Terminate the emulator process
                    try:
                        process.terminate()
                    except Exception as term_e:
                        logger.warning(f"Error terminating process: {term_e}")

                    # Force cleanup all emulators
                    self._force_cleanup_emulators()
                    return False

                # Sleep for a shorter time between checks
                time.sleep(check_interval)

            # If we get here, we timed out without booting successfully
            logger.error("Emulator boot timed out after 60 seconds")

            # Terminate the emulator process
            try:
                process.terminate()
            except:
                pass

            # Force cleanup all emulators
            self._force_cleanup_emulators()
            return False

        except Exception as e:
            logger.error(f"Error starting emulator: {e}")
            return False

    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """
        Create a new AVD for the given email.

        Returns:
            Tuple[bool, str]: (success, avd_name)
        """
        # Generate a unique AVD name based on the email using our utility method
        avd_name = self.get_avd_name_from_email(email)

        # Check if an AVD with this name already exists
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        if os.path.exists(avd_path):
            logger.info(f"AVD {avd_name} already exists, reusing it")
            return True, avd_name

        try:
            # Get list of available system images
            logger.info("Getting list of available system images")
            try:
                list_cmd = [f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager", "--list"]

                env = os.environ.copy()
                env["ANDROID_SDK_ROOT"] = self.android_home

                result = subprocess.run(
                    list_cmd, env=env, check=False, text=True, capture_output=True, timeout=30
                )

                # Parse available system images
                available_images = []
                output_lines = result.stdout.split("\n")
                for line in output_lines:
                    if "system-images;" in line:
                        # Extract the system image path
                        parts = line.strip().split("|")
                        if len(parts) > 0:
                            img_path = parts[0].strip()
                            available_images.append(img_path)

                # Get a compatible system image based on host architecture
                sys_img = self.get_compatible_system_image(available_images)

                if not sys_img:
                    # Always use x86_64 images for all platforms
                    sys_img = "system-images;android-30;google_apis_playstore;x86_64"
                    logger.info(f"No compatible system image found, will install {sys_img} for all hosts")

                # Try to install the system image if we have one selected
                if sys_img:
                    # Try to install the system image
                    logger.info(f"Installing system image: {sys_img}")
                    install_cmd = [
                        f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager",
                        "--install",
                        sys_img,
                    ]

                    install_result = subprocess.run(
                        install_cmd,
                        env=env,
                        check=False,
                        text=True,
                        input="y\n",  # Auto-accept license
                        capture_output=True,
                        timeout=300,  # 5 minutes timeout for installation
                    )

                    if install_result.returncode != 0:
                        logger.error(f"Failed to install system image: {install_result.stderr}")
                        return False, f"Failed to install system image: {install_result.stderr}"
                else:
                    logger.error("No compatible system image found and failed to select a fallback")
                    return False, "No compatible system image found for your architecture"

            except Exception as e:
                logger.error(f"Error getting available system images: {e}")
                # Fallback to x86_64 for all platforms
                sys_img = "system-images;android-30;google_apis;x86_64"
                logger.info("Using fallback x86_64 system image")

            logger.info(f"Using system image: {sys_img}")

            # Create new AVD
            logger.info(f"Creating new AVD named {avd_name} for email {email}")

            # Set environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir

            # Build AVD creation command
            create_cmd = [
                f"{self.android_home}/cmdline-tools/latest/bin/avdmanager",
                "create",
                "avd",
                "-n",
                avd_name,
                "-k",
                sys_img,
                "--device",
                "pixel_5",
                "--force",
            ]

            logger.info(f"Creating AVD with command: {' '.join(create_cmd)}")

            # Execute AVD creation command
            process = subprocess.run(create_cmd, env=env, check=False, text=True, capture_output=True)

            if process.returncode != 0:
                logger.error(f"Failed to create AVD: {process.stderr}")
                return False, f"Failed to create AVD: {process.stderr}"

            # Configure AVD settings for better performance
            self._configure_avd(avd_name)

            return True, avd_name

        except Exception as e:
            logger.error(f"Error creating new AVD: {e}")
            return False, str(e)

    def _configure_avd(self, avd_name: str) -> None:
        """Configure AVD settings for better performance."""
        config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
        if not os.path.exists(config_path):
            logger.error(f"AVD config file not found at {config_path}")
            return

        try:
            # Read existing config
            with open(config_path, "r") as f:
                config_lines = f.readlines()

            # Always use x86_64 for all host types
            # Even on ARM Macs, we need to use x86_64 images with Rosetta 2 translation
            # as the Android emulator doesn't properly support ARM64 emulation yet
            cpu_arch = "x86_64"
            sysdir = "system-images/android-30/google_apis_playstore/x86_64/"

            logger.info(f"Using x86_64 architecture for all host types (even on ARM Macs)")

            # Special handling for cloud linux servers
            if self.host_arch == "x86_64" and os.path.exists("/etc/os-release"):
                # This is likely a Linux server
                logger.info("Detected Linux x86_64 host - using standard x86_64 configuration")

            logger.info(
                f"Configuring AVD {avd_name} for {self.host_arch} host with {cpu_arch} CPU architecture"
            )

            # Define settings to update
            settings = {
                "hw.ramSize": "4096",
                "hw.cpu.ncore": "4",
                "hw.gpu.enabled": "yes",
                "hw.gpu.mode": "swiftshader",
                "hw.audioInput": "no",
                "hw.audioOutput": "no",
                "hw.gps": "no",
                "hw.camera.back": "none",
                "hw.keyboard": "yes",
                "hw.fastboot": "no",
                "hw.arc": "false",
                "hw.useext4": "yes",
                "kvm.enabled": "no",
                "showWindow": "no",
                "hw.arc.autologin": "no",
                "snapshot.present": "no",
                "disk.dataPartition.size": "6G",
                "PlayStore.enabled": "true",
                "image.sysdir.1": sysdir,
                "tag.id": "google_apis_playstore" if "playstore" in sysdir else "google_apis",
                "tag.display": "Google Play" if "playstore" in sysdir else "Google APIs",
                "hw.cpu.arch": cpu_arch,
                "ro.kernel.qemu.gles": "1",
                "skin.dynamic": "yes",
                "skin.name": "1080x1920",
                "skin.path": "_no_skin",
                "skin.path.backup": "_no_skin",
            }

            # For arm64 hosts, make sure we're not trying to use x86_64
            if self.host_arch == "arm64":
                # Remove any x86 settings
                keys_to_remove = []
                for line in config_lines:
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if "x86" in value and key not in keys_to_remove:
                            keys_to_remove.append(key)

                # Log what we're removing
                if keys_to_remove:
                    logger.info(f"Removing incompatible x86 settings: {', '.join(keys_to_remove)}")

            # Update config file
            new_config_lines = []
            for line in config_lines:
                if "=" in line:
                    key = line.split("=")[0]
                    if key in settings:
                        new_config_lines.append(f"{key}={settings[key]}\n")
                        del settings[key]
                    else:
                        # Skip lines with x86 values on arm64 hosts
                        if self.host_arch == "arm64" and "x86" in line:
                            continue
                        new_config_lines.append(line)
                else:
                    new_config_lines.append(line)

            # Add any remaining settings
            for key, value in settings.items():
                new_config_lines.append(f"{key}={value}\n")

            # Write back to file
            with open(config_path, "w") as f:
                f.writelines(new_config_lines)

            logger.info(f"Updated AVD configuration for {avd_name}")

        except Exception as e:
            logger.error(f"Error configuring AVD: {e}")

    def register_profile(self, email: str, avd_name: str) -> None:
        """Register a profile by associating an email with an AVD name."""
        self.profiles_index[email] = avd_name
        self._save_profiles_index()
        logger.info(f"Registered profile for {email} with AVD {avd_name}")

    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """
        Switch to the profile for the given email.
        If the profile doesn't exist, create a new one.

        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any running emulator and start a new one
                               (used with recreate=1 flag)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info(f"Switching to profile for email: {email} (force_new_emulator={force_new_emulator})")

        # Special case: Simplified mode for Mac development environment
        if self.use_simplified_mode:
            logger.info("Using simplified mode for Mac development environment")

            # In simplified mode, we don't manage profiles on Mac dev machines
            # Just use whatever emulator is running and associate it with this email

            # Check if any emulator is running
            if self.is_emulator_running():
                # If we have a running emulator, just use it
                running_emulators = self.map_running_emulators()

                if running_emulators:
                    # First check if there's an emulator with this email in the AVD name
                    emulator_id = self.find_running_emulator_for_email(email)
                    if emulator_id:
                        # Find the AVD name for this emulator
                        for avd, emu_id in running_emulators.items():
                            if emu_id == emulator_id:
                                avd_name = avd
                                break
                        else:
                            # Use first available if we couldn't find the matching AVD
                            avd_name, emulator_id = next(iter(running_emulators.items()))
                    else:
                        # Use first available emulator
                        avd_name, emulator_id = next(iter(running_emulators.items()))

                    logger.info(
                        f"Using existing running emulator: {emulator_id} (AVD: {avd_name}) for {email}"
                    )

                    # Associate this emulator with the profile
                    if email not in self.profiles_index or self.profiles_index[email] != avd_name:
                        self.profiles_index[email] = avd_name
                        self._save_profiles_index()

                    # Update current profile
                    self._save_current_profile(email, avd_name, emulator_id)

                    return True, f"Using existing emulator {emulator_id} for {email}"
                else:
                    logger.warning("Emulator appears to be running but couldn't identify it")

            # If no emulator is running or we couldn't identify it, try to find AVD
            avd_name = self.get_avd_for_email(email)

            if not avd_name:
                # Look for any available AVD
                try:
                    # List available AVDs
                    avd_list_cmd = [f"{self.android_home}/emulator/emulator", "-list-avds"]
                    result = subprocess.run(
                        avd_list_cmd, check=False, capture_output=True, text=True, timeout=5
                    )
                    available_avds = result.stdout.strip().split("\n")
                    available_avds = [avd for avd in available_avds if avd.strip()]

                    if available_avds:
                        # Use the first available AVD
                        avd_name = available_avds[0]
                        logger.info(f"Using first available AVD: {avd_name} for {email}")

                        # Register this AVD with the profile
                        self.register_profile(email, avd_name)
                    else:
                        logger.warning(f"No AVDs found. Please create an AVD in Android Studio")
                        # Create a placeholder name that will be updated later
                        avd_name = f"AndroidStudioAVD_{email.split('@')[0]}"
                        self.register_profile(email, avd_name)
                except Exception as e:
                    logger.warning(f"Error listing available AVDs: {e}")
                    # Create a placeholder AVD name
                    avd_name = f"AndroidStudioAVD_{email.split('@')[0]}"
                    self.register_profile(email, avd_name)

            # Update current profile without trying to start emulator
            self._save_current_profile(email, avd_name)

            logger.info(f"In simplified mode, tracking profile for {email} without managing emulator")
            return True, f"Tracking profile for {email} in simplified mode"

        #
        # Normal profile management mode below (for non-Mac or non-dev environments)
        #

        # If force_new_emulator is True, stop any running emulator first
        if force_new_emulator:
            logger.info("Force new emulator requested, stopping any running emulator")
            if self.is_emulator_running():
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulator")
                    # We'll try to continue anyway

        # Check if this is already the current profile
        if self.current_profile and self.current_profile.get("email") == email and not force_new_emulator:
            logger.info(f"Already using profile for {email}")

            # If an emulator is already running and ready, just use it
            if self.is_emulator_ready():
                logger.info(f"Emulator already running and ready for profile {email}")
                return True, f"Already using profile for {email} with running emulator"
            else:
                # Attempt to start the emulator for this profile
                avd_name = self.current_profile.get("avd_name")
                if avd_name:
                    # Check if AVD exists before trying to start it
                    avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
                    if not os.path.exists(avd_path):
                        logger.error(f"AVD {avd_name} does not exist at {avd_path}. Need to create it first.")
                        # Try to create the AVD
                        logger.info(f"Attempting to create AVD for {email}")
                        success, result = self.create_new_avd(email)
                        if not success:
                            logger.error(f"Failed to create AVD: {result}")
                            return False, f"Failed to create AVD for {email}: {result}"
                        # Update avd_name with newly created AVD
                        avd_name = result
                        self.register_profile(email, avd_name)
                        logger.info(f"Created new AVD {avd_name} for {email}")

                    logger.info(f"Emulator not ready for profile {email}, attempting to start it")
                    if self.start_emulator(avd_name):
                        logger.info(f"Successfully started emulator for profile {email}")
                        return True, f"Started emulator for profile {email}"

            # Otherwise continue with normal profile switch
            logger.info(f"Emulator not ready for profile {email}, proceeding with normal switch")

        # Get AVD name for this email
        avd_name = self.get_avd_for_email(email)

        # If no AVD exists for this email, create one
        if not avd_name:
            logger.info(f"No AVD found for {email}, creating new one")
            success, result = self.create_new_avd(email)
            if not success:
                return False, f"Failed to create AVD: {result}"
            avd_name = result
            self.register_profile(email, avd_name)

        # Check if this AVD actually exists - it might not if we're using
        # manually registered AVDs but the Android Studio AVD was renamed or deleted
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)

        # First check if there's already a running emulator for this email
        is_running, emulator_id, found_avd_name = self.find_running_emulator_for_email(email)

        # If we found a running emulator for this email and we're not forcing a new one
        if is_running and not force_new_emulator:
            logger.info(f"Found running emulator {emulator_id} for profile {email} (AVD: {found_avd_name})")
            # Update the AVD name if it's different from what we expected
            if found_avd_name != avd_name and found_avd_name is not None:
                logger.info(f"Updating AVD name for profile {email}: {avd_name} -> {found_avd_name}")
                avd_name = found_avd_name
                self.register_profile(email, avd_name)

            # Save the current profile with the found emulator
            self._save_current_profile(email, avd_name, emulator_id)
            logger.info(f"Using existing running emulator for profile {email}")
            return True, f"Switched to profile {email} with existing running emulator"

        # Check if emulator is already running and ready
        emulator_ready = self.is_emulator_ready()

        # For Mac M1/M2/M4 users where direct emulator launch might fail,
        # we'll just track the profile without trying to start the emulator
        if self.host_arch == "arm64" and platform.system() == "Darwin":
            logger.info(f"Running on ARM Mac - skipping emulator start, just tracking profile change")
            # Update current profile
            self._save_current_profile(email, avd_name)

            if emulator_ready:
                logger.info(f"Found running emulator that appears ready, will use it for profile {email}")
                return True, f"Switched to profile {email} with existing running emulator"

            if not avd_exists:
                logger.warning(
                    f"AVD {avd_name} doesn't exist at {avd_path}. If using Android Studio AVDs, "
                    f"please run 'make register-avd' to update the AVD name for this profile."
                )
            return True, f"Switched profile tracking to {email} (AVD: {avd_name})"

        # For other platforms, try normal start procedure
        # Check running emulators more carefully - don't stop emulators unnecessarily
        running_avds = self.map_running_emulators()

        # Only restart emulators in specific cases
        if force_new_emulator and self.is_emulator_running():
            # Force new emulator was explicitly requested
            logger.info("Force new emulator explicitly requested, stopping current emulator")
            if not self.stop_emulator():
                return False, "Failed to stop current emulator"
        # Only if emulator is running but not ready, and it doesn't match our AVD, stop it
        elif not emulator_ready and self.is_emulator_running():
            # Check if the running emulator is related to our AVD or email
            if avd_name in running_avds:
                logger.info(
                    f"Found running emulator for AVD {avd_name} but it's not ready yet, waiting for it"
                )
                # Don't stop it, just wait
            else:
                # Check if any running emulator has the email in its name
                email_match_found = False
                for running_avd in running_avds.keys():
                    if self.normalize_email_for_avd(email) in running_avd:
                        logger.info(
                            f"Found emulator with matching email pattern: {running_avd}, waiting for it"
                        )
                        email_match_found = True
                        break

                if not email_match_found:
                    # No match found, so stop the unrelated emulator
                    logger.info(
                        "Emulator running but not related to this profile, stopping to restart the correct one"
                    )
                    if not self.stop_emulator():
                        return False, "Failed to stop unrelated emulator"

        # If emulator is already running and ready, check if we should use it
        if emulator_ready and not force_new_emulator:
            # We need to verify this emulator belongs to the correct AVD or has the email in its name
            running_avds = self.map_running_emulators()
            if avd_name in running_avds:
                logger.info(
                    f"Using already running emulator for profile {email} - confirmed to be correct AVD"
                )
                self._save_current_profile(email, avd_name, running_avds[avd_name])
                return True, f"Switched to profile {email} with existing running emulator (verified)"
            else:
                logger.warning(f"Found running emulator but it doesn't match the expected AVD {avd_name}")
                # If we're not forcing a new emulator, check if we can use this one
                if not force_new_emulator:
                    # Check if any running emulator has the email in its name
                    for running_avd, running_emu_id in running_avds.items():
                        if self.normalize_email_for_avd(email) in running_avd:
                            logger.info(f"Found emulator with matching email pattern: {running_avd}")
                            # Update our registration to match the running AVD
                            self.register_profile(email, running_avd)
                            self._save_current_profile(email, running_avd, running_emu_id)
                            return (
                                True,
                                f"Switched to profile {email} with existing running emulator (name match)",
                            )

                # If we didn't find a matching emulator or we're forcing a new one, stop the current emulator
                logger.info(f"Stopping unrelated emulator to start the correct one")
                if not self.stop_emulator():
                    logger.error("Failed to stop unrelated emulator")
                    # We'll try to continue anyway

        # Check if AVD exists before trying to start it
        if not avd_exists:
            logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. Attempting to create it.")
            # Try to create the AVD
            success, result = self.create_new_avd(email)
            if not success:
                logger.error(f"Failed to create AVD: {result}")
                # Still update the current profile for tracking
                self._save_current_profile(email, avd_name)
                return (
                    False,
                    f"Failed to create AVD for {email}: {result}",
                )

            # Update avd_name with newly created AVD
            avd_name = result
            self.register_profile(email, avd_name)
            logger.info(f"Created new AVD {avd_name} for {email}")

            # Update current profile with new AVD
            self._save_current_profile(email, avd_name)

            # Set avd_exists to True since we just created it
            avd_exists = True

        # Double-check that AVD actually exists before trying to start it
        # This shouldn't be necessary since we already handled AVD creation above,
        # but it's here as a safety check
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        if not os.path.exists(avd_path):
            logger.error(
                f"AVD {avd_name} still does not exist even after creation attempt. This is unexpected."
            )
            return False, f"Failed to create AVD for {email}: AVD still doesn't exist after creation attempt"

        # Start the new emulator
        logger.info(f"Starting emulator with AVD {avd_name}")
        if not self.start_emulator(avd_name):
            # If we can't start the emulator, we should check if any are running and handle appropriately
            if self.is_emulator_running():
                if force_new_emulator:
                    # If we need a fresh emulator, forcibly kill any running ones
                    logger.warning(f"Failed to start new emulator for {avd_name} and force_new_emulator=True")
                    logger.warning("Forcibly terminating any running emulators")

                    # Force kill all emulator processes
                    self._force_cleanup_emulators()

                    # Cannot continue with force_new_emulator if we can't clean everything up
                    logger.warning(
                        f"Emulator start failed, tracking profile {email} but fresh emulator required - manual intervention needed"
                    )

                elif not force_new_emulator:
                    # Only in non-force mode, we might consider using an existing emulator
                    # Check if it's the correct AVD for this email
                    running_avds = self.map_running_emulators()
                    if avd_name in running_avds:
                        logger.warning(
                            f"Failed to start new emulator but found correct running AVD {avd_name}. Will use it for {email}"
                        )
                        self._save_current_profile(email, avd_name)
                        # Try to verify the emulator is actually ready
                        if self.is_emulator_ready():
                            logger.info(f"Existing emulator is ready, using it for profile {email}")
                            return (
                                True,
                                f"Switched to profile {email} with existing running emulator (verified)",
                            )
                    else:
                        logger.warning(
                            f"Failed to start emulator for {avd_name} and found unrelated running emulator"
                        )
                        # For safety, we should not use an unrelated emulator's data
                        logger.info(f"Forcing emulator shutdown to prevent data mixing")
                        self.stop_emulator()
                        logger.warning(
                            f"Emulator start failed, but still tracking profile {email} - manual intervention needed"
                        )

            # Update current profile even if emulator couldn't start
            self._save_current_profile(email, avd_name)
            return (
                True,
                f"Tracked profile for {email} but emulator failed to start. Try running manually with 'make run-emulator'",
            )

        # Update current profile
        self._save_current_profile(email, avd_name)

        return True, f"Successfully switched to profile for {email}"

    def create_profile(self, email: str) -> Tuple[bool, str]:
        """
        Create a new profile for the given email without switching to it.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Check if profile already exists
        if email in self.profiles_index:
            # If the profile exists but doesn't follow our naming convention,
            # let's generate the standard name and update it
            current_avd = self.profiles_index[email]
            standard_avd = self.get_avd_name_from_email(email)

            if current_avd != standard_avd:
                logger.info(
                    f"Profile for {email} exists but with non-standard AVD name. Updating to {standard_avd}"
                )

                # Check if the existing AVD actually exists
                existing_path = os.path.join(self.avd_dir, f"{current_avd}.avd")
                standard_path = os.path.join(self.avd_dir, f"{standard_avd}.avd")

                if os.path.exists(existing_path) and not os.path.exists(standard_path):
                    # Rename the existing AVD to follow our convention
                    try:
                        # Rename the AVD directory
                        shutil.move(existing_path, standard_path)

                        # Rename the .ini file if it exists
                        existing_ini = os.path.join(self.avd_dir, f"{current_avd}.ini")
                        standard_ini = os.path.join(self.avd_dir, f"{standard_avd}.ini")
                        if os.path.exists(existing_ini):
                            shutil.move(existing_ini, standard_ini)

                        # Update our profiles_index
                        self.profiles_index[email] = standard_avd
                        self._save_profiles_index()

                        logger.info(f"Successfully renamed AVD from {current_avd} to {standard_avd}")
                        return (
                            True,
                            f"Profile for {email} exists, renamed AVD to standard format: {standard_avd}",
                        )
                    except Exception as e:
                        logger.error(f"Error renaming AVD: {e}")

            return True, f"Profile for {email} already exists with AVD: {current_avd}"

        # Create new AVD using our standardized naming
        success, result = self.create_new_avd(email)
        if not success:
            return False, f"Failed to create AVD: {result}"

        # Register profile
        self.register_profile(email, result)

        return True, f"Successfully created profile for {email}"

    def _load_user_preferences(self) -> Dict:
        """
        Load user preferences from JSON file or create if it doesn't exist.

        Returns:
            Dict: User preferences dictionary mapping email to preferences
        """
        if os.path.exists(self.preferences_file):
            try:
                with open(self.preferences_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading user preferences: {e}")
                return {}
        else:
            # Create an empty preferences file
            try:
                with open(self.preferences_file, "w") as f:
                    json.dump({}, f, indent=2)
                return {}
            except Exception as e:
                logger.error(f"Error creating user preferences file: {e}")
                return {}

    def _save_user_preferences(self) -> bool:
        """
        Save user preferences to JSON file.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(self.preferences_file, "w") as f:
                json.dump(self.user_preferences, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving user preferences: {e}")
            return False

    def update_style_preference(self, styles_updated: bool = True) -> bool:
        """
        Update the style preference for the current profile.

        Args:
            styles_updated: Whether styles have been updated for this profile

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.current_profile:
            logger.error("Cannot update style preference: no current profile")
            return False

        try:
            # Get the email for the current profile
            email = self.current_profile.get("email")
            if not email:
                logger.error("Cannot update style preference: current profile has no email")
                return False

            # Create or update preferences for this email
            if email not in self.user_preferences:
                self.user_preferences[email] = {}

            # Set the styles_updated preference
            self.user_preferences[email]["styles_updated"] = styles_updated

            # Save preferences to file
            self._save_user_preferences()

            # Also update the current profile for backward compatibility
            self.current_profile["styles_updated"] = styles_updated
            with open(self.current_profile_file, "w") as f:
                json.dump(self.current_profile, f, indent=2)

            logger.info(f"Updated style preference for {email} to {styles_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating style preference: {e}")
            return False

    def is_styles_updated(self) -> bool:
        """
        Check if styles have been updated for the current profile.

        Returns:
            bool: True if styles have been updated, False otherwise
        """
        if not self.current_profile:
            logger.debug("No current profile, styles not updated")
            return False

        # Get the email for the current profile
        email = self.current_profile.get("email")
        if not email:
            logger.debug("Current profile has no email, styles not updated")
            return False

        # Check for the preference in user_preferences first
        if email in self.user_preferences and "styles_updated" in self.user_preferences[email]:
            return self.user_preferences[email]["styles_updated"]

        # Fall back to current profile for backward compatibility
        return self.current_profile.get("styles_updated", False)

    def delete_profile(self, email: str) -> Tuple[bool, str]:
        """
        Delete the profile for the given email.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Check if profile exists
        if email not in self.profiles_index:
            return False, f"No profile found for {email}"

        # Get AVD name
        avd_name = self.profiles_index[email]

        # Special case for Mac development environment
        if self.use_simplified_mode:
            logger.info(f"In simplified mode (Mac dev), just removing profile tracking for {email}")

            # Remove from profiles index
            del self.profiles_index[email]
            self._save_profiles_index()

            # If this is the current profile, clear it
            if self.current_profile and self.current_profile.get("email") == email:
                self.current_profile = None
                if os.path.exists(self.current_profile_file):
                    os.remove(self.current_profile_file)

            # Clean up emulator mapping
            # No longer using emulator_map

            # Remove from user preferences
            if email in self.user_preferences:
                del self.user_preferences[email]
                self._save_user_preferences()
                logger.info(f"Removed preferences for {email}")

            logger.info(f"Profile tracking removed for {email} in simplified mode")
            return True, f"Profile tracking removed for {email}"

        # Normal profile deletion for server environments

        # Always ensure any emulators are stopped before deleting the profile
        # This is important even if it's not the current profile, as the emulator
        # might still be running from a previous session
        logger.info(f"Ensuring no emulators are running before deleting profile for {email}")
        emulator_id = self.get_emulator_id_for_avd(avd_name)
        if emulator_id:
            logger.info(f"Found emulator {emulator_id} for AVD {avd_name}, stopping it")

            # Try specific emulator stop first
            try:
                subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                    check=False,
                    timeout=5,
                )
                # Wait briefly for emulator to stop
                time.sleep(2)
            except Exception as e:
                logger.warning(f"Error stopping specific emulator: {e}")

        # Force cleanup to make sure all emulators are stopped
        self._force_cleanup_emulators()

        # Check if this is the current profile
        if self.current_profile and self.current_profile.get("email") == email:
            # Clear current profile
            self.current_profile = None
            if os.path.exists(self.current_profile_file):
                os.remove(self.current_profile_file)

        # Delete AVD files
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_ini = os.path.join(self.avd_dir, f"{avd_name}.ini")

        if os.path.exists(avd_path):
            try:
                # Make several attempts to delete the directory,
                # as it might be temporarily locked by an emulator process
                for attempt in range(3):
                    try:
                        logger.info(f"Attempting to delete AVD directory: {avd_path} (attempt {attempt+1}/3)")
                        shutil.rmtree(avd_path)
                        logger.info(f"Successfully deleted AVD directory: {avd_path}")
                        break
                    except Exception as e:
                        logger.warning(f"Error deleting AVD directory (attempt {attempt+1}/3): {e}")
                        # If this isn't the last attempt, wait briefly and retry
                        if attempt < 2:
                            time.sleep(1)
                            # Force cleanup again to ensure no processes are holding locks
                            self._force_cleanup_emulators()
                        else:
                            logger.error(f"Error deleting AVD directory after 3 attempts: {e}")
                            return False, f"Failed to delete AVD directory: {str(e)}"
            except Exception as e:
                logger.error(f"Error deleting AVD directory: {e}")
                return False, f"Failed to delete AVD directory: {str(e)}"

        if os.path.exists(avd_ini):
            try:
                os.remove(avd_ini)
                logger.info(f"Deleted AVD ini file: {avd_ini}")
            except Exception as e:
                logger.error(f"Error deleting AVD ini file: {e}")

            # Clean up emulator mapping
            # No longer using emulator_map
            logger.info(f"Removed {avd_name} from emulator map")

        # Remove from profiles index
        del self.profiles_index[email]
        self._save_profiles_index()

        # Remove from user preferences
        if email in self.user_preferences:
            del self.user_preferences[email]
            self._save_user_preferences()
            logger.info(f"Removed preferences for {email}")

        return True, f"Successfully deleted profile for {email}"
