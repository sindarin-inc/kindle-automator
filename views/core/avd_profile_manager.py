"""
AVD Profile Manager with PostgreSQL database backend.

This is a refactored version of AVDProfileManager that uses PostgreSQL
instead of JSON files for data persistence. It maintains the same API
but with atomic database operations and better concurrency support.
"""

import logging
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from database.connection import DatabaseConnection
from database.repositories.user_repository import UserRepository
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

    This version uses PostgreSQL for data persistence instead of JSON files.
    """

    @classmethod
    def get_instance(cls, base_dir: str = "/opt/android-sdk") -> "AVDProfileManager":
        """Get the singleton instance of AVDProfileManager."""
        global _instance
        if _instance is None:
            _instance = cls(base_dir)
        return _instance

    def __init__(self, base_dir: str = "/opt/android-sdk"):
        # Check if this is being called directly or through get_instance()
        global _instance
        if _instance is not None and _instance is not self:
            logger.warning("AVDProfileManager initialized directly. Use get_instance() instead.")

        # Initialize database connection
        try:
            self.db_connection = DatabaseConnection()
            self.db_connection.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")
            raise

        # Detect host architecture and operating system first
        self.host_arch = self._detect_host_architecture()
        self.is_macos = platform.system() == "Darwin"
        self.is_dev_mode = os.environ.get("FLASK_ENV") == "development"

        # Get Android home from environment or fallback to default
        self.android_home = os.environ.get("ANDROID_HOME", base_dir)

        # Use a different base directory for Mac development environments
        if self.is_macos:
            # Use project's user_data directory instead of Android SDK directory
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            base_dir = os.path.join(project_root, "user_data")
            logger.info("Mac development environment detected")
            logger.info(f"Using {base_dir} for profile storage")

            # Profiles now stored in project's user_data directory

            # In macOS, the AVD directory is typically in the .android folder
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
        if self.is_macos:
            self.profiles_dir = base_dir
            # Keep users_file for backward compatibility but it won't be used
            self.users_file = os.path.join(self.profiles_dir, "users.json")
        else:
            # For non-Mac environments, keep the old directory structure
            self.profiles_dir = os.path.join(base_dir, "profiles")
            self.users_file = os.path.join(self.profiles_dir, "users.json")

        # Ensure directories exist
        os.makedirs(self.profiles_dir, exist_ok=True)
        # Initialize component managers
        self.device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
        self.emulator_manager = EmulatorManager(self.android_home, self.avd_dir, self.host_arch)
        self.avd_creator = AVDCreator(self.android_home, self.avd_dir, self.host_arch)

        # VNC related settings
        self.vnc_base_port = 6500
        self.max_vnc_instances = 25

        # Track restarting AVDs
        self.restarting_avds = set()

        # Initialize profiles_index property for compatibility
        self._profiles_index_cache = None
        self._profiles_index_cache_time = 0

        logger.info(f"AVDProfileManager initialized with base_dir: {base_dir}")
        logger.info(f"AVD directory: {self.avd_dir}")
        logger.info(f"Host architecture: {self.host_arch}")

    def _detect_host_architecture(self) -> str:
        """Detect the host system architecture."""
        machine = platform.machine().lower()

        if machine in ["x86_64", "amd64"]:
            return "x86_64"
        elif machine in ["aarch64", "arm64"]:
            return "arm64"
        elif machine in ["armv7l", "armv7"]:
            return "arm"
        elif machine in ["i386", "i686"]:
            return "x86"
        else:
            logger.warning(f"Unknown architecture: {machine}, defaulting to x86_64")
            return "x86_64"

    def get_user_field(self, email: str, field: str, default=None, section: Optional[str] = None):
        """
        Get a specific field value for a user.

        Args:
            email: User's email
            field: Field name to retrieve
            default: Default value if field doesn't exist
            section: Optional section name for nested fields

        Returns:
            Field value or default
        """
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(email)

            if not user:
                return default

            # Handle section-based fields
            if section:
                field_path = f"{section}.{field}"
            else:
                field_path = field

            # Parse the field path and get the value
            parts = field_path.split(".")
            obj = user

            try:
                for part in parts:
                    if hasattr(obj, part):
                        obj = getattr(obj, part)
                    elif isinstance(obj, list):
                        # Handle preferences list
                        for pref in obj:
                            if hasattr(pref, "preference_key") and pref.preference_key == part:
                                return pref.preference_value
                        return default
                    else:
                        return default

                return obj if obj is not None else default
            except AttributeError:
                return default

    def set_user_field(self, email: str, field: str, value, section: Optional[str] = None):
        """
        Set a specific field value for a user.

        Args:
            email: User's email
            field: Field name to set
            value: Value to set
            section: Optional section name for nested fields
        """
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)

            # Ensure user exists
            user = repo.get_user_by_email(email)
            if not user:
                logger.warning(f"User {email} not found, creating new user")
                repo.create_user(email)

            # Update the field
            if section:
                field_path = f"{section}.{field}"
            else:
                field_path = field

            repo.update_user_field(email, field_path, value)

    def get_profile_for_email(self, email: str) -> Optional[Dict]:
        """
        Get the complete profile data for an email.

        Returns:
            Profile dictionary in the same format as the old JSON structure
        """
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(email)

            if not user:
                return None

            return repo.user_to_dict(user)

    def get_avd_for_email(self, email: str) -> Optional[str]:
        """Get the AVD name associated with an email."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(email)
            return user.avd_name if user else None

    def update_avd_name_for_email(self, email: str, avd_name: str) -> bool:
        """Update the AVD name for a given email."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            return repo.update_user_field(email, "avd_name", avd_name)

    def register_profile(
        self, email: str, avd_name: str, vnc_instance: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Register a new profile or update existing one.

        Returns:
            Tuple of (success, message)
        """
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)

            try:
                # Create or update user
                user, created = repo.get_or_create_user(email, avd_name)

                if created:
                    message = f"Registered new profile for {email} with AVD {avd_name}"
                else:
                    # Update AVD name if different
                    if user.avd_name != avd_name:
                        repo.update_user_field(email, "avd_name", avd_name)
                        message = f"Updated AVD name for {email} to {avd_name}"
                    else:
                        message = f"Profile already exists for {email}"

                logger.info(message)
                return True, message

            except Exception as e:
                logger.error(f"Error registering profile: {e}")
                return False, str(e)

    def update_auth_state(self, email: str, authenticated: bool) -> bool:
        """Update authentication state for a user."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            return repo.update_auth_state(email, authenticated)

    def _save_profile_status(self, email: str, avd_name: str, emulator_id: Optional[str] = None) -> bool:
        """Save profile status with last_used timestamp."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            return repo.update_last_used(email, emulator_id)

    def update_style_preference(self, is_updated: bool, email: Optional[str] = None) -> Dict:
        """Update style preference for a user."""
        if not email:
            email = get_sindarin_email()

        if not email:
            return {"error": "No email found"}

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            success = repo.update_user_field(email, "styles_updated", is_updated)

            return {"success": success, "email": email, "styles_updated": is_updated}

    def save_style_setting(self, setting_name: str, setting_value, email: Optional[str] = None) -> Dict:
        """Save a library style setting for a user."""
        if not email:
            email = get_sindarin_email()

        if not email:
            return {"error": "No email found"}

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)

            # Ensure user exists
            user = repo.get_user_by_email(email)
            if not user:
                repo.create_user(email)

            # Update the library setting
            success = repo.update_user_field(email, f"library_settings.{setting_name}", setting_value)

            return {"success": success, "email": email, setting_name: setting_value}

    def save_reading_setting(self, setting_name: str, setting_value, email: Optional[str] = None) -> Dict:
        """Save a reading style setting for a user."""
        if not email:
            email = get_sindarin_email()

        if not email:
            return {"error": "No email found"}

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)

            # Ensure user exists
            user = repo.get_user_by_email(email)
            if not user:
                repo.create_user(email)

            # Update the reading setting
            success = repo.update_user_field(email, f"reading_settings.{setting_name}", setting_value)

            return {"success": success, "email": email, setting_name: setting_value}

    def get_all_profiles(self) -> Dict[str, Dict]:
        """Get all user profiles as a dictionary."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_all_users()

            return {user.email: repo.user_to_dict(user) for user in users}

    def get_recently_used_profiles(self, limit: int = 10) -> List[Dict]:
        """Get recently used profiles ordered by last_used."""
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_recently_used_users(limit)

            return [repo.user_to_dict(user) for user in users]

    @property
    def profiles_index(self) -> Dict[str, Dict]:
        """Property for backward compatibility with code expecting profiles_index."""
        # Cache for 5 seconds to avoid too many DB calls
        import time

        current_time = time.time()
        if self._profiles_index_cache is None or current_time - self._profiles_index_cache_time > 5:
            self._profiles_index_cache = self.get_all_profiles()
            self._profiles_index_cache_time = current_time
        return self._profiles_index_cache

    def list_profiles(self) -> Dict[str, Dict]:
        """List all profiles (alias for profiles_index)."""
        return self.profiles_index

    def get_profiles_with_restart_flag(self) -> List[str]:
        """Get list of emails for profiles with was_running_at_restart flag set."""
        from database.repositories.user_repository import UserRepository

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_users_with_restart_flag()
            return [user.email for user in users]

    def clear_all_restart_flags(self) -> int:
        """Clear all was_running_at_restart flags and return count cleared."""
        from database.repositories.user_repository import UserRepository

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            return repo.clear_restart_flags()

    def get_email_by_emulator_id(self, emulator_id: str) -> Optional[str]:
        """Get email for a given emulator_id."""
        from database.repositories.user_repository import UserRepository

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_emulator_id(emulator_id)
            return user.email if user else None

    def get_inactive_profiles(self, cutoff_datetime: datetime) -> List[Dict]:
        """Get profiles that haven't been used since cutoff date and aren't in cold storage."""
        from database.repositories.user_repository import UserRepository

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_inactive_users(cutoff_datetime)
            return [repo.user_to_dict(user) for user in users]

    def get_profiles_by_avd_names(self, avd_names: List[str]) -> Dict[str, Dict]:
        """Get profiles that have one of the specified AVD names."""
        from database.repositories.user_repository import UserRepository

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_users_with_avd_names(avd_names)
            return {user.email: repo.user_to_dict(user) for user in users}

    def get_emulator_id_for_avd(self, avd_name: str) -> Optional[str]:
        """
        Get the emulator device ID for a given AVD name.

        Args:
            avd_name: Name of the AVD to find

        Returns:
            Optional[str]: The emulator ID if found, None otherwise
        """
        # Use device_discovery to map running emulators
        running_emulators = self.device_discovery.map_running_emulators(self.get_all_profiles())

        # Check if the AVD is in the running emulators
        if avd_name in running_emulators:
            return running_emulators[avd_name]

        # Also check VNC instance manager for any stored emulator IDs
        for email, profile in self.get_all_profiles().items():
            if profile.get("avd_name") == avd_name:
                try:
                    from server.utils.vnc_instance_manager import VNCInstanceManager

                    vnc_manager = VNCInstanceManager.get_instance()
                    emulator_id = vnc_manager.get_emulator_id(email)
                    if emulator_id:
                        return emulator_id
                except Exception as e:
                    logger.warning(f"Error checking VNC instance for emulator ID: {e}")

        return None

    def get_current_profile(self) -> Optional[Dict]:
        """
        Get the current profile based on the request context email.

        Returns:
            Optional[Dict]: Profile information for the current user or None
        """
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return None

        return self.get_profile_for_email(sindarin_email)

    def cleanup_stale_profiles(self, days_threshold: int = 30) -> int:
        """
        Clean up profiles that haven't been used in the specified number of days.

        Returns:
            Number of profiles cleaned up
        """
        # This would need to be implemented based on business requirements
        # For now, just log a warning
        logger.warning("cleanup_stale_profiles not fully implemented for database version")
        return 0

    def mark_avd_restarting(self, avd_name: str):
        """Mark an AVD as currently restarting."""
        self.restarting_avds.add(avd_name)

    def unmark_avd_restarting(self, avd_name: str):
        """Unmark an AVD as restarting."""
        self.restarting_avds.discard(avd_name)

    def is_avd_restarting(self, avd_name: str) -> bool:
        """Check if an AVD is currently restarting."""
        return avd_name in self.restarting_avds

    def get_avd_name_from_email(self, email: str) -> str:
        """Generate a standardized AVD name from an email address."""
        return self.avd_creator.get_avd_name_from_email(email)

    def find_running_emulator_for_email(self, email: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Find a running emulator that's associated with a specific email."""
        return self.device_discovery.find_running_emulator_for_email(email, self.get_all_profiles())

    def register_email_to_avd(self, email: str, default_avd_name: str = "Pixel_API_30") -> None:
        """Register an email to an AVD for development purposes."""
        # Check if we already have a mapping
        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            if repo.get_user_by_email(email):
                return

        # Create a standardized AVD name for this email
        normalized_avd_name = self.get_avd_name_from_email(email)
        logger.info(f"Generated standardized AVD name {normalized_avd_name} for {email}")

        # Register the profile
        self.register_profile(email, normalized_avd_name)

        # Try to find if this user's AVD is already running
        running_emulators = self.device_discovery.map_running_emulators(self.get_all_profiles())
        if normalized_avd_name in running_emulators:
            emulator_id = running_emulators[normalized_avd_name]
            logger.info(f"Found user's AVD {normalized_avd_name} already running at {emulator_id}")
            self._save_profile_status(email, normalized_avd_name, emulator_id)
        else:
            self._save_profile_status(email, normalized_avd_name)

    def stop_emulator(self, device_id: str) -> bool:
        """Stop an emulator by device ID."""
        return self.emulator_manager.stop_specific_emulator(device_id)

    def start_emulator(self, email: str) -> bool:
        """Start the emulator for a specific email."""
        return self.emulator_manager.start_emulator_with_retries(email)

    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """Create a new AVD for the given email."""
        return self.avd_creator.create_new_avd(email)

    def _create_avd_with_seed_clone_fallback(self, email: str, normalized_avd_name: str) -> str:
        """Create a new AVD using seed clone if available, otherwise fall back to normal creation."""
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

    def is_styles_updated(self) -> bool:
        """Check if styles have been updated for a profile."""
        email = get_sindarin_email()
        if not email:
            logger.warning("No email available to check styles_updated")
            return False

        with self.db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(email)
            return user.styles_updated if user else False

    def get_style_setting(self, setting_name: str, email: str = None, default=None):
        """Get a style setting value from the profile."""
        if not email:
            email = get_sindarin_email()
            if not email:
                logger.warning("No email available to get style setting")
                return default

        return self.get_user_field(email, setting_name, default, section="library_settings")

    # save_reading_setting is already implemented above in the class

    def switch_profile_and_start_emulator(
        self, email: str, force_new_emulator: bool = False
    ) -> Tuple[bool, str]:
        """
        Switch to the profile for the given email.

        Args:
            email: The email address to switch to
            force_new_emulator: If True, stop existing emulator and start fresh

        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Reset device settings if forcing new emulator
        if force_new_emulator:
            settings_to_reset = [
                "hw_overlays_disabled",
                "animations_disabled",
                "sleep_disabled",
                "status_bar_disabled",
                "auto_updates_disabled",
            ]
            for setting in settings_to_reset:
                self.set_user_field(email, setting, False, section="emulator_settings")

        # No more simplified mode - always manage emulators properly

        #
        # Normal profile management mode below (for non-Mac or non-dev environments)
        # Now with multi-emulator support
        #

        # Get AVD name for this email - this should be the first step
        avd_name = self.get_avd_for_email(email)

        # Create AVD if needed
        if not avd_name:
            logger.info(f"No AVD found for {email}, creating new one")
            normalized_avd_name = self.get_avd_name_from_email(email)
            logger.info(f"Generated AVD name {normalized_avd_name} for {email}")

            # Register profile
            self.register_profile(email, normalized_avd_name)
            logger.info(f"Registered AVD {normalized_avd_name} for email {email}")

            # Create AVD
            avd_name = self._create_avd_with_seed_clone_fallback(email, normalized_avd_name)

            # Update profile if AVD name changed
            if avd_name != normalized_avd_name:
                self.register_profile(email, avd_name)

        # Check if AVD exists
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_ini_path = os.path.join(self.avd_dir, f"{avd_name}.ini")
        avd_exists = os.path.exists(avd_path) and os.path.exists(avd_ini_path)

        # Check for running emulator
        is_running, emulator_id, found_avd_name = self.find_running_emulator_for_email(email)

        # Handle force new emulator
        if is_running and force_new_emulator:
            logger.info(f"Stopping emulator {emulator_id} for fresh start")
            if not self.stop_emulator(emulator_id):
                logger.error(f"Failed to stop emulator {emulator_id}")
            is_running = False
            emulator_id = None

        # Use existing emulator if running
        if is_running and not force_new_emulator:
            logger.info(f"Found running emulator {emulator_id} for profile {email}")

            # Verify it's the correct AVD
            if found_avd_name != avd_name:
                logger.warning(f"Found wrong AVD {found_avd_name}, expected {avd_name}")
                return False, f"Cannot use another user's emulator for {email}"

            self._save_profile_status(email, avd_name, emulator_id)
            return True, f"Switched to profile {email} with existing running emulator"

        # No more ARM Mac workarounds - we can launch emulators properly now

        # Check if AVD exists before trying to start it
        if not avd_exists:
            logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. Attempting to create it.")

            # Check if this user requires ALT_SYSTEM_IMAGE
            if self.avd_creator.host_arch == "arm64":
                ignore_seed_clone = True  # Use the MAC_SYSTEM_IMAGE
            else:
                ignore_seed_clone = email in self.avd_creator.ALT_IMAGE_TEST_EMAILS

            # Check if we can use the seed clone for faster AVD creation
            # Skip seed clone for ALT_IMAGE users since seed clone uses Android 30
            if self.avd_creator.is_seed_clone_ready() and not ignore_seed_clone:
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
                if ignore_seed_clone:
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
        logger.info(f"Starting emulator for {email} with AVD {avd_name}")
        if not self.start_emulator(email):
            return False, "Failed to start emulator"

        # Update profile status
        self._save_profile_status(email, avd_name)
        return True, f"Successfully switched to profile {email} with AVD {avd_name}"

    # Legacy compatibility methods
    def _load_profiles_index(self) -> Dict[str, Dict]:
        """Load all profiles - for compatibility with old code."""
        return self.get_all_profiles()

    def _save_profiles_index(self) -> None:
        """Save profiles - no-op for database version as saves are automatic."""
        pass

    def _get_images_for_architecture(self) -> List[Tuple[str, str]]:
        """Get appropriate system images based on host architecture."""
        if self.host_arch == "arm64":
            return [
                ("system-images;android-30;google_apis_playstore;arm64-v8a", "arm64-v8a"),
                ("system-images;android-30;google_apis;arm64-v8a", "arm64-v8a"),
                ("system-images;android-29;google_apis_playstore;arm64-v8a", "arm64-v8a"),
                ("system-images;android-29;google_apis;arm64-v8a", "arm64-v8a"),
            ]
        else:  # x86_64 or others
            return [
                ("system-images;android-30;google_apis_playstore;x86_64", "x86_64"),
                ("system-images;android-30;google_apis;x86_64", "x86_64"),
                ("system-images;android-29;google_apis_playstore;x86_64", "x86_64"),
                ("system-images;android-29;google_apis;x86_64", "x86_64"),
            ]

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

            # Remove the user from database (only if recreating user AVD)
            if recreate_user:
                with self.db_connection.get_session() as session:
                    from database.repositories.user_repository import UserRepository

                    repo = UserRepository(session)
                    user = repo.get_user_by_email(email)
                    if user:
                        session.delete(user)
                        session.commit()
                        logger.info(f"Removed {email} from database")

            logger.info(f"Successfully recreated {', '.join(actions)} for {email}")
            return True, f"Successfully recreated: {', '.join(actions)}"

        except Exception as e:
            logger.error(f"Error recreating profile AVD for {email}: {e}", exc_info=True)
            return False, f"Failed to recreate profile AVD: {str(e)}"
