import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from views.core.avd_creator import AVDCreator
from views.core.device_discovery import DeviceDiscovery
from views.core.emulator_manager import EmulatorManager

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

        # Initialize component managers
        self.device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
        self.emulator_manager = EmulatorManager(
            self.android_home, self.avd_dir, self.host_arch, self.use_simplified_mode
        )
        self.avd_creator = AVDCreator(self.android_home, self.avd_dir, self.host_arch)

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
        return self.avd_creator.normalize_email_for_avd(email)

    def get_avd_name_from_email(self, email: str) -> str:
        """
        Generate a standardized AVD name from an email address.

        Args:
            email: Email address

        Returns:
            str: Complete AVD name
        """
        return self.avd_creator.get_avd_name_from_email(email)

    def extract_email_from_avd_name(self, avd_name: str) -> Optional[str]:
        """
        Try to extract an email from an AVD name.
        This is an approximate reverse of get_avd_name_from_email.

        Args:
            avd_name: The AVD name to parse

        Returns:
            Optional[str]: Extracted email or None if pattern doesn't match
        """
        return self.device_discovery.extract_email_from_avd_name(avd_name)

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

    def _load_user_preferences(self) -> Dict[str, Dict]:
        """Load user preferences from JSON file or create if it doesn't exist."""
        if os.path.exists(self.preferences_file):
            try:
                with open(self.preferences_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading user preferences: {e}")
                return {}
        else:
            return {}

    def _save_user_preferences(self) -> None:
        """Save user preferences to JSON file."""
        try:
            with open(self.preferences_file, "w") as f:
                json.dump(self.user_preferences, f, indent=2)
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
        running_emulators = self.device_discovery.map_running_emulators()
        return running_emulators.get(avd_name)

    def is_emulator_running(self) -> bool:
        """Check if an emulator is currently running."""
        return self.emulator_manager.is_emulator_running()

    def is_emulator_ready(self) -> bool:
        """Check if an emulator is running and fully booted."""
        return self.emulator_manager.is_emulator_ready()

    def scan_for_avds_with_emails(self) -> Dict[str, str]:
        """
        Scan all running AVDs to find ones with email patterns in their names.
        This helps to discover and register email-to-AVD mappings automatically.

        Returns:
            Dict[str, str]: Dictionary mapping emails to AVD names
        """
        return self.device_discovery.scan_for_avds_with_emails(self.profiles_index)

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
        running_emulators = self.device_discovery.map_running_emulators()

        result = []
        for email, avd_name in self.profiles_index.items():
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")

            # Get emulator ID if the AVD is running
            emulator_id = running_emulators.get(avd_name)

            # If we didn't find it, check if any running emulator has email in its name
            if not emulator_id:
                is_running, found_emulator_id, _ = self.find_running_emulator_for_email(email)
                if is_running:
                    emulator_id = found_emulator_id

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

    def register_profile(self, email: str, avd_name: str) -> None:
        """Register a profile by associating an email with an AVD name."""
        self.profiles_index[email] = avd_name
        self._save_profiles_index()
        logger.info(f"Registered profile for {email} with AVD {avd_name}")

    def stop_emulator(self) -> bool:
        """Stop the currently running emulator."""
        return self.emulator_manager.stop_emulator()

    def start_emulator(self, avd_name: str) -> bool:
        """
        Start the specified AVD.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        return self.emulator_manager.start_emulator(avd_name)

    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """
        Create a new AVD for the given email.

        Returns:
            Tuple[bool, str]: (success, avd_name)
        """
        return self.avd_creator.create_new_avd(email)

    def is_styles_updated(self) -> bool:
        """
        Check if styles have been updated for the current profile.

        Returns:
            bool: True if styles have been updated, False otherwise
        """
        if self.current_profile and "styles_updated" in self.current_profile:
            return self.current_profile["styles_updated"]
        return False
        
    def update_style_preference(self, is_updated: bool) -> bool:
        """
        Update the styles_updated preference for the current profile.
        
        Args:
            is_updated: Boolean indicating whether styles have been updated
            
        Returns:
            bool: True if the update was successful, False otherwise
        """
        try:
            if not self.current_profile:
                logger.warning("No current profile to update style preference for")
                return False
                
            email = self.current_profile.get("email")
            if not email:
                logger.warning("Current profile has no email to update style preference for")
                return False
                
            # Update the current profile
            self.current_profile["styles_updated"] = is_updated
            
            # Also update user preferences to ensure persistence
            if email not in self.user_preferences:
                self.user_preferences[email] = {}
            self.user_preferences[email]["styles_updated"] = is_updated
            
            # Save changes to both files
            self._save_current_profile(
                email, 
                self.current_profile.get("avd_name", ""), 
                self.current_profile.get("emulator_id")
            )
            self._save_user_preferences()
            
            logger.info(f"Successfully updated style preference for {email} to {is_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating style preference: {e}")
            return False

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
                running_emulators = self.device_discovery.map_running_emulators()

                if running_emulators:
                    # First check if there's an emulator with this email in the AVD name
                    is_running, emulator_id, found_avd = self.find_running_emulator_for_email(email)
                    if is_running and emulator_id:
                        # Find the AVD name for this emulator
                        avd_name = found_avd
                        for avd, emu_id in running_emulators.items():
                            if emu_id == emulator_id:
                                avd_name = avd
                                break
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

        # If force_new_emulator is True, we would normally stop any running emulator
        # But in simplified mode (Mac development), we always preserve emulators
        if force_new_emulator:
            if self.use_simplified_mode:
                logger.info("Force new emulator requested, but preserving emulator in simplified mode")
            else:
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
        running_avds = self.device_discovery.map_running_emulators()

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
            running_avds = self.device_discovery.map_running_emulators()
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
                return False, f"Failed to create AVD for {email}: {result}"
            # Update avd_name with newly created AVD
            avd_name = result
            self.register_profile(email, avd_name)
            logger.info(f"Created new AVD {avd_name} for {email}")

        # Start the emulator
        logger.info(f"Starting emulator for profile {email} (AVD: {avd_name})")
        if self.start_emulator(avd_name):
            # We need to get the emulator ID for the started emulator
            started_emulator_id = self.get_emulator_id_for_avd(avd_name)
            self._save_current_profile(email, avd_name, started_emulator_id)
            logger.info(f"Successfully started emulator for profile {email}")
            return True, f"Switched to profile {email} with new emulator"
        else:
            # Failed to start emulator, but still update the current profile for tracking
            self._save_current_profile(email, avd_name)
            logger.error(f"Failed to start emulator for profile {email}, but updated current profile")
            return False, f"Failed to start emulator for profile {email}"
