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
        # Removing current_profile_file as we're managing multiple users simultaneously
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
        # Removed current_profile loading as we're managing multiple users simultaneously
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
            logger.info(f"Profiles index not found at {self.index_file}, creating empty index")
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            # Save an empty profiles index
            empty_index = {}
            with open(self.index_file, "w") as f:
                json.dump(empty_index, f, indent=2)
            return empty_index

    def _save_profiles_index(self) -> None:
        """Save profiles index to JSON file."""
        try:
            with open(self.index_file, "w") as f:
                json.dump(self.profiles_index, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving profiles index: {e}")

    # Removed _load_current_profile method as we're managing multiple users simultaneously

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

    def _save_profile_status(self, email: str, avd_name: str, emulator_id: Optional[str] = None) -> None:
        """
        Save profile status to the user_preferences file.
        This replaces the previous _save_current_profile that used a separate file.

        Args:
            email: Email address of the profile
            avd_name: Name of the AVD
            emulator_id: Optional emulator device ID (e.g., 'emulator-5554')
        """
        # Make sure the email exists in user_preferences
        if email not in self.user_preferences:
            self.user_preferences[email] = {}

        # Update the user's status
        self.user_preferences[email]["last_used"] = int(time.time())
        self.user_preferences[email]["avd_name"] = avd_name

        # Add emulator ID if provided
        if emulator_id:
            self.user_preferences[email]["emulator_id"] = emulator_id

        # Save the updated preferences
        self._save_user_preferences()

        logger.debug(f"Saved profile status for {email} with AVD {avd_name}")

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
            profile_entry = self.profiles_index.get(email)

            # Handle different formats (backward compatibility)
            if isinstance(profile_entry, str):
                return profile_entry
            elif isinstance(profile_entry, dict) and "avd_name" in profile_entry:
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

        Args:
            email: Email address to lookup

        Returns:
            Optional[int]: The Appium port or None if not assigned
        """
        if email in self.profiles_index:
            profile_entry = self.profiles_index.get(email)

            # Handle different formats
            if isinstance(profile_entry, dict) and "appium_port" in profile_entry:
                return profile_entry["appium_port"]

        return None

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
            # Handle different profile entry formats
            if isinstance(profile_entry, str):
                avd_name = profile_entry
                appium_port = None
                vnc_instance = None
            elif isinstance(profile_entry, dict):
                avd_name = profile_entry.get("avd_name")
                appium_port = profile_entry.get("appium_port")
                vnc_instance = profile_entry.get("vnc_instance")
            else:
                logger.warning(f"Unknown profile entry format for {email}: {profile_entry}")
                continue

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
        This replaces the previous get_current_profile method that returned a single "current" profile.

        Args:
            email: The email address to get profile information for

        Returns:
            Optional[Dict]: Profile information or None if the profile doesn't exist
        """
        logger.info(f"[PROFILE DEBUG] get_profile_for_email called with email: {email}")
        
        if not email:
            logger.warning("[PROFILE DEBUG] get_profile_for_email called with empty email")
            return None

        # Check if the email exists in profiles_index
        if email not in self.profiles_index:
            logger.warning(f"[PROFILE DEBUG] Email {email} not found in profiles_index. Available keys: {list(self.profiles_index.keys())}")
            return None

        # Get the AVD name for this email
        profile_entry = self.profiles_index[email]
        logger.info(f"[PROFILE DEBUG] Found profile entry for {email}: {profile_entry}")
        
        if isinstance(profile_entry, dict) and "avd_name" in profile_entry:
            avd_name = profile_entry["avd_name"]
            logger.info(f"[PROFILE DEBUG] Found AVD name in dict format: {avd_name}")
        elif isinstance(profile_entry, str):
            avd_name = profile_entry
            logger.info(f"[PROFILE DEBUG] Found AVD name in string format: {avd_name}")
        else:
            logger.error(f"[PROFILE DEBUG] Could not determine AVD name from profile entry for {email}")
            return None

        # Look for a running emulator for this email
        logger.info(f"[PROFILE DEBUG] Looking for running emulator for email {email}")
        is_running, emulator_id, _ = self.find_running_emulator_for_email(email)
        logger.info(f"[PROFILE DEBUG] find_running_emulator_for_email result: running={is_running}, emulator_id={emulator_id}")

        # Build profile information
        profile = {
            "email": email,
            "avd_name": avd_name,
        }

        # Add emulator info if available
        if is_running and emulator_id:
            logger.info(f"[PROFILE DEBUG] Adding emulator_id {emulator_id} to profile for {email}")
            profile["emulator_id"] = emulator_id

            # Update stored emulator ID if different from what we have
            stored_emulator_id = None
            if email in self.user_preferences:
                stored_emulator_id = self.user_preferences[email].get("emulator_id")
                logger.info(f"[PROFILE DEBUG] Found stored emulator_id in preferences: {stored_emulator_id}")

            if stored_emulator_id != emulator_id:
                logger.info(f"[PROFILE DEBUG] Updating emulator ID for profile {email}: {emulator_id}")
                self._save_profile_status(email, avd_name, emulator_id)
        else:
            logger.warning(f"[PROFILE DEBUG] No running emulator found for {email}, profile will not have emulator_id")

        # Add any preferences if available
        if email in self.user_preferences:
            logger.info(f"[PROFILE DEBUG] Adding user preferences for {email}")
            for key, value in self.user_preferences[email].items():
                if key not in profile:
                    profile[key] = value

        logger.info(f"[PROFILE DEBUG] Returning profile for {email}: {profile}")
        return profile

    def get_current_profile(self) -> Optional[Dict]:
        """
        This method provides backward compatibility with the old single-user system.
        In the multi-user system, we'll attempt to find a running emulator and return
        its associated profile information.

        Returns:
            Optional[Dict]: Profile information for a running emulator or None if none found
        """
        logger.info("[PROFILE DEBUG] get_current_profile() called in multi-user system context")
        try:
            # Check for running emulators
            running_emulators = self.device_discovery.get_running_emulators()
            logger.info(f"[PROFILE DEBUG] Found running emulators: {running_emulators}")
            
            # If there are running emulators, try to find one in our profiles_index
            if running_emulators:
                # Log profiles_index for debugging
                logger.info(f"[PROFILE DEBUG] Current profiles_index keys: {list(self.profiles_index.keys())}")
                
                # First, try to find a profile that matches one of the running emulators
                for email, profile_entry in self.profiles_index.items():
                    # Extract AVD name from profile
                    avd_name = None
                    if isinstance(profile_entry, str):
                        avd_name = profile_entry
                    elif isinstance(profile_entry, dict) and "avd_name" in profile_entry:
                        avd_name = profile_entry["avd_name"]
                    
                    if avd_name and avd_name in running_emulators:
                        logger.info(f"[PROFILE DEBUG] Found matching profile for running emulator: {email} -> {avd_name}")
                        emulator_id = running_emulators[avd_name]
                        
                        # Build a profile object with the information we have
                        profile = {
                            "email": email,
                            "avd_name": avd_name,
                            "emulator_id": emulator_id
                        }
                        
                        # Add additional info from profiles_index if available
                        if isinstance(profile_entry, dict):
                            for key, value in profile_entry.items():
                                if key != "avd_name":  # Avoid duplicate
                                    profile[key] = value
                        
                        # Add user preferences if available
                        if email in self.user_preferences:
                            for key, value in self.user_preferences[email].items():
                                if key not in profile:  # Don't overwrite profile
                                    profile[key] = value
                        
                        logger.info(f"[PROFILE DEBUG] Returning profile for {email}: {profile}")
                        return profile
                
                # If we didn't find a matching profile, just return info about the first running emulator
                first_avd = list(running_emulators.keys())[0]
                logger.info(f"[PROFILE DEBUG] No profile matched running emulators. Using first running emulator: {first_avd}")
                
                # Try to extract email from AVD name if possible
                email = self._extract_email_from_avd_name(first_avd)
                if not email:
                    # If extraction fails, use a placeholder
                    email = f"unknown_user_for_{first_avd}"
                
                profile = {
                    "email": email,
                    "avd_name": first_avd,
                    "emulator_id": running_emulators[first_avd]
                }
                logger.info(f"[PROFILE DEBUG] Returning synthesized profile: {profile}")
                return profile
            
            # Even if we don't find matching emulators, check if we have a device_id in any profile
            # This helps in cases where the device ID comes from elsewhere but isn't properly tracked in our emulator list
            logger.info("[PROFILE DEBUG] No matching running emulators found in our tracking")
            
            # Check ADB directly for any connected emulators as a last resort
            try:
                result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                
                if result.returncode == 0:
                    logger.info(f"[PROFILE DEBUG] ADB devices output: {result.stdout}")
                    lines = result.stdout.strip().split("\n")
                    
                    for line in lines[1:]:  # Skip header
                        if not line.strip():
                            continue
                            
                        parts = line.split("\t")
                        if len(parts) >= 2 and "emulator" in parts[0] and parts[1].strip() == "device":
                            emulator_id = parts[0].strip()
                            logger.info(f"[PROFILE DEBUG] Found connected emulator: {emulator_id}")
                            
                            # Use any profile with this emulator ID if available
                            for email, prefs in self.user_preferences.items():
                                if prefs.get("emulator_id") == emulator_id:
                                    avd_name = prefs.get("avd_name")
                                    if avd_name:
                                        logger.info(f"[PROFILE DEBUG] Found matching profile for {emulator_id}: {email}")
                                        profile = {
                                            "email": email,
                                            "avd_name": avd_name,
                                            "emulator_id": emulator_id
                                        }
                                        logger.info(f"[PROFILE DEBUG] Returning profile from user preferences: {profile}")
                                        return profile
                            
                            # If no matching profile found but we have a device, create a synthetic profile
                            if self.profiles_index:
                                # Use the first profile we have and associate it with this device
                                first_email = next(iter(self.profiles_index.keys()))
                                profile_entry = self.profiles_index[first_email]
                                
                                if isinstance(profile_entry, dict) and "avd_name" in profile_entry:
                                    avd_name = profile_entry["avd_name"]
                                elif isinstance(profile_entry, str):
                                    avd_name = profile_entry
                                else:
                                    avd_name = f"DefaultAVD_{first_email}"
                                    
                                logger.info(f"[PROFILE DEBUG] Creating synthetic profile for {first_email} with {emulator_id}")
                                profile = {
                                    "email": first_email,
                                    "avd_name": avd_name,
                                    "emulator_id": emulator_id
                                }
                                
                                # Save this mapping for future use
                                self._save_profile_status(first_email, avd_name, emulator_id)
                                logger.info(f"[PROFILE DEBUG] Returning synthetic profile: {profile}")
                                return profile
                            
                            # If we have an emulator but no profiles at all, create a generic one
                            logger.info(f"[PROFILE DEBUG] Creating generic profile for emulator {emulator_id}")
                            profile = {
                                "email": "default_user",
                                "avd_name": "Default_AVD",
                                "emulator_id": emulator_id
                            }
                            logger.info(f"[PROFILE DEBUG] Returning generic profile: {profile}")
                            return profile
            except Exception as e:
                logger.error(f"[PROFILE DEBUG] Error checking for connected emulators: {e}")
                
            logger.warning("[PROFILE DEBUG] No running emulators or profiles found, returning None")
            return None
        except Exception as e:
            logger.error(f"[PROFILE DEBUG] Error in get_current_profile: {e}")
            return None

    def register_profile(
        self, email: str, avd_name: str, vnc_instance: int = None, appium_port: int = None
    ) -> None:
        """
        Register a profile by associating an email with an AVD name.

        Args:
            email: The email address to register
            avd_name: The AVD name to associate with this email
            vnc_instance: Optional VNC instance number to assign to this profile
            appium_port: Optional Appium port to assign to this profile
        """
        logger.info(f"[PROFILE DEBUG] Starting register_profile for email: {email}, avd: {avd_name}")
        logger.info(f"[PROFILE DEBUG] Current profiles_index keys: {list(self.profiles_index.keys())}")
        
        # Debug check if the email already exists before we add it
        if email in self.profiles_index:
            logger.info(f"[PROFILE DEBUG] Email {email} already exists in profiles_index: {self.profiles_index[email]}")
            
            if isinstance(self.profiles_index[email], str):
                # Convert old format to new format
                old_avd = self.profiles_index[email]
                logger.info(f"[PROFILE DEBUG] Converting old format '{old_avd}' to new format for {email}")
                self.profiles_index[email] = {"avd_name": old_avd}
        else:
            logger.info(f"[PROFILE DEBUG] Adding new entry for {email} in profiles_index")
            self.profiles_index[email] = {}

        # Update with new values
        logger.info(f"[PROFILE DEBUG] Setting AVD name to {avd_name} for {email}")
        self.profiles_index[email]["avd_name"] = avd_name

        # Add VNC instance if provided
        if vnc_instance is not None:
            logger.info(f"[PROFILE DEBUG] Setting VNC instance to {vnc_instance} for {email}")
            self.profiles_index[email]["vnc_instance"] = vnc_instance

        # Add Appium port if provided
        if appium_port is not None:
            logger.info(f"[PROFILE DEBUG] Setting Appium port to {appium_port} for {email}")
            self.profiles_index[email]["appium_port"] = appium_port

        # Save to file
        logger.info(f"[PROFILE DEBUG] Saving profiles_index to {self.index_file}")
        try:
            self._save_profiles_index()
            logger.info(f"[PROFILE DEBUG] Successfully saved profiles_index, verifying entry")
            
            # Verify the entry was saved
            if email in self.profiles_index:
                logger.info(f"[PROFILE DEBUG] Verified {email} is in memory copy of profiles_index")
            else:
                logger.error(f"[PROFILE DEBUG] {email} is NOT in memory copy of profiles_index!")
                
            # Verify the file was updated
            if os.path.exists(self.index_file):
                try:
                    with open(self.index_file, "r") as f:
                        file_data = json.load(f)
                    if email in file_data:
                        logger.info(f"[PROFILE DEBUG] Verified {email} is in saved profiles_index file")
                    else:
                        logger.error(f"[PROFILE DEBUG] {email} is NOT in saved profiles_index file!")
                except Exception as verify_e:
                    logger.error(f"[PROFILE DEBUG] Error verifying file contents: {verify_e}")
            else:
                logger.error(f"[PROFILE DEBUG] Index file does not exist at {self.index_file}!")
        except Exception as save_e:
            logger.error(f"[PROFILE DEBUG] Error saving profiles_index: {save_e}")
            
        # Build and log the registration message
        log_message = f"Registered profile for {email} with AVD {avd_name}"
        if vnc_instance is not None:
            log_message += f" on VNC instance {vnc_instance}"
        if appium_port is not None:
            log_message += f" with Appium port {appium_port}"
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
            logger.info(f"Email {email} already registered to AVD {self.profiles_index[email]}")
            return

        # Create a standardized AVD name for this email first
        normalized_avd_name = self.get_avd_name_from_email(email)
        logger.info(f"Generated standardized AVD name {normalized_avd_name} for {email}")

        # Next, try to find any running emulator to use
        running_emulators = self.device_discovery.map_running_emulators()

        if running_emulators:
            # Use the first available running emulator
            avd_name, emulator_id = next(iter(running_emulators.items()))
            logger.info(f"Registering email {email} to running emulator with AVD {avd_name}")
            # Use proper registration method instead of direct dict assignment to ensure correct format
            self.register_profile(email, avd_name)

            # Update profile status
            self._save_profile_status(email, avd_name, emulator_id)
            return

        # If no running emulator, check for available AVDs
        try:
            # List available AVDs
            avd_list_cmd = [f"{self.android_home}/emulator/emulator", "-list-avds"]
            result = subprocess.run(avd_list_cmd, check=False, capture_output=True, text=True, timeout=5)
            available_avds = result.stdout.strip().split("\n")
            available_avds = [avd for avd in available_avds if avd.strip()]

            if available_avds:
                # Use the first available AVD
                avd_name = available_avds[0]
                logger.info(f"Registering email {email} to available AVD {avd_name}")
                # Use proper registration method instead of direct dict assignment to ensure correct format
                self.register_profile(email, avd_name)

                # Update profile status without emulator ID
                self._save_profile_status(email, avd_name)
                return
        except Exception as e:
            logger.warning(f"Error listing available AVDs: {e}")

        # Register with our standardized AVD name as fallback
        logger.info(f"Registering email {email} to standardized AVD {normalized_avd_name}")
        # Use proper registration method instead of direct dict assignment to ensure correct format
        self.register_profile(email, normalized_avd_name)

        # Update profile status without emulator ID
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

    def is_styles_updated(self, email: str = None) -> bool:
        """
        Check if styles have been updated for a profile.

        Args:
            email: The email address of the profile to check. If None, returns False.

        Returns:
            bool: True if styles have been updated, False otherwise
        """
        if not email:
            return False

        if email in self.user_preferences and "styles_updated" in self.user_preferences[email]:
            return self.user_preferences[email]["styles_updated"]

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

            # Update user preferences to ensure persistence
            if email not in self.user_preferences:
                self.user_preferences[email] = {}
            self.user_preferences[email]["styles_updated"] = is_updated

            # Save changes
            self._save_user_preferences()

            logger.info(f"Successfully updated style preference for {email} to {is_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating style preference: {e}")
            return False

    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
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

                    # Update profile status
                    self._save_profile_status(email, avd_name, emulator_id)

                    return True, f"Using existing emulator {emulator_id} for {email}"
                else:
                    logger.warning("Emulator appears to be running but couldn't identify it")

            # If no emulator is running or we couldn't identify it, try to find AVD
            avd_name = self.get_avd_for_email(email)

            if not avd_name:
                # Create a standardized AVD name for this email first
                normalized_avd_name = self.get_avd_name_from_email(email)
                logger.info(f"Generated standardized AVD name {normalized_avd_name} for {email}")

                # Register this standardized name first to ensure it's in the profiles_index
                self.register_profile(email, normalized_avd_name)

                # Now look for any available AVD as a fallback
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

                        # Update the profile with this AVD
                        self.register_profile(email, avd_name)
                    else:
                        logger.warning(f"No AVDs found. Using standardized AVD name.")
                        # Use the standardized name we registered
                        avd_name = normalized_avd_name
                except Exception as e:
                    logger.warning(f"Error listing available AVDs: {e}")
                    # Use the standardized name we registered
                    avd_name = normalized_avd_name

            # Update profile status without trying to start emulator
            self._save_profile_status(email, avd_name)

            logger.info(f"In simplified mode, tracking profile for {email} without managing emulator")
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
            # Update the AVD name if it's different from what we expected
            if found_avd_name != avd_name and found_avd_name is not None:
                logger.info(f"Updating AVD name for profile {email}: {avd_name} -> {found_avd_name}")
                avd_name = found_avd_name
                self.register_profile(email, avd_name)

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
        if self.start_emulator(avd_name):
            # We need to get the emulator ID for the started emulator
            started_emulator_id = self.get_emulator_id_for_avd(avd_name)
            self._save_profile_status(email, avd_name, started_emulator_id)
            logger.info(f"Successfully started emulator for profile {email}")
            return True, f"Switched to profile {email} with new emulator"
        else:
            # Failed to start emulator, but still update the profile status for tracking
            self._save_profile_status(email, avd_name)
            logger.error(f"Failed to start emulator for profile {email}, but updated profile tracking")
            return False, f"Failed to start emulator for profile {email}"
