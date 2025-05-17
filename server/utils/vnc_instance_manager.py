import json
import logging
import os
import platform
import random
from typing import Dict, List, Optional, Tuple

from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)

# Default path to VNC instance mapping file
# Use the same path as in EmulatorLauncher - in the Android SDK profiles directory
import os

DEFAULT_ANDROID_SDK = "/opt/android-sdk"
if os.environ.get("ANDROID_HOME"):
    ANDROID_HOME = os.environ.get("ANDROID_HOME")
else:
    ANDROID_HOME = DEFAULT_ANDROID_SDK

# Use user_data directory for macOS/Darwin systems
is_macos = platform.system() == "Darwin"
if is_macos:
    # Use project's user_data directory instead of Android SDK profiles
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    PROFILES_DIR = os.path.join(project_root, "user_data")
else:
    PROFILES_DIR = os.path.join(ANDROID_HOME, "profiles")

VNC_INSTANCE_MAP_PATH = os.path.join(PROFILES_DIR, "vnc_instance_map.json")

# Singleton instance
_instance = None


class VNCInstanceManager:
    """
    Manages multiple VNC instances and assigns them to user profiles.
    Implements the singleton pattern to ensure only one instance exists.
    """

    @classmethod
    def get_instance(cls) -> "VNCInstanceManager":
        """
        Get the singleton instance of VNCInstanceManager.

        Returns:
            VNCInstanceManager: The singleton instance
        """
        global _instance
        if _instance is None:
            _instance = cls(VNC_INSTANCE_MAP_PATH)
        return _instance

    def __init__(self, map_path: str = VNC_INSTANCE_MAP_PATH):
        """
        Initialize the VNC instance manager.
        Note: You should use get_instance() instead of creating instances directly.

        Args:
            map_path: Path to the VNC instance mapping JSON file
        """
        # Check if this is being called directly or through get_instance()
        global _instance
        if _instance is not None and _instance is not self:
            logger.warning("VNCInstanceManager initialized directly. Use get_instance() instead.")

        self.map_path = map_path
        self.instances = []

        # Ensure profiles directory exists
        os.makedirs(os.path.dirname(self.map_path), exist_ok=True)

        # Determine if we're on macOS/Darwin
        self.is_macos = platform.system() == "Darwin"

        # Path to the profiles index file - use user_data on macOS, otherwise use Android SDK profiles
        if self.is_macos:
            # Use project's user_data directory for macOS
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.profiles_dir = os.path.join(project_root, "user_data")
            logger.info(f"Using {self.profiles_dir} for users.json on macOS")
        else:
            # For non-Mac environments, use standard directory structure
            android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
            self.profiles_dir = os.path.join(android_home, "profiles")

        self.users_file_path = os.path.join(self.profiles_dir, "users.json")
        self.profiles_index = {}  # Email to AVD mapping

        # Load the profiles index if it exists
        self._load_profiles_index()

        # Load VNC instances or create new ones with email-based assignments
        self.load_instances()

    def load_instances(self) -> bool:
        """
        Load VNC instance mappings from the JSON file.

        Returns:
            bool: True if instances were loaded successfully, False otherwise
        """
        try:
            if os.path.exists(self.map_path):
                with open(self.map_path, "r") as f:
                    data = json.load(f)
                    self.instances = data.get("instances", [])
                    # Ensure we have a valid instances list
                    if not isinstance(self.instances, list):
                        logger.warning(
                            f"Invalid instances format in {self.map_path}, resetting to empty list"
                        )
                        self.instances = []

                    # Log info about loaded instances
                    active_instances = [i for i in self.instances if i.get("assigned_profile") is not None]
                    logger.info(f"Loaded {len(self.instances)} VNC instances, {len(active_instances)} active")
                    return True
            else:
                # Create an empty list for development environments
                logger.info(f"VNC instance map not found at {self.map_path}, creating empty instance list")
                self.instances = self._create_default_instances()
                self.save_instances()
                return True
        except Exception as e:
            logger.error(f"Error loading VNC instances: {e}")
            self.instances = self._create_default_instances()
            return False

    def _create_default_instances(self) -> List[Dict]:
        """
        Create an empty list for VNC instances that will be populated dynamically.

        Returns:
            List[Dict]: Empty list for VNC instances
        """
        # Return an empty list - instances will be created dynamically as needed
        return []

    def calculate_emulator_port(self, instance_id: int) -> int:
        """
        Calculate emulator port based on instance ID.

        Args:
            instance_id: The instance ID

        Returns:
            int: The emulator port
        """
        # Emulator ports are typically 5554, 5556, 5558, etc. (even numbers)
        return 5554 + ((instance_id - 1) * 2)

    def calculate_vnc_port(self, instance_id: int) -> int:
        """
        Calculate VNC port based on instance ID.

        Args:
            instance_id: The instance ID

        Returns:
            int: The VNC port
        """
        # VNC ports start at 5900 and increment by 1
        return 5900 + instance_id

    def calculate_appium_port(self, instance_id: int) -> int:
        """
        Calculate Appium port based on instance ID.

        Args:
            instance_id: The instance ID

        Returns:
            int: The Appium port
        """
        # Appium ports start at 4723 and increment by 1
        return 4723 + instance_id

    def _create_new_instance(self) -> Dict:
        """
        Create a new VNC instance with the next available ID.

        Returns:
            Dict: Newly created VNC instance
        """
        # Determine next available ID from existing instances
        next_id = 1
        if self.instances:
            existing_ids = [instance["id"] for instance in self.instances]
            next_id = max(existing_ids) + 1

        # Calculate ports based on instance ID
        emulator_port = self.calculate_emulator_port(next_id)
        vnc_port = self.calculate_vnc_port(next_id)
        appium_port = self.calculate_appium_port(next_id)

        # Create a new instance with the next available ID
        return {
            "id": next_id,
            "display": next_id,
            "vnc_port": vnc_port,
            "appium_port": appium_port,
            "emulator_port": emulator_port,
            "emulator_id": None,
            "assigned_profile": None,
        }

    def save_instances(self) -> bool:
        """
        Save VNC instance mappings to the JSON file.

        Returns:
            bool: True if instances were saved successfully, False otherwise
        """
        try:
            data = {"instances": self.instances, "version": 1}
            with open(self.map_path, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving VNC instances: {e}")
            return False

    def _load_profiles_index(self) -> Dict:
        """
        Load the profiles index file.

        Returns:
            Dict: The profiles index mapping (email -> AVD ID)
        """
        try:
            if os.path.exists(self.users_file_path):
                with open(self.users_file_path, "r") as f:
                    self.profiles_index = json.load(f)
            else:
                logger.debug(f"No profiles index found at {self.users_file_path}")
                self.profiles_index = {}
        except Exception as e:
            logger.error(f"Error loading profiles index: {e}")
            self.profiles_index = {}

        return self.profiles_index

    def _get_avd_id_for_email(self, email: str) -> Optional[str]:
        """
        Get the AVD ID for a given email from the profiles index.

        Args:
            email: The user's email address

        Returns:
            Optional[str]: The AVD ID or None if not found
        """
        if not email:
            return None

        # Check if we need to reload the profiles index
        if not self.profiles_index:
            self._load_profiles_index()

        # Get the AVD ID from the profiles index
        avd_id = self.profiles_index.get(email)
        if avd_id:
            # Handle both string and dictionary formats for backward compatibility
            if isinstance(avd_id, dict):
                # If it's a dictionary, look for avd_name key
                if "avd_name" in avd_id:
                    avd_name = avd_id["avd_name"]
                    # Extract unique identifier if it's the full AVD name
                    if isinstance(avd_name, str) and avd_name.startswith("KindleAVD_"):
                        return avd_name[len("KindleAVD_") :]
                    else:
                        return avd_name
                else:
                    # No avd_name key in dictionary
                    logger.warning(f"AVD ID dictionary for {email} has no avd_name key: {avd_id}")
                    return None
            elif isinstance(avd_id, str):
                # Extract just the unique identifier part (e.g., 'kindle_solreader_com')
                # from AVD name like 'KindleAVD_kindle_solreader_com'
                if avd_id.startswith("KindleAVD_"):
                    return avd_id[len("KindleAVD_") :]
                else:
                    return avd_id
            else:
                # Unexpected type
                logger.warning(f"Unexpected AVD ID type for {email}: {type(avd_id)}")
                return None

        logger.debug(f"No AVD ID found for email {email}")
        return None

    def get_instance_for_profile(self, email: str) -> Optional[Dict]:
        """
        Get the VNC instance assigned to a specific profile.

        Args:
            email: Email address of the profile

        Returns:
            Optional[Dict]: VNC instance dictionary or None if not assigned
        """
        # Look directly for the email in assigned_profile
        for instance in self.instances:
            assigned_profile = instance.get("assigned_profile")
            if assigned_profile == email:
                return instance

        logger.info(f"No VNC instance found for email {email}")
        return None

    def assign_instance_to_profile(self, email: str, instance_id: Optional[int] = None) -> Optional[Dict]:
        """
        Assign a VNC instance to a profile. Creates a new instance if needed.

        Args:
            email: Email address of the profile
            instance_id: Optional specific instance ID to assign

        Returns:
            Optional[Dict]: The assigned instance or None if assignment failed
        """
        # First check if this profile already has an assigned instance
        existing = self.get_instance_for_profile(email)
        if existing:
            logger.info(f"Profile {email} is already assigned to VNC instance {existing['id']}")
            return existing

        # Try to assign the specified instance if provided
        if instance_id is not None:
            for instance in self.instances:
                if instance["id"] == instance_id:
                    if instance["assigned_profile"] is None:
                        # Use the email directly as the assigned_profile value
                        instance["assigned_profile"] = email
                        self.save_instances()
                        logger.info(f"Assigned VNC instance {instance_id} to email {email}")

                        # No need to sync with EmulatorLauncher - it now uses this singleton instance directly

                        return instance
                    else:
                        logger.warning(
                            f"VNC instance {instance_id} is already assigned to {instance['assigned_profile']}"
                        )
                        return None

            logger.warning(f"VNC instance {instance_id} not found")
            return None

        # Find an available instance to assign
        for instance in self.instances:
            if instance["assigned_profile"] is None:
                # Found an available instance - use the email directly
                instance["assigned_profile"] = email
                self.save_instances()
                logger.info(f"Assigned VNC instance {instance['id']} to email {email}")
                return instance

        # No available instances, create a new one
        new_instance = self._create_new_instance()
        new_instance["assigned_profile"] = email
        self.instances.append(new_instance)
        self.save_instances()
        logger.info(f"Created and assigned new VNC instance {new_instance['id']} to email {email}")

        # No need to sync with EmulatorLauncher - it now uses this singleton instance directly

        return new_instance

    def release_instance_from_profile(self, email: str) -> bool:
        """
        Release the VNC instance assigned to a profile.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if an instance was released, False otherwise
        """
        # Get the assigned instance for this profile
        instance = self.get_instance_for_profile(email)
        if instance:
            instance_id = instance.get("id")
            assigned_profile = instance.get("assigned_profile")
            instance["assigned_profile"] = None
            self.save_instances()
            logger.info(f"Released VNC instance {instance_id} from profile {email}")

            # No need to sync with EmulatorLauncher - it now uses this singleton instance directly

            return True

        # No instance found
        logger.info(f"No VNC instance found assigned to profile {email}")
        return False

    def get_vnc_port(self, email: str) -> Optional[int]:
        """
        Get the VNC port for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The VNC port or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            # Return stored vnc_port if available
            if "vnc_port" in instance:
                return instance["vnc_port"]

            # Calculate port from ID if vnc_port is not available
            instance_id = instance.get("id")
            if instance_id:
                return self.calculate_vnc_port(instance_id)

        return None

    def get_x_display(self, email: str) -> Optional[int]:
        """
        Get the X display number for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The X display number or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            # The display number is typically the same as the instance ID
            return instance.get("display", instance.get("id"))
        return None

    def get_appium_port(self, email: str) -> Optional[int]:
        """
        Get the Appium port for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The Appium port or None if no instance is assigned
        """
        try:
            # Check if we're on macOS development environment
            import platform as sys_platform  # Import inside the function to avoid name clash

            if sys_platform.system() == "Darwin":
                # On macOS dev, use a fixed appium port (4723) if no explicit port is assigned
                # This helps with local debugging/development
                logger.info(f"On macOS dev environment, using default Appium port 4723 for {email}")
                return 4723
        except Exception as e:
            logger.warning(f"Error checking platform for appium port: {e}")
            # Default to 4723 if there's any error on macOS
            return 4723

        instance = self.get_instance_for_profile(email)
        if instance:
            # Return stored appium_port if available
            if "appium_port" in instance:
                return instance["appium_port"]

            # Calculate port from ID if emulator_port is not available
            instance_id = instance.get("id")
            if instance_id:
                return self.calculate_appium_port(instance_id)

        return None

    def get_emulator_id(self, email: str) -> Optional[str]:
        """
        Get the emulator ID for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[str]: The emulator ID or None if not assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance and "emulator_id" in instance:
            return instance["emulator_id"]
        return None

    def set_emulator_id(self, email: str, emulator_id: str) -> bool:
        """
        Set the emulator ID for a profile's assigned instance.

        Args:
            email: Email address of the profile
            emulator_id: The emulator ID to set

        Returns:
            bool: True if successful, False otherwise
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            instance["emulator_id"] = emulator_id
            self.save_instances()
            return True
        return False

    def mark_running_for_deployment(self, email: str) -> bool:
        """
        Mark an emulator as running at deployment time.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if marked successfully
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager()
            success = avd_manager.set_user_field(email, "was_running_at_restart", True)

            if success:
                logger.info(f"✓ Successfully marked {email} as running at deployment")
                # Verify it was saved
                verify = avd_manager.get_user_field(email, "was_running_at_restart", False)
                logger.info(f"Verification: {email} was_running_at_restart = {verify}")
                return True
            else:
                logger.warning(f"Failed to mark {email} as running at deployment")
                return False
        except Exception as e:
            logger.error(f"Error marking {email} as running at deployment: {e}")
            return False

    def get_running_at_restart(self) -> List[str]:
        """
        Get list of emails that were running at last restart.

        Returns:
            List[str]: Email addresses that were running at restart
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager()
            running_emails = []

            # Check each profile for the was_running_at_restart flag
            logger.info(f"Checking {len(avd_manager.profiles_index)} profiles for restart flags")
            for email in avd_manager.profiles_index.keys():
                was_running = avd_manager.get_user_field(email, "was_running_at_restart", False)
                logger.debug(f"Profile {email}: was_running_at_restart = {was_running}")
                if was_running:
                    running_emails.append(email)
                    logger.info(f"✓ Found {email} marked for restart")

            logger.info(f"Total emulators marked for restart: {len(running_emails)}")
            return running_emails
        except Exception as e:
            logger.error(f"Error getting running at restart emails: {e}")
            return []

    def clear_running_at_restart_flags(self) -> None:
        """
        Clear all was_running_at_restart flags after server startup.
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager()

            # Clear flags for all profiles
            cleared_count = 0
            for email in avd_manager.profiles_index.keys():
                if avd_manager.get_user_field(email, "was_running_at_restart", False):
                    avd_manager.set_user_field(email, "was_running_at_restart", None)
                    cleared_count += 1
                    logger.debug(f"Cleared was_running_at_restart flag for {email}")

            logger.info(f"Cleared {cleared_count} was_running_at_restart flags")
        except Exception as e:
            logger.error(f"Error clearing was_running_at_restart flags: {e}")
