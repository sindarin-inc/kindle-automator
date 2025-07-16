import json
import logging
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from server.utils.request_utils import get_sindarin_email
from views.core.avd_creator import AVDCreator
from views.core.device_discovery import DeviceDiscovery
from views.core.emulator_manager import EmulatorManager

logger = logging.getLogger(__name__)

# Singleton instance
_instance = None


class AVDProfileManager:
    """
    Manages Android Virtual Device (AVD) profiles for different Kindle user accounts.

    Note that this model is shared between all users, so don't set any user-specific preferences here.

    This class provides functionality to:
    1. Store and track multiple AVDs mapped to email addresses
    2. Switch between AVDs when a new authentication request comes in
    3. Create new AVD profiles when needed
    4. Track the currently active AVD/email
    """

    @classmethod
    def get_instance(cls, base_dir: str = "/opt/android-sdk") -> "AVDProfileManager":
        """
        Get the singleton instance of AVDProfileManager.

        Args:
            base_dir: Base directory for Android SDK (default: "/opt/android-sdk")

        Returns:
            AVDProfileManager: The singleton instance
        """
        global _instance
        if _instance is None:
            _instance = cls(base_dir)
        return _instance

    def __init__(self, base_dir: str = "/opt/android-sdk"):
        # Check if this is being called directly or through get_instance()
        global _instance
        if _instance is not None and _instance is not self:
            logger.warning("AVDProfileManager initialized directly. Use get_instance() instead.")

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
            # Use project's user_data directory instead of home folder
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            base_dir = os.path.join(project_root, "user_data")
            logger.info("Mac development environment detected - using simplified emulator mode")
            logger.info(f"Using {base_dir} for profile storage instead of /opt/android-sdk")
            logger.info("Will use any available emulator instead of managing profiles")

            # Profiles now stored in project's user_data directory

            # In macOS, the AVD directory is typically in the .android folder
            # This ensures we're pointing to the right place for AVDs in Android Studio
            user_home = os.path.expanduser("~")
            if self.android_home:
                logger.info(f"Using Android home from environment: {self.android_home}")
                self.avd_dir = os.path.join(user_home, ".android", "avd")
            else:
                # Fallback if ANDROID_HOME isn't set
                self.avd_dir = os.path.join(user_home, ".android", "avd")
                logger.info(f"ANDROID_HOME not set, using default AVD directory: {self.avd_dir}")
        else:
            # For non-Mac or non-dev environments, use standard directory structure
            self.avd_dir = os.path.join(base_dir, "avd")

        self.base_dir = base_dir

        # In the new structure, we store everything directly in user_data/
        if self.use_simplified_mode:
            self.profiles_dir = base_dir
            self.users_file = os.path.join(self.profiles_dir, "users.json")
        else:
            # For non-Mac or non-dev environments, keep the old directory structure
            self.profiles_dir = os.path.join(base_dir, "profiles")
            self.users_file = os.path.join(self.profiles_dir, "users.json")

        # Ensure directories exist
        os.makedirs(self.profiles_dir, exist_ok=True)
        # Initialize component managers
        self.device_discovery = DeviceDiscovery(self.android_home, self.avd_dir, self.use_simplified_mode)
        self.emulator_manager = EmulatorManager(
            self.android_home, self.avd_dir, self.host_arch, self.use_simplified_mode
        )
        self.avd_creator = AVDCreator(self.android_home, self.avd_dir, self.host_arch)

        # Load profile index if it exists, otherwise create empty one
        self._load_profiles_index()

        # Load user preferences from the profiles_index
        self.user_preferences = self._load_user_preferences()

    def get_avd_name_from_email(self, email: str) -> str:
        """
        Generate a standardized AVD name from an email address.

        Args:
            email: Email address

        Returns:
            str: Complete AVD name
        """
        return self.avd_creator.get_avd_name_from_email(email)

    def _start_emulator_and_create_snapshot(
        self, email: str, prepare_kindle: bool = False
    ) -> Tuple[bool, str]:
        """
        Helper method to start an emulator, wait for it to be ready, create a snapshot, and stop it.

        Args:
            email: Email of the emulator to start
            prepare_kindle: If True, install Kindle APK and navigate to Library before snapshot

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Start the emulator
        logger.info(f"Starting emulator for {email}")
        if not self.emulator_manager.start_emulator_with_retries(email):
            return False, "Failed to start emulator"

        # Wait for emulator to be ready
        logger.info("Waiting for emulator to be ready...")

        # Use the existing launcher from emulator_manager to maintain cache consistency
        launcher = self.emulator_manager.emulator_launcher

        # Wait up to 2 minutes for emulator to be ready
        for i in range(24):  # 24 * 5 seconds = 2 minutes
            if launcher.is_emulator_ready(email):
                logger.info("Emulator is ready")
                break
            time.sleep(5)
        else:
            return False, "Emulator failed to become ready"

        # If prepare_kindle is True, install Kindle and navigate to Library
        if prepare_kindle:
            logger.info("Installing Kindle APK and navigating to Library view...")

            # Import necessary modules
            from automator import KindleAutomator
            from driver import Driver
            from server.utils.appium_driver import AppiumDriver
            from server.utils.request_utils import email_override
            from server.utils.vnc_instance_manager import VNCInstanceManager
            from views.state_machine import KindleStateMachine

            # Use email_override to ensure all operations use seed@clone.local
            with email_override(email):  # email is seed@clone.local here
                # Get the allocated VNC instance and ports for this email
                vnc_manager = VNCInstanceManager.get_instance()
                instance = vnc_manager.get_instance_for_profile(email)

                if not instance:
                    return False, "Failed to get VNC instance for seed clone"

                # Create a temporary automator instance
                automator = KindleAutomator()
                automator.profile_manager = self
                # Add emulator_manager reference needed by view inspector
                automator.emulator_manager = self.emulator_manager

                # Create and initialize driver
                driver_instance = Driver()
                driver_instance.automator = automator

                # Set the appium port from the VNC instance
                driver_instance.appium_port = instance.get("appium_port", 4723)

                # Ensure Appium is running for this instance
                appium_driver = AppiumDriver.get_instance()
                if not appium_driver.start_appium_for_profile(email):
                    return False, "Failed to start Appium for Kindle preparation"

                try:
                    # Initialize the driver (this will install Kindle if needed)
                    logger.info("Initializing driver to install Kindle APK...")
                    if not driver_instance.initialize():
                        return False, "Failed to initialize driver for Kindle installation"

                    # Set up all the cross-references that normally happen during initialization
                    # Get the device_id from the driver and propagate it
                    if hasattr(driver_instance, "device_id") and driver_instance.device_id:
                        automator.device_id = driver_instance.device_id
                        logger.info(f"Set device_id on automator: {automator.device_id}")

                    # For seed clone, we don't want to launch the app
                    logger.info("Kindle APK installed successfully. Skipping app launch for seed clone.")

                    # Navigate to Android home screen instead
                    logger.info("Navigating to Android home screen...")
                    device_id = driver_instance.device_id
                    if device_id:
                        # Press home button to go to Android dashboard
                        subprocess.run(
                            ["adb", "-s", device_id, "shell", "input", "keyevent", "KEYCODE_HOME"],
                            check=True,
                            capture_output=True,
                        )
                        logger.info("Successfully navigated to Android home screen")

                finally:
                    # Clean up driver and Appium but keep app running
                    if hasattr(driver_instance, "driver") and driver_instance.driver:
                        driver_instance.driver.quit()
                    appium_driver.stop_appium_for_profile(email)

                    # Give the app and system time to complete background processes
                    logger.info(
                        "Waiting 1 minute for background processes (Play Store updates, etc.) to complete..."
                    )
                    logger.info("This ensures the seed clone is fully prepared for copying")
                    # # Log progress every minute
                    # for minute in range(1, 2):
                    #     time.sleep(60)  # Wait 1 minute
                    #     logger.info(f"Seed clone preparation wait: {minute}/1 minute elapsed...")
                    logger.info("1-minute wait period complete, proceeding with shutdown")

        # Check if this is the seed clone
        if email == AVDCreator.SEED_CLONE_EMAIL:
            # For seed clone, just stop the emulator normally without snapshot
            logger.info(f"Stopping seed clone emulator normally (no snapshot)")
            launcher.stop_emulator(email)
            return True, "Seed clone prepared successfully"
        else:
            # Take snapshot (always saves to default)
            logger.info(f"Creating snapshot for {email}")
            if launcher.save_snapshot(email):
                logger.info(f"Successfully created snapshot for {email}")
                # Stop the emulator
                launcher.stop_emulator(email)
                return True, "Snapshot created successfully"
            else:
                return False, "Failed to create snapshot"

    def ensure_seed_clone_ready(self) -> Tuple[bool, str]:
        """
        Ensure the seed clone AVD is ready for use. This includes:
        1. Creating the seed clone AVD if it doesn't exist
        2. Starting it and waiting for it to be ready
        3. Installing Kindle and letting it settle for 10 minutes

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            seed_email = AVDCreator.SEED_CLONE_EMAIL

            # Check if seed clone already exists
            if self.avd_creator.has_seed_clone():
                logger.info("Seed clone AVD already exists")
                return True, "Seed clone is ready"

            # Seed clone doesn't exist at all, create it
            logger.info("Creating seed clone AVD for fast user initialization")
            success, avd_name = self.avd_creator.create_seed_clone_avd()
            if not success:
                return False, f"Failed to create seed clone AVD: {avd_name}"

            # Register the seed clone in profiles
            self.register_profile(seed_email, avd_name)

            # Start emulator and create snapshot
            success, message = self._start_emulator_and_create_snapshot(seed_email, prepare_kindle=True)
            if success:
                return True, "Seed clone is now ready"
            else:
                return False, f"Failed to prepare seed clone: {message}"

        except Exception as e:
            logger.error(f"Error ensuring seed clone ready: {e}", exc_info=True)
            return False, str(e)

    def update_seed_clone_snapshot(self) -> Tuple[bool, str]:
        """
        Update the seed clone AVD's snapshot. This is useful after fixing snapshot
        functionality or making changes to the base configuration.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            seed_email = AVDCreator.SEED_CLONE_EMAIL

            # Check if seed clone exists
            if not self.avd_creator.has_seed_clone():
                return False, "Seed clone AVD does not exist"

            # Check if emulator is running for seed clone
            is_running, emulator_id, avd_name = self.find_running_emulator_for_email(seed_email)

            if not is_running:
                logger.info("Starting seed clone emulator to create snapshot")
                # Start the emulator
                success, message = self.switch_profile_and_start_emulator(seed_email)
                if not success:
                    return False, f"Failed to start seed clone emulator: {message}"

                # Wait for it to be ready
                logger.info("Waiting for seed clone emulator to be ready...")
                time.sleep(10)

            # Save the snapshot
            logger.info("Saving snapshot for seed clone AVD")
            from server.utils.emulator_launcher import EmulatorLauncher

            launcher = EmulatorLauncher(self.android_home, self.avd_dir, self.host_arch)

            if launcher.save_snapshot(seed_email):
                # Update the timestamp
                self.set_user_field(seed_email, "last_snapshot_timestamp", int(time.time()))
                return True, "Successfully updated seed clone snapshot"
            else:
                return False, "Failed to save seed clone snapshot"

        except Exception as e:
            logger.error(f"Error updating seed clone snapshot: {e}", exc_info=True)
            return False, str(e)

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

    def _load_profiles_index(self) -> Dict[str, str]:
        """Load profiles index from JSON file or create if it doesn't exist."""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r") as f:
                    data = json.load(f)
                    self.profiles_index = data
                    return data
            except Exception as e:
                logger.error(f"Error loading profiles index: {e}", exc_info=True)
                return {}
        else:
            logger.info(f"Profiles index not found at {self.users_file}, creating empty index")
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(self.users_file), exist_ok=True)
            # Save an empty profiles index
            empty_index = {}
            with open(self.users_file, "w") as f:
                json.dump(empty_index, f, indent=2)
            return empty_index

    def _save_profiles_index(self) -> None:
        """Save profiles index to JSON file."""
        try:
            with open(self.users_file, "w") as f:
                json.dump(self.profiles_index, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving profiles index: {e}", exc_info=True)

    # Removed _load_current_profile method as we're managing multiple users simultaneously

    def _load_user_preferences(self) -> Dict[str, Dict]:
        """
        Load user preferences from profiles_index under the 'preferences' key.
        Returns a separate dictionary for easier access.
        """
        preferences = {}

        # Extract preferences from the profiles_index
        for email, profile_data in self.profiles_index.items():
            if "preferences" in profile_data:
                preferences[email] = profile_data["preferences"]
            else:
                # Initialize empty preferences if not yet created
                preferences[email] = {}

        return preferences

    def _save_user_preferences(self) -> None:
        """
        Save user preferences to the profiles_index.
        This ensures preferences are only stored in the "preferences" key.

        This is a backward compatibility method - new code should use set_user_field.
        """
        try:
            # Update the profiles_index with preferences data
            for email, prefs in self.user_preferences.items():
                if email in self.profiles_index:
                    # Create preferences structure if it doesn't exist
                    if "preferences" not in self.profiles_index[email]:
                        self.profiles_index[email]["preferences"] = {}

                    # Update preferences in the profile - ONLY in the preferences key
                    for key, value in prefs.items():
                        # Store all preferences in the preferences section
                        self.profiles_index[email]["preferences"][key] = value

            # Now save the updated profiles_index
            self._save_profiles_index()

            # Reload user preferences from profiles_index to ensure our cache is up-to-date
            self.user_preferences = self._load_user_preferences()
        except Exception as e:
            logger.error(f"Error saving user preferences: {e}", exc_info=True)

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
        return self.device_discovery.find_running_emulator_for_email(email, self.profiles_index)

    def set_user_field(self, email: str, field: str, value, section: str = None) -> bool:
        """
        Set a field for a user profile at the specified section level.

        Args:
            email: Email address of the profile
            field: Field name to set
            value: Value to set for the field
            section: Section to set the field in (e.g. "preferences"). If None, sets at top level.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Reload profiles to ensure we have the latest data
            self._load_profiles_index()

            # Make sure the email exists in profiles_index
            if email not in self.profiles_index:
                logger.warning(f"Cannot update field {field}: email {email} not found in profiles_index")
                return False

            # If section is specified, ensure it exists
            if section:
                if section not in self.profiles_index[email]:
                    self.profiles_index[email][section] = {}

                # Set value in the specified section
                self.profiles_index[email][section][field] = value
            else:
                # Set value at top level
                self.profiles_index[email][field] = value

            # Save the updated profiles_index
            self._save_profiles_index()
            logger.info(f"Updated {section + '.' if section else ''}field {field} for {email} to {value}")
            return True
        except Exception as e:
            logger.error(f"Error setting user field {field} for {email}: {e}", exc_info=True)
            return False

    def get_user_field(self, email: str, field: str, default=None, section: str = None):
        """
        Get a field value from a user profile at the specified section level.

        Args:
            email: Email address of the user
            field: Field name to get
            default: Default value to return if field not found
            section: Section to get the field from (e.g. "preferences"). If None, gets from top level.

        Returns:
            The field value or default if not found
        """
        try:
            # Make sure the email exists in profiles_index
            if email not in self.profiles_index:
                return default

            # If section is specified, check if it exists
            if section:
                if section not in self.profiles_index[email]:
                    return default

                # Get value from the specified section
                return self.profiles_index[email][section].get(field, default)
            else:
                # Get value from top level
                return self.profiles_index[email].get(field, default)
        except Exception as e:
            logger.error(f"Error getting user field {field} for {email}: {e}", exc_info=True)
            return default

    def update_auth_state(self, email: str, authenticated: bool) -> bool:
        """
        Update authentication state for a user profile.

        When authenticated=True:
        - Sets auth_date to current timestamp
        - Clears auth_failed_date

        When authenticated=False:
        - Sets auth_failed_date to current timestamp
        - Does not modify auth_date

        Args:
            email: Email address of the profile
            authenticated: Whether the user is authenticated

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            from datetime import datetime

            current_date = datetime.now().isoformat()

            if authenticated:
                # User is authenticated - set auth_date and clear auth_failed_date
                logger.info(f"Setting auth_date for {email} as user is authenticated")
                self.set_user_field(email, "auth_date", current_date)

                # Clear auth_failed_date if it exists
                auth_failed_date = self.get_user_field(email, "auth_failed_date")
                if auth_failed_date:
                    logger.info(f"Clearing auth_failed_date for {email}")
                    self.set_user_field(email, "auth_failed_date", None)
            else:
                # User lost authentication - set auth_failed_date
                logger.info(f"Setting auth_failed_date for {email} as user lost authentication")
                self.set_user_field(email, "auth_failed_date", current_date)

            return True
        except Exception as e:
            logger.error(f"Error updating auth state for {email}: {e}", exc_info=True)
            return False

    def _save_profile_status(self, email: str, avd_name: str, emulator_id: Optional[str] = None) -> None:
        """
        Save profile status to the profiles_index directly.

        Also updates the emulator_id in the VNC instance if available.

        Args:
            email: Email address of the profile
            avd_name: Name of the AVD
            emulator_id: Optional emulator device ID (e.g., 'emulator-5554')
        """
        # Make sure the email exists in profiles_index
        if email not in self.profiles_index:
            self.profiles_index[email] = {}

        # Update the profile status fields
        self.profiles_index[email]["last_used"] = int(time.time())
        self.profiles_index[email]["last_used_date"] = datetime.now().isoformat()
        self.profiles_index[email]["avd_name"] = avd_name
        self.profiles_index[email]["email"] = email

        # Store the emulator ID in the VNC instance where it belongs
        if emulator_id:
            try:
                from server.utils.vnc_instance_manager import VNCInstanceManager

                vnc_manager = VNCInstanceManager.get_instance()
                vnc_manager.set_emulator_id(email, emulator_id)
            except Exception as e:
                logger.warning(f"Error storing emulator ID in VNC instance: {e}")
                # No longer storing emulator_id in profiles - VNC instance manager is the source of truth

        # Only store preferences in the designated "preferences" key
        # Ensure we don't duplicate preference data at root level
        if email in self.user_preferences:
            # Create preferences structure if it doesn't exist
            if "preferences" not in self.profiles_index[email]:
                self.profiles_index[email]["preferences"] = {}

            # Copy preferences to the designated location only
            self.profiles_index[email]["preferences"] = self.user_preferences[email]

        # Save the updated profiles_index
        self._save_profiles_index()

        # Also update our local user_preferences cache for consistency
        # This ensures we have the latest preferences from users.json
        self.user_preferences = self._load_user_preferences()

    def get_avd_for_email(self, email: str) -> Optional[str]:
        """
        Get the AVD name for a given email address.

        Args:
            email: Email address to lookup

        Returns:
            Optional[str]: The associated AVD name or None if not found
        """
        # Check if we have a mapping in the profiles index
        if email in self.profiles_index:
            profile_entry = self.profiles_index.get(email)
            if "avd_name" in profile_entry:
                return profile_entry["avd_name"]

        # If not found, create a standardized AVD name
        return self.get_avd_name_from_email(email)

    def get_vnc_instance_for_email(self, email: str) -> Optional[int]:
        """
        Get the VNC instance number assigned to this email profile.

        Args:
            email: Email address to lookup

        Returns:
            Optional[int]: The VNC instance number or None if not assigned
        """
        if email in self.profiles_index:
            profile_entry = self.profiles_index.get(email)

            # Handle different formats
            if isinstance(profile_entry, dict) and "vnc_instance" in profile_entry:
                return profile_entry["vnc_instance"]

        return None

    def get_appium_port_for_email(self, email: str) -> Optional[int]:
        """
        Get the Appium port assigned to this email profile.

        This method first checks for a VNC instance assignment, and if found,
        returns the Appium port from that VNC instance.

        For backward compatibility, it will fall back to the old method of
        looking in the profiles_index.

        Args:
            email: Email address to lookup

        Returns:
            Optional[int]: The Appium port or None if not assigned
        """
        # Use centralized port utilities for all port calculations
        from server.utils.port_utils import calculate_appium_port

        # Check if we're on macOS development environment - use centralized check
        # Port utils will handle the macOS special case internally
        try:
            # First try to get the appium_port from the VNC instance manager
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            appium_port = vnc_manager.get_appium_port(email)
            if appium_port:
                return appium_port
        except Exception as e:
            logger.warning(f"Error getting Appium port from VNC instance: {e}")

        # Fall back to the old method for backward compatibility
        if email in self.profiles_index:
            profile_entry = self.profiles_index.get(email)

            # Handle different formats
            if isinstance(profile_entry, dict) and "appium_port" in profile_entry:
                logger.warning(f"Using deprecated profiles_index appium_port for {email}")
                return profile_entry["appium_port"]

        # Use centralized port calculation as final fallback
        # This handles macOS special case automatically
        return calculate_appium_port(email=email)

    def get_emulator_id_for_avd(self, avd_name: str) -> Optional[str]:
        """
        Get the emulator device ID for a given AVD name.

        Args:
            avd_name: Name of the AVD to find

        Returns:
            Optional[str]: The emulator ID if found, None otherwise
        """

        # First check if emulator_manager has cached info
        cached_info = None
        if hasattr(self.emulator_manager, "_emulator_cache"):
            for email, (emulator_id, cached_avd_name, _) in self.emulator_manager._emulator_cache.items():
                if cached_avd_name == avd_name:
                    logger.info(
                        f"Found cached emulator {emulator_id} for AVD {avd_name} (cached for email={email})"
                    )
                    cached_info = (avd_name, emulator_id)
                    break
        else:
            logger.info(f"No emulator cache found")

        # Look for running emulators with this AVD name
        running_emulators = self.device_discovery.map_running_emulators(
            self.profiles_index, cached_info=cached_info
        )

        emulator_id = running_emulators.get(avd_name)

        # CRITICAL: Only return an emulator ID if it actually matches this AVD
        # This prevents cross-user emulator access
        if emulator_id and not cached_info:
            # Verify this emulator is actually running the requested AVD
            actual_avd = self.device_discovery._query_emulator_avd_name(emulator_id)
            if actual_avd != avd_name:
                logger.error(
                    f"CRITICAL: Emulator {emulator_id} is running AVD {actual_avd}, "
                    f"not {avd_name}. Returning None to prevent cross-user access.",
                    exc_info=True,
                )
                return None

        logger.info(
            f"Found emulator id: {emulator_id} for AVD: {avd_name}. All running emulators: {running_emulators}"
        )
        return emulator_id

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
            # Check if we have an existing entry and preserve its format
            if email in self.profiles_index:
                existing_entry = self.profiles_index.get(email)

                # If it's a dictionary, update the avd_name field
                if isinstance(existing_entry, dict):
                    existing_entry["avd_name"] = avd_name
                    self.profiles_index[email] = existing_entry
                else:
                    # Convert string to dictionary format for consistency
                    self.profiles_index[email] = {"avd_name": avd_name}
            else:
                # Create a new entry in the new format
                self.profiles_index[email] = {"avd_name": avd_name}

            self._save_profiles_index()

            # Update profile status (replaces old current_profile concept)
            self._save_profile_status(email, avd_name)

            logger.info(f"Updated AVD name for {email} to {avd_name}")
            return True
        except Exception as e:
            logger.error(f"Error updating AVD name for {email}: {e}", exc_info=True)
            return False

    def list_profiles(self) -> List[Dict]:
        """
        List all available profiles with their details.

        Returns:
            List[Dict]: List of profile information dictionaries
        """
        # First get running emulators
        running_emulators = self.device_discovery.map_running_emulators(self.profiles_index)

        result = []
        for email, profile_entry in self.profiles_index.items():
            # Get profile information
            avd_name = profile_entry.get("avd_name")
            appium_port = profile_entry.get("appium_port")
            vnc_instance = profile_entry.get("vnc_instance")

            if not avd_name:
                logger.warning(f"No AVD name found for profile {email}")
                continue

            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")

            # Get emulator ID if the AVD is running
            emulator_id = running_emulators.get(avd_name)

            # If we didn't find it, check if any running emulator has email in its name
            if not emulator_id:
                is_running, found_emulator_id, _ = self.find_running_emulator_for_email(email)
                if is_running:
                    emulator_id = found_emulator_id

            # Build profile info with all available details
            profile_info = {
                "email": email,
                "avd_name": avd_name,
                "exists": os.path.exists(avd_path),
                "current": False,  # No concept of "current" profile anymore
                "emulator_id": emulator_id,
            }

            # Add optional information if available
            if appium_port:
                profile_info["appium_port"] = appium_port
            if vnc_instance:
                profile_info["vnc_instance"] = vnc_instance

            # Add Android version information if available
            android_version = profile_entry.get("android_version")
            if android_version:
                profile_info["android_version"] = android_version

            # Add system image information if available
            system_image = profile_entry.get("system_image")
            if system_image:
                profile_info["system_image"] = system_image

            result.append(profile_info)
        return result

    def get_profile_for_email(self, email: str) -> Optional[Dict]:
        """
        Get information about a specific profile by email.

        Args:
            email: The email address to get profile information for

        Returns:
            Optional[Dict]: Profile information or None if the profile doesn't exist
        """
        if not email:
            logger.warning("get_profile_for_email called with empty email")
            return None

        # Check if the email exists in profiles_index
        if email not in self.profiles_index:
            logger.warning(f"Email {email} not found in profiles_index")
            return None

        # Get the AVD name for this email
        profile_entry = self.profiles_index[email]

        if "avd_name" in profile_entry:
            avd_name = profile_entry["avd_name"]
        else:
            logger.error(f"Could not determine AVD name from profile entry for {email}", exc_info=True)
            return None

        # Build profile information
        profile = {
            "email": email,
            "avd_name": avd_name,
        }

        # Try to get emulator_id from VNC instance first
        try:
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            emulator_id = vnc_manager.get_emulator_id(email)

            if emulator_id:
                profile["emulator_id"] = emulator_id
            else:
                # If not found in VNC instance, look for a running emulator
                is_running, emulator_id, _ = self.find_running_emulator_for_email(email)

                if is_running and emulator_id:
                    profile["emulator_id"] = emulator_id

                    # Update VNC instance with the found emulator ID
                    vnc_manager.set_emulator_id(email, emulator_id)

                else:
                    # Fallback to user preferences for backward compatibility
                    if email in self.user_preferences and "emulator_id" in self.user_preferences[email]:
                        emulator_id = self.user_preferences[email]["emulator_id"]
                        profile["emulator_id"] = emulator_id

                        # Move to VNC instance
                        vnc_manager.set_emulator_id(email, emulator_id)
        except Exception as e:
            logger.warning(f"Error getting emulator_id from VNC instance: {e}")

            # Fallback to the original approach
            is_running, emulator_id, _ = self.find_running_emulator_for_email(email)
            if is_running and emulator_id:
                profile["emulator_id"] = emulator_id
                self._save_profile_status(email, avd_name, emulator_id)

            # Check legacy storage in preferences
            elif email in self.user_preferences and "emulator_id" in self.user_preferences[email]:
                emulator_id = self.user_preferences[email]["emulator_id"]
                profile["emulator_id"] = emulator_id

        # Add any preferences if available
        if email in self.user_preferences:
            for key, value in self.user_preferences[email].items():
                if (
                    key not in profile and key != "emulator_id"
                ):  # Skip emulator_id which should come from VNC instance
                    profile[key] = value

        return profile

    def get_current_profile(self) -> Optional[Dict]:
        """
        In the multi-user system, we'll attempt to find a running emulator and return
        its associated profile information.

        Returns:
            Optional[Dict]: Profile information for a running emulator or None if none found
        """
        sindarin_email = get_sindarin_email()

        # Special case for macOS development environment
        is_mac_dev = os.getenv("ENVIRONMENT", "DEV").lower() == "dev" and platform.system() == "Darwin"

        # First check if we have a valid cached profile and emulator
        if (
            sindarin_email
            and hasattr(self.emulator_manager, "_emulator_cache")
            and sindarin_email in self.emulator_manager._emulator_cache
        ):
            emulator_id, avd_name, cache_time = self.emulator_manager._emulator_cache[sindarin_email]

            # Quick verification that the emulator is still running
            if self.emulator_manager.emulator_launcher._verify_emulator_running(emulator_id, sindarin_email):
                # Check if we have this profile
                if sindarin_email in self.profiles_index:
                    profile = self.profiles_index[sindarin_email].copy()  # Make a copy

                    # Add user preferences if available
                    if sindarin_email in self.user_preferences:
                        for key, value in self.user_preferences[sindarin_email].items():
                            if key not in profile:  # Don't overwrite profile data
                                profile[key] = value

                    # Update it with the running emulator ID
                    profile["emulator_id"] = emulator_id
                    # Update last used timestamp
                    profile["last_used"] = int(time.time())
                    profile["last_used_date"] = datetime.now().isoformat()
                    return profile
            else:
                logger.info(f"Cached emulator {emulator_id} no longer running, clearing cache")
                del self.emulator_manager._emulator_cache[sindarin_email]

        # Only call map_running_emulators if we don't have valid cached data
        cached_info = None
        if (
            sindarin_email
            and hasattr(self.emulator_manager, "_emulator_cache")
            and sindarin_email in self.emulator_manager._emulator_cache
        ):
            emulator_id, avd_name, _ = self.emulator_manager._emulator_cache[sindarin_email]
            cached_info = (avd_name, emulator_id)

        # Check for running emulators
        running_emulators = self.device_discovery.map_running_emulators(
            self.profiles_index, cached_info=cached_info
        )

        # Special case for macOS development environment
        is_mac_dev = os.getenv("ENVIRONMENT", "DEV").lower() == "dev" and platform.system() == "Darwin"

        # Always check if we have a profile for the current user
        if sindarin_email in self.profiles_index:
            profile = self.profiles_index[sindarin_email]

            # Also check if there's a running emulator at all
            try:
                result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    has_emulator = any("emulator-" in line for line in lines[1:])

                    if has_emulator or is_mac_dev:
                        # Add user preferences if available
                        if sindarin_email in self.user_preferences:
                            for key, value in self.user_preferences[sindarin_email].items():
                                if key not in profile:  # Don't overwrite profile
                                    profile[key] = value

                        return profile
            except Exception as e:
                logger.warning(f"Error checking for running emulators: {e}")

        # Fallback to original logic if needed
        if running_emulators or is_mac_dev:
            # First, try to find a profile that matches one of the running emulators
            for email, profile in self.profiles_index.items():
                if email != sindarin_email:
                    continue

                # Add user preferences if available
                if email in self.user_preferences:
                    for key, value in self.user_preferences[email].items():
                        if key not in profile:  # Don't overwrite profile
                            profile[key] = value

                return profile

        return None

    def register_profile(self, email: str, avd_name: str, vnc_instance: int = None) -> None:
        """
        Register a profile by associating an email with an AVD name.

        Args:
            email: The email address to register
            avd_name: The AVD name to associate with this email
            vnc_instance: Optional VNC instance number to assign to this profile
        """
        # Check if the email already exists before we add it
        if email not in self.profiles_index:
            self.profiles_index[email] = {}

        # Update with new values
        self.profiles_index[email]["avd_name"] = avd_name

        # Add VNC instance if provided
        if vnc_instance is not None:
            self.profiles_index[email]["vnc_instance"] = vnc_instance

        # Save to file
        try:
            self._save_profiles_index()
        except Exception as save_e:
            logger.error(f"Error saving profiles_index: {save_e}", exc_info=True)

        # Build and log the registration message
        log_message = f"Registered profile for {email} with AVD {avd_name}"
        if vnc_instance is not None:
            log_message += f" on VNC instance {vnc_instance}"
        logger.info(log_message)

    def register_email_to_avd(self, email: str, default_avd_name: str = "Pixel_API_30") -> None:
        """
        Register an email to an AVD for development purposes.

        Args:
            email: The email to register
            default_avd_name: Default AVD name to use if no AVD can be found
        """
        # First check if we already have a mapping
        if email in self.profiles_index:
            return

        # Create a standardized AVD name for this email first
        normalized_avd_name = self.get_avd_name_from_email(email)
        logger.info(f"Generated standardized AVD name {normalized_avd_name} for {email}")

        # Never use another user's running emulator - always use the standardized AVD name
        logger.info(f"Registering email {email} to standardized AVD {normalized_avd_name}")
        self.register_profile(email, normalized_avd_name)

        # Try to find if this user's AVD is already running
        running_emulators = self.device_discovery.map_running_emulators(self.profiles_index)
        if normalized_avd_name in running_emulators:
            emulator_id = running_emulators[normalized_avd_name]
            logger.info(f"Found user's AVD {normalized_avd_name} already running at {emulator_id}")
            self._save_profile_status(email, normalized_avd_name, emulator_id)
        else:
            self._save_profile_status(email, normalized_avd_name)

    def stop_emulator(self, device_id: str) -> bool:
        """
        Stop an emulator by device ID or the currently running emulator.

        Args:
            device_id: Optional device ID to stop a specific emulator.
                       If None, stops whatever emulator is running.

        Returns:
            bool: True if successful, False otherwise
        """
        return self.emulator_manager.stop_specific_emulator(device_id)

    def start_emulator(self, email: str) -> bool:
        """
        Start the specified AVD.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        return self.emulator_manager.start_emulator_with_retries(email)

    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """
        Create a new AVD for the given email.

        Returns:
            Tuple[bool, str]: (success, avd_name)
        """
        return self.avd_creator.create_new_avd(email)

    def _create_avd_with_seed_clone_fallback(self, email: str, normalized_avd_name: str) -> str:
        """
        Create a new AVD using seed clone if available, otherwise fall back to normal creation.

        Args:
            email: User's email address
            normalized_avd_name: The normalized AVD name for this email

        Returns:
            str: The final AVD name
        """
        # Check if we can use the seed clone for faster AVD creation
        if self.avd_creator.is_seed_clone_ready():
            logger.info("Seed clone is ready - using fast AVD copy method")
            success, result = self.avd_creator.copy_avd_from_seed_clone(email)
            if success:
                logger.info(f"Successfully created AVD {result} from seed clone for {email}")
                return result
            else:
                logger.warning(f"Failed to copy seed clone: {result}, falling back to normal creation")

        # Seed clone not ready or failed, use normal AVD creation
        logger.info("Using normal AVD creation")
        success, result = self.create_new_avd(email)
        if not success:
            logger.warning(f"Failed to create AVD: {result}, but profile was registered")
            return normalized_avd_name
        else:
            return result

    def _get_preference_value(self, email: str, key: str, default=None):
        """
        Get a preference value for a user from the preferences section.

        This is a backward compatibility method - new code should use get_user_field.

        Args:
            email: Email address of the user
            key: Preference key to get
            default: Default value to return if preference not found

        Returns:
            The preference value or default if not found
        """
        # Use preferences section for all keys
        return self.get_user_field(email, key, default, section="preferences")

    def is_styles_updated(self) -> bool:
        """
        Check if styles have been updated for a profile.

        Args:
            email: The email address of the profile to check. If None, returns False.

        Returns:
            bool: True if styles have been updated, False otherwise
        """
        email = get_sindarin_email()
        if not email:
            logger.warning("No email available to check styles_updated")
            return False

        # Get the styles_updated from the top level
        if email in self.profiles_index:
            return self.profiles_index[email].get("styles_updated", False)
        return False

    def _set_preference_value(self, email: str, key: str, value):
        """
        Set a preference value for a user in the preferences section.

        This is a backward compatibility method - new code should use set_user_field.

        Args:
            email: Email address of the user
            key: Preference key to set
            value: Value to set

        Returns:
            bool: True if successful, False otherwise
        """
        # Use preferences section for all keys
        return self.set_user_field(email, key, value, section="preferences")

    def get_style_setting(self, setting_name: str, email: str = None, default=None):
        """
        Get a style setting value from the profile.

        Args:
            setting_name: The name of the setting to retrieve
            email: Optional email. If not provided, uses the current sindarin email.
            default: Default value to return if setting doesn't exist

        Returns:
            The setting value if found, otherwise the default value
        """
        try:
            # Get email if not provided
            if not email:
                email = get_sindarin_email()
                if not email:
                    logger.warning("No email available to get style setting")
                    return default

            # Look for library_settings at the top level
            if email in self.profiles_index:
                profile = self.profiles_index[email]
                if "library_settings" in profile:
                    library_settings = profile["library_settings"]
                    if setting_name in library_settings:
                        return library_settings[setting_name]

            return default
        except Exception as e:
            logger.error(f"Error getting style setting {setting_name}: {e}", exc_info=True)
            return default

    def save_style_setting(self, setting_name: str, setting_value, email: str = None) -> bool:
        """
        Save a style setting in a single line. Handles all the complexity of preference management.

        Args:
            setting_name: Name of the setting (e.g., 'group_by_series', 'view_type')
            setting_value: Value to set (can be any type)
            email: Email of the user. If None, uses get_sindarin_email()

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get email if not provided
            if not email:
                email = get_sindarin_email()
                if not email:
                    logger.warning("No email available to save style setting")
                    return False

            # Ensure profile structure exists
            if email not in self.profiles_index:
                self.profiles_index[email] = {}

            # Save library_settings at the top level
            if "library_settings" not in self.profiles_index[email]:
                self.profiles_index[email]["library_settings"] = {}

            # Save the setting
            self.profiles_index[email]["library_settings"][setting_name] = setting_value

            # Persist to disk
            self._save_profiles_index()

            logger.info(f"Saved library style setting {setting_name}={setting_value} for {email}")
            return True
        except Exception as e:
            logger.error(f"Error saving style setting {setting_name}: {e}", exc_info=True)
            return False

    def update_style_preference(self, is_updated: bool, email: str = None) -> bool:
        """
        Update the styles_updated preference for a profile.

        Args:
            is_updated: Boolean indicating whether styles have been updated
            email: The email address of the profile to update. If None, returns False.

        Returns:
            bool: True if the update was successful, False otherwise
        """
        try:
            if not email:
                logger.warning("No email provided to update style preference")
                return False

            # Get the AVD name for this email
            avd_name = self.get_avd_for_email(email)
            if not avd_name:
                logger.warning(f"No AVD name found for email {email}")
                return False

            # Make sure the email exists in profiles_index
            if email not in self.profiles_index:
                logger.info(f"Creating new profile entry for {email}")
                self.profiles_index[email] = {}

            # Make sure the preferences section exists for this email
            if "preferences" not in self.profiles_index[email]:
                logger.info(f"Initializing preferences section for {email}")
                self.profiles_index[email]["preferences"] = {}

            # Make sure the email exists in user_preferences
            if email not in self.user_preferences:
                logger.info(f"Initializing user preferences for {email}")
                self.user_preferences[email] = {}

            # Update style preference at the top level
            self.profiles_index[email]["styles_updated"] = is_updated

            # Initialize reading_settings at top level if needed
            if "reading_settings" not in self.profiles_index[email]:
                logger.info(f"Initializing reading_settings for {email}")
                self.profiles_index[email]["reading_settings"] = {}

            # Update various reading settings - keep these values synced
            # with what's saved in the actual reading style sheet
            reading_settings = self.profiles_index[email]["reading_settings"]
            if is_updated:
                # These are the default settings we apply when styles_updated is True
                reading_settings["theme"] = "dark"
                reading_settings["font_size"] = "small"
                reading_settings["real_time_highlighting"] = False
                reading_settings["about_book"] = False
                reading_settings["page_turn_animation"] = False
                reading_settings["popular_highlights"] = False
                reading_settings["highlight_menu"] = False

            # Save all changes
            self._save_profiles_index()

            logger.info(f"Successfully updated style preferences for {email} to {is_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating style preference: {e}", exc_info=True)
            return False

    def switch_profile_and_start_emulator(
        self, email: str, force_new_emulator: bool = False
    ) -> Tuple[bool, str]:
        """
        Switch to the profile for the given email. If the profile doesn't exist, create a new one.
        With the multi-emulator approach, this method will:
        1. Try to find a running emulator for this email first
        2. If not found, start a new emulator for this profile
        3. No longer stop other emulators unless explicitly forced

        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any existing emulator for this profile and start a new one
                              (used with recreate=1 flag)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # If we're forcing a new emulator, reset device settings in the profile
        if force_new_emulator:
            # Reset all device-specific settings for this profile under emulator_settings
            settings_to_reset = [
                "hw_overlays_disabled",
                "animations_disabled",
                "sleep_disabled",
                "status_bar_disabled",
                "auto_updates_disabled",
            ]
            for setting in settings_to_reset:
                self.set_user_field(email, setting, False, section="emulator_settings")

        # Special case: Simplified mode for Mac development environment
        if self.use_simplified_mode:
            return True, f"Tracking profile for {email} in simplified mode"

        #
        # Normal profile management mode below (for non-Mac or non-dev environments)
        # Now with multi-emulator support
        #

        # Get AVD name for this email - this should be the first step
        avd_name = self.get_avd_for_email(email)

        # If no AVD exists for this email, create one
        if not avd_name:
            logger.info(f"No AVD found for {email}, creating new one")

            # Create a normalized AVD name based on the email
            normalized_avd_name = self.get_avd_name_from_email(email)
            logger.info(f"Generated AVD name {normalized_avd_name} for {email}")

            # First register this AVD name in profiles_index so VNC can find it
            self.register_profile(email, normalized_avd_name)
            logger.info(f"Registered AVD {normalized_avd_name} for email {email} in profiles_index")

            # Create AVD using seed clone if available
            avd_name = self._create_avd_with_seed_clone_fallback(email, normalized_avd_name)

            # Update the profile with the final AVD name if different
            if avd_name != normalized_avd_name:
                self.register_profile(email, avd_name)

        # Check if this AVD actually exists - it might not if we're using
        # manually registered AVDs but the Android Studio AVD was renamed or deleted
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_ini_path = os.path.join(self.avd_dir, f"{avd_name}.ini")
        # AVD is only valid if both the directory and ini file exist
        avd_exists = os.path.exists(avd_path) and os.path.exists(avd_ini_path)

        # First check if there's already a running emulator for this email
        is_running, emulator_id, found_avd_name = self.find_running_emulator_for_email(email)

        # If we found a running emulator for this email but need to force a new one
        if is_running and force_new_emulator:
            logger.info(
                f"Found running emulator {emulator_id} for profile {email}, but force_new_emulator=True"
            )
            logger.info(f"Stopping emulator {emulator_id} to start a fresh one")
            # Stop only this specific emulator, not others
            if not self.stop_emulator(emulator_id):
                logger.error(f"Failed to stop emulator {emulator_id} for profile {email}", exc_info=True)
                # We'll try to continue anyway
            # Clear the is_running flag so we'll start a new emulator
            is_running = False
            emulator_id = None

        # If we found a running emulator for this email and aren't forcing a new one, use it
        if is_running and not force_new_emulator:
            logger.info(f"Found running emulator {emulator_id} for profile {email} (AVD: {found_avd_name})")

            # Check if the found running emulator's AVD matches what we're expecting for this user
            # If it doesn't match, we should fail rather than use another user's AVD
            if found_avd_name != avd_name:
                logger.warning(
                    f"Found running emulator uses AVD {found_avd_name}, but user {email} requires {avd_name}"
                )
                logger.warning(f"Will not use another user's emulator for {email}")
                return False, f"Cannot use another user's emulator for {email}"

            # We already verified found_avd_name equals avd_name above, so no need to update it

            # Save the profile status with the found emulator
            self._save_profile_status(email, avd_name, emulator_id)
            logger.info(f"Using existing running emulator for profile {email}")
            return True, f"Switched to profile {email} with existing running emulator"

        # For Mac M1/M2/M4 users where direct emulator launch might fail,
        # we'll just track the profile without trying to start the emulator
        if self.host_arch == "arm64" and platform.system() == "Darwin":
            logger.info(f"Running on ARM Mac - skipping emulator start, just tracking profile change")
            # Update profile status
            self._save_profile_status(email, avd_name)

            if not avd_exists:
                logger.warning(
                    f"AVD {avd_name} doesn't exist at {avd_path}. If using Android Studio AVDs, "
                    f"please run 'make register-avd' to update the AVD name for this profile."
                )
            return True, f"Switched profile tracking to {email} (AVD: {avd_name})"

        # Check if AVD exists before trying to start it
        if not avd_exists:
            logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. Attempting to create it.")

            # Check if this user requires ALT_SYSTEM_IMAGE
            requires_alt_image = email in self.avd_creator.ALT_IMAGE_TEST_EMAILS

            # Check if we can use the seed clone for faster AVD creation
            # Skip seed clone for ALT_IMAGE users since seed clone uses Android 30
            if self.avd_creator.is_seed_clone_ready() and not requires_alt_image:
                logger.info("Seed clone is ready - using fast AVD copy method")
                success, result = self.avd_creator.copy_avd_from_seed_clone(email)
                if success:
                    avd_name = result
                    logger.info(f"Successfully created AVD {avd_name} from seed clone for {email}")
                else:
                    logger.warning(f"Failed to copy seed clone: {result}, falling back to normal creation")
                    # Fall back to normal AVD creation
                    success, result = self.create_new_avd(email)
                    if not success:
                        logger.error(f"Failed to create AVD: {result}", exc_info=True)
                        return False, f"Failed to create AVD for {email}: {result}"
                    avd_name = result
            else:
                # Either seed clone not ready or user requires ALT_SYSTEM_IMAGE
                if requires_alt_image:
                    logger.info(
                        f"User {email} requires ALT_SYSTEM_IMAGE (Android 36), using normal AVD creation"
                    )
                else:
                    logger.info("Seed clone not ready, using normal AVD creation")
                success, result = self.create_new_avd(email)
                if not success:
                    logger.error(f"Failed to create AVD: {result}", exc_info=True)
                    return False, f"Failed to create AVD for {email}: {result}"
                avd_name = result

            # Update profile with new AVD
            self.register_profile(email, avd_name)
            logger.info(f"Created new AVD {avd_name} for {email}")

        # Start the emulator
        if self.start_emulator(email):
            # We need to get the emulator ID for the started emulator
            started_emulator_id = self.get_emulator_id_for_avd(avd_name)
            self._save_profile_status(email, avd_name, started_emulator_id)
            logger.info(f"Successfully started emulator {started_emulator_id} for profile {email}")
            return True, f"Switched to profile {email} with new emulator"
        else:
            # Failed to start emulator, but still update the profile status for tracking
            self._save_profile_status(email, avd_name)
            logger.error(
                f"Failed to start emulator for profile {email}, but updated profile tracking", exc_info=True
            )
            return False, f"Failed to start emulator for profile {email}"

    def recreate_profile_avd(
        self, email: str, recreate_user: bool = True, recreate_seed: bool = True
    ) -> Tuple[bool, str]:
        """
        Completely recreate AVD for a profile. This will:
        1. Stop any running emulators (user and/or seed clone based on parameters)
        2. Delete the user's AVD (if recreate_user=True)
        3. Delete the seed clone AVD (if recreate_seed=True)
        4. Clean up profile data (if recreate_user=True)
        5. Clean up any existing automator

        Args:
            email: The user's email address
            recreate_user: Whether to recreate the user's AVD (default True)
            recreate_seed: Whether to recreate the seed clone AVD (default True for backwards compatibility)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        actions = []
        if recreate_user:
            actions.append("user AVD")
        if recreate_seed:
            actions.append("seed clone")

        logger.info(f"Recreating profile AVD for {email} - will recreate: {', '.join(actions)}")

        try:
            # Stop user's emulator if running (only if recreating user AVD)
            if recreate_user:
                user_emulator_id, _ = self.emulator_manager.emulator_launcher.get_running_emulator(email)
                if user_emulator_id:
                    logger.info(f"Stopping running emulator for {email}")
                    self.emulator_manager.emulator_launcher.stop_emulator(email)
                    time.sleep(2)  # Give it time to shut down

            # Stop seed clone emulator if running (only if recreating seed clone)
            if recreate_seed:
                seed_emulator_id, _ = self.emulator_manager.emulator_launcher.get_running_emulator(
                    AVDCreator.SEED_CLONE_EMAIL
                )
                if seed_emulator_id:
                    logger.info("Stopping running seed clone emulator")
                    self.emulator_manager.emulator_launcher.stop_emulator(AVDCreator.SEED_CLONE_EMAIL)
                    time.sleep(2)  # Give it time to shut down

            # Delete the user's AVD (only if recreate_user=True)
            avd_name = None
            if recreate_user:
                avd_name = self.avd_creator.get_avd_name_from_email(email)
                logger.info(f"Deleting user AVD: {avd_name}")
                success, msg = self.avd_creator.delete_avd(email)
                if not success:
                    logger.error(f"Failed to delete user AVD through avdmanager: {msg}", exc_info=True)
                    raise Exception(f"Failed to delete user AVD: {msg}")

            # Delete the seed clone AVD (only if recreate_seed=True)
            seed_avd_name = None
            if recreate_seed:
                seed_avd_name = self.avd_creator.get_avd_name_from_email(AVDCreator.SEED_CLONE_EMAIL)
                logger.info(f"Deleting seed clone AVD: {seed_avd_name}")
                success, msg = self.avd_creator.delete_avd(AVDCreator.SEED_CLONE_EMAIL)
                if not success:
                    logger.error(f"Failed to delete seed clone AVD through avdmanager: {msg}", exc_info=True)
                    raise Exception(f"Failed to delete seed clone AVD: {msg}")
                elif "does not exist" in msg:
                    logger.info(f"Seed clone AVD did not exist, proceeding with recreation")

            # Clear any cached emulator data
            if recreate_user and avd_name:
                self.emulator_manager.emulator_launcher.running_emulators.pop(avd_name, None)
            if recreate_seed and seed_avd_name:
                self.emulator_manager.emulator_launcher.running_emulators.pop(seed_avd_name, None)

            # Remove the user from profiles index (only if recreating user AVD)
            if recreate_user and email in self.profiles_index:
                del self.profiles_index[email]
                self._save_profiles_index()
                logger.info(f"Removed {email} from profiles index")

            # Force the profile manager to reload
            self._load_profiles_index()

            logger.info(f"Successfully recreated {', '.join(actions)} for {email}")
            return True, f"Successfully recreated: {', '.join(actions)}"

        except Exception as e:
            logger.error(f"Error recreating profile AVD for {email}: {e}", exc_info=True)
            return False, f"Failed to recreate profile AVD: {str(e)}"

    def clear_emulator_settings(self, email: str) -> bool:
        """
        Clear all emulator settings for a user.

        This includes settings like:
        - appium_device_initialized
        - animations_disabled
        - hw_overlays_disabled
        - sleep_disabled
        - status_bar_disabled
        - auto_updates_disabled

        Args:
            email: Email address of the user

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Reload profiles to ensure we have the latest data
            self._load_profiles_index()

            # Check if user exists
            if email not in self.profiles_index:
                logger.warning(f"Cannot clear emulator settings: email {email} not found in profiles_index")
                return False

            # Clear the emulator_settings section if it exists
            if "emulator_settings" in self.profiles_index[email]:
                self.profiles_index[email]["emulator_settings"] = {}
                logger.info(f"Cleared all emulator settings for {email}")
            else:
                logger.info(f"No emulator settings to clear for {email}")

            # Save the updated profiles_index
            self._save_profiles_index()
            return True

        except Exception as e:
            logger.error(f"Error clearing emulator settings for {email}: {e}", exc_info=True)
            return False
