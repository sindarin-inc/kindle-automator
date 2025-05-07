import json
import logging
import os
import random
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default path to VNC instance mapping file
# Use the same path as in EmulatorLauncher - in the Android SDK profiles directory
import os

DEFAULT_ANDROID_SDK = "/opt/android-sdk"
if os.environ.get("ANDROID_HOME"):
    ANDROID_HOME = os.environ.get("ANDROID_HOME")
else:
    ANDROID_HOME = DEFAULT_ANDROID_SDK
PROFILES_DIR = os.path.join(ANDROID_HOME, "profiles")
VNC_INSTANCE_MAP_PATH = os.path.join(PROFILES_DIR, "vnc_instance_map.json")


class VNCInstanceManager:
    """
    Manages multiple VNC instances and assigns them to user profiles.
    """

    def __init__(self, map_path: str = VNC_INSTANCE_MAP_PATH):
        """
        Initialize the VNC instance manager.

        Args:
            map_path: Path to the VNC instance mapping JSON file
        """
        self.map_path = map_path
        self.instances = []

        # Ensure profiles directory exists
        os.makedirs(os.path.dirname(self.map_path), exist_ok=True)

        # Path to the profiles index file - same structure as used by AVDProfileManager
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

        # Create a new instance with the next available ID
        return {
            "id": next_id,
            "display": next_id,
            "vnc_port": 5900 + next_id,
            "appium_port": 4723 + next_id,
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
            return instance["vnc_port"]
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
            return instance["display"]
        return None

    def get_appium_port(self, email: str) -> Optional[int]:
        """
        Get the Appium port for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The Appium port or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance and "appium_port" in instance:
            return instance["appium_port"]
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
