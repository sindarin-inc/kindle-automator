import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from server.utils.request_utils import get_sindarin_email
from views.core.avd_creator import AVDCreator
from views.core.device_discovery import DeviceDiscovery
from views.core.emulator_manager import EmulatorManager

logger = logging.getLogger(__name__)


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
        # No longer need a separate "profiles" subdirectory
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
        self.device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
        self.emulator_manager = EmulatorManager(
            self.android_home, self.avd_dir, self.host_arch, self.use_simplified_mode
        )
        self.avd_creator = AVDCreator(self.android_home, self.avd_dir, self.host_arch)

        # Load profile index if it exists, otherwise create empty one
        self.profiles_index = self._load_profiles_index()

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
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading profiles index: {e}")
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
            logger.error(f"Error saving profiles index: {e}")

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

            logger.debug("Saved user preferences by updating profiles_index and refreshed preferences cache")
        except Exception as e:
            logger.error(f"Error saving user preferences: {e}")

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
            logger.info(f"Updated {section + '.' if section else ''}field {field} for {email}")
            return True
        except Exception as e:
            logger.error(f"Error setting user field {field} for {email}: {e}")
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
            logger.error(f"Error getting user field {field} for {email}: {e}")
            return default

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
                # Fallback to storing in profile data for backward compatibility
                self.profiles_index[email]["emulator_id"] = emulator_id

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
        # Look for running emulators with this AVD name
        running_emulators = self.device_discovery.map_running_emulators()
        emulator_id = running_emulators.get(avd_name)
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
            logger.error(f"Error updating AVD name for {email}: {e}")
            return False

    def list_profiles(self) -> List[Dict]:
        """
        List all available profiles with their details.

        Returns:
            List[Dict]: List of profile information dictionaries
        """
        # First get running emulators
        running_emulators = self.device_discovery.map_running_emulators()

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
            logger.error(f"Could not determine AVD name from profile entry for {email}")
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
        try:
            # Check for running emulators
            running_emulators = self.device_discovery.map_running_emulators()
            logger.info(f"[DIAG] Running emulators map: {running_emulators}")
            sindarin_email = get_sindarin_email()
            logger.info(f"[DIAG] Sindarin email: {sindarin_email}")

            # Special case for macOS development environment
            is_mac_dev = os.getenv("ENVIRONMENT", "DEV").lower() == "dev" and platform.system() == "Darwin"

            # If there are running emulators or we're in macOS dev mode, try to find the profile
            if running_emulators or is_mac_dev:
                # First, try to find a profile that matches one of the running emulators
                logger.info(f"[DIAG] Profiles index contains: {list(self.profiles_index.keys())}")
                for email, profile in self.profiles_index.items():
                    logger.info(f"[DIAG] Checking email {email} against sindarin_email {sindarin_email}")
                    if email != sindarin_email:
                        continue
                    logger.info(f"[DIAG] Found matching profile for {email}: {profile}")

                    # Add user preferences if available
                    if email in self.user_preferences:
                        for key, value in self.user_preferences[email].items():
                            if key not in profile:  # Don't overwrite profile
                                profile[key] = value

                    return profile

            logger.warning("No running emulators or profiles found")
            return None
        except Exception as e:
            logger.error(f"Error in get_current_profile: {e}")
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
            logger.error(f"Error saving profiles_index: {save_e}")

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
        running_emulators = self.device_discovery.map_running_emulators()
        if normalized_avd_name in running_emulators:
            emulator_id = running_emulators[normalized_avd_name]
            logger.info(f"Found user's AVD {normalized_avd_name} already running at {emulator_id}")
            self._save_profile_status(email, normalized_avd_name, emulator_id)
        else:
            self._save_profile_status(email, normalized_avd_name)

    def stop_emulator(self, device_id: str = None) -> bool:
        """
        Stop an emulator by device ID or the currently running emulator.

        Args:
            device_id: Optional device ID to stop a specific emulator.
                       If None, stops whatever emulator is running.

        Returns:
            bool: True if successful, False otherwise
        """
        if device_id:
            return self.emulator_manager.stop_specific_emulator(device_id)
        else:
            return self.emulator_manager.stop_emulator()

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
            logger.error(f"Error getting style setting {setting_name}: {e}")
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
            logger.error(f"Error saving style setting {setting_name}: {e}")
            return False

    def get_last_snapshot(self, email: str) -> Optional[str]:
        """
        Get the last snapshot name saved for a user.

        Args:
            email: The email address of the user

        Returns:
            Optional[str]: The snapshot name or None if not found
        """
        return self.get_user_field(email, "last_snapshot")

    def clear_last_snapshot(self, email: str) -> bool:
        """
        Clear the last snapshot name for a user.

        Args:
            email: The email address of the user

        Returns:
            bool: True if successful, False otherwise
        """
        return self.set_user_field(email, "last_snapshot", None)

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
            logger.error(f"Error updating style preference: {e}")
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
        if force_new_emulator and email in self.user_preferences:
            # Reset all device-specific settings for this profile
            settings_to_reset = ["hw_overlays_disabled", "animations_disabled", "sleep_disabled"]
            for setting in settings_to_reset:
                if setting in self.user_preferences[email]:
                    self.user_preferences[email][setting] = False
                    logger.info(f"Reset {setting} for {email} due to emulator recreation")

            # Save the updated preferences
            self._save_user_preferences()

            # No need to update current profile anymore, as we're using the multi-user approach
            # The user_preferences save above is sufficient

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

            # Try to create the AVD - even if this fails, we'll have the profile registered
            success, result = self.create_new_avd(email)
            if not success:
                logger.warning(f"Failed to create AVD: {result}, but profile was registered")
                # Set AVD name to the one we registered to continue
                avd_name = normalized_avd_name
            else:
                avd_name = result
                # Update the profile with the final AVD name if different
                if avd_name != normalized_avd_name:
                    self.register_profile(email, avd_name)

        # Check if this AVD actually exists - it might not if we're using
        # manually registered AVDs but the Android Studio AVD was renamed or deleted
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)

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
                logger.error(f"Failed to stop emulator {emulator_id} for profile {email}")
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
            # Try to create the AVD
            success, result = self.create_new_avd(email)
            if not success:
                logger.error(f"Failed to create AVD: {result}")
                return False, f"Failed to create AVD for {email}: {result}"
            # Update avd_name with newly created AVD
            avd_name = result
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
            logger.error(f"Failed to start emulator for profile {email}, but updated profile tracking")
            return False, f"Failed to start emulator for profile {email}"
