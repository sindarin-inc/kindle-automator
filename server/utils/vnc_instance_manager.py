import json
import logging
import os
import platform
import random
import subprocess
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

        # Calculate ports based on instance ID
        from server.utils.port_utils import PortConfig, calculate_emulator_ports

        ports = calculate_emulator_ports(next_id)
        emulator_port = ports["emulator_port"]
        vnc_port = ports["vnc_port"]
        appium_port = ports["appium_port"]

        # Get additional Appium-related ports
        appium_system_port = ports.get("system_port", PortConfig.SYSTEM_BASE_PORT + next_id)
        appium_chromedriver_port = ports.get("chromedriver_port", PortConfig.CHROMEDRIVER_BASE_PORT + next_id)
        appium_mjpeg_server_port = PortConfig.MJPEG_BASE_PORT + next_id

        # Create a new instance with the next available ID
        return {
            "id": next_id,
            "display": next_id,
            "vnc_port": vnc_port,
            "appium_port": appium_port,
            "emulator_port": emulator_port,
            "emulator_id": None,
            "assigned_profile": None,
            # New fields for Appium process tracking
            "appium_pid": None,
            "appium_running": False,
            "appium_last_health_check": None,
            # Additional Appium-related ports
            "appium_system_port": appium_system_port,
            "appium_chromedriver_port": appium_chromedriver_port,
            "appium_mjpeg_server_port": appium_mjpeg_server_port,
        }

    def save_instances(self) -> bool:
        """
        Save VNC instance mappings to the JSON file.

        Returns:
            bool: True if instances were saved successfully, False otherwise
        """
        try:
            # Ensure directory exists before saving
            os.makedirs(os.path.dirname(self.map_path), exist_ok=True)

            data = {"instances": self.instances, "version": 1}
            with open(self.map_path, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving VNC instances: {e}")
            return False

    def get_instance_for_profile(self, email: str) -> Optional[Dict]:
        """
        Get the VNC instance assigned to a specific profile.

        Args:
            email: Email address of the profile

        Returns:
            Optional[Dict]: VNC instance dictionary or None if not assigned
        """
        # Look directly for the email in assigned_profile
        logger.info(
            f"Looking for VNC instance for profile {email} in {[(i['assigned_profile'], i['emulator_id']) for i in self.instances]}"
        )
        for instance in self.instances:
            assigned_profile = instance.get("assigned_profile")
            if assigned_profile == email:
                return instance

        # logger.info(f"No VNC instance found for email {email}")
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

            # Log if assigned_profile is not None and is not the same as the email
            if assigned_profile is not None and assigned_profile != email:
                logger.info(
                    f"Assigned profile {assigned_profile} is not the same as the email {email}, this is a bug"
                )

            try:
                # Stop WebSocket proxy if running
                from server.utils.websocket_proxy_manager import WebSocketProxyManager

                ws_proxy_manager = WebSocketProxyManager.get_instance()
                if ws_proxy_manager.is_proxy_running(email):
                    logger.info(f"Stopping WebSocket proxy for {email} during cleanup")
                    ws_proxy_manager.stop_proxy(email)
            except Exception as e:
                logger.error(f"Error stopping WebSocket proxy during cleanup: {e}")

            # Clear Appium-related fields
            instance["appium_pid"] = None
            instance["appium_running"] = False
            instance["appium_last_health_check"] = None

            # Clear emulator_id - this is important to prevent stale references
            if instance.get("emulator_id"):
                logger.info(f"Clearing emulator_id {instance['emulator_id']} for {email}")
            instance["emulator_id"] = None

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
        instance = self.get_instance_for_profile(email)
        if instance:
            # Return stored appium_port if available
            if "appium_port" in instance:
                logger.info(f"Using VNC instance appium port {instance['appium_port']} for {email}")
                return instance["appium_port"]

            # Calculate port from ID if appium_port is not available
            instance_id = instance.get("id")
            if instance_id:
                calculated_port = self.calculate_appium_port(instance_id)
                logger.info(
                    f"Calculated appium port {calculated_port} from instance ID {instance_id} for {email}"
                )
                return calculated_port

        logger.info(f"No VNC instance found for {email}, no appium port available")
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

    def mark_running_for_deployment(self, email: str, should_restart: bool = True) -> bool:
        """
        Set or clear the restart flag for an emulator.

        Args:
            email: Email address of the profile
            should_restart: True to mark for restart (default), False to clear the flag

        Returns:
            bool: True if updated successfully
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager.get_instance()
            success = avd_manager.set_user_field(
                email, "was_running_at_restart", should_restart if should_restart else None
            )

            if success:
                action = "marked for restart" if should_restart else "cleared restart flag"
                logger.info(f"✓ Successfully {action} for {email}")
                return True
            else:
                logger.warning(f"Failed to update restart flag for {email}")
                return False
        except Exception as e:
            logger.error(f"Error setting restart flag for {email}: {e}")
            return False

    def get_running_at_restart(self) -> List[str]:
        """
        Get list of emails that were running at last restart.

        Returns:
            List[str]: Email addresses that were running at restart
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager.get_instance()
            running_emails = []

            # Check each profile for the was_running_at_restart flag
            # Get all profiles and check each one
            profiles = avd_manager.list_profiles()
            for profile in profiles:
                email = profile.get("email")
                if email:
                    was_running = avd_manager.get_user_field(email, "was_running_at_restart", False)
                    if was_running:
                        running_emails.append(email)

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

            avd_manager = AVDProfileManager.get_instance()

            # Clear flags for all profiles
            cleared_count = 0
            profiles = avd_manager.list_profiles()
            for profile in profiles:
                email = profile.get("email")
                if email and avd_manager.get_user_field(email, "was_running_at_restart", False):
                    avd_manager.set_user_field(email, "was_running_at_restart", None)
                    cleared_count += 1
                    logger.debug(f"Cleared was_running_at_restart flag for {email}")

            logger.info(f"Cleared {cleared_count} was_running_at_restart flags")
        except Exception as e:
            logger.error(f"Error clearing was_running_at_restart flags: {e}")

    def reset_appium_states_on_startup(self) -> None:
        """
        Reset all appium_running states to false on server startup.
        This ensures clean state after unexpected shutdowns.
        """
        try:
            reset_count = 0
            for instance in self.instances:  # instances is a list, not a dict
                if instance.get("appium_running", False):
                    instance["appium_running"] = False
                    instance["appium_pid"] = None
                    reset_count += 1
                    logger.info(f"Reset appium_running state for instance {instance['id']}")

            if reset_count > 0:
                self.save_instances()
                logger.info(f"Reset {reset_count} appium_running states on startup")
            else:
                logger.info("No appium_running states needed resetting")
        except Exception as e:
            logger.error(f"Error resetting appium states on startup: {e}")

    def get_all_instances(self) -> List[Dict]:
        """
        Get all VNC instances (both assigned and unassigned).

        Returns:
            List[Dict]: List of all VNC instances
        """
        return self.instances.copy()

    def get_assigned_instances(self) -> List[Dict]:
        """
        Get only VNC instances that are assigned to profiles.

        Returns:
            List[Dict]: List of assigned VNC instances
        """
        return [instance for instance in self.instances if instance.get("assigned_profile") is not None]

    def clear_emulator_id_for_profile(self, email: str) -> bool:
        """
        Clear the emulator_id for a specific profile's VNC instance.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if cleared successfully, False otherwise
        """
        instance = self.get_instance_for_profile(email)
        if instance and instance.get("emulator_id"):
            logger.info(f"Clearing emulator_id {instance['emulator_id']} for profile {email}")
            instance["emulator_id"] = None
            self.save_instances()
            return True
        return False

    def audit_and_cleanup_stale_instances(self) -> None:
        """Audit assigned VNC instances and clean up any that aren't actually running."""
        assigned_instances = self.get_assigned_instances()
        if assigned_instances:
            logger.info(f"Auditing {len(assigned_instances)} assigned VNC instances")
            for instance in assigned_instances:
                email = instance.get("assigned_profile")
                emulator_id = instance.get("emulator_id")
                if email and emulator_id:
                    # Check if emulator is still running via adb devices
                    try:
                        result = subprocess.run(
                            [f"{ANDROID_HOME}/platform-tools/adb", "devices"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if result.returncode == 0 and emulator_id not in result.stdout:
                            logger.info(
                                f"VNC instance for {email} has stale emulator_id {emulator_id}, releasing"
                            )
                            self.release_instance_from_profile(email)
                    except Exception as e:
                        logger.error(f"Error checking emulator status for {email}: {e}")
