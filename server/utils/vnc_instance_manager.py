"""VNC Instance Manager that uses the database instead of JSON files."""

import logging
import os
import platform
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

from database.repositories.vnc_instance_repository import VNCInstanceRepository
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)

DEFAULT_ANDROID_SDK = "/opt/android-sdk"
if platform.system() == "Darwin":
    DEFAULT_ANDROID_SDK = os.path.expanduser("~/Library/Android/sdk")

if os.environ.get("ANDROID_HOME"):
    ANDROID_HOME = os.environ.get("ANDROID_HOME")
else:
    ANDROID_HOME = DEFAULT_ANDROID_SDK

# Singleton instance
_instance = None


class VNCInstanceManager:
    """
    Manages multiple VNC instances and assigns them to user profiles.
    Uses the database for persistence instead of JSON files.
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
            _instance = cls()
        return _instance

    def __init__(self):
        """
        Initialize the VNC instance manager.
        Note: You should use get_instance() instead of creating instances directly.
        """
        # Check if this is being called directly or through get_instance()
        if _instance is not None and _instance is not self:
            logger.warning("VNCInstanceManager initialized directly. Use get_instance() instead.")

        self._repository = None
        self.is_macos = platform.system() == "Darwin"
        self._initialized = False

    @property
    def repository(self):
        """Lazy-load the repository to ensure database is ready."""
        if self._repository is None:
            self._repository = VNCInstanceRepository()
        return self._repository

    def _ensure_initialized(self):
        """Ensure the manager is fully initialized."""
        if not self._initialized:
            # Reset Appium states on startup
            self.reset_appium_states_on_startup()
            self._initialized = True

    def load_instances(self) -> bool:
        """
        Compatibility method - database instances are always available.

        Returns:
            bool: Always returns True
        """
        return True

    def _create_new_instance(self) -> Dict:
        """
        Create a new VNC instance with the next available ID.

        Returns:
            Dict: Newly created VNC instance as a dictionary
        """
        next_id = self.repository.get_next_available_id()

        # Calculate ports based on instance ID
        from server.utils.port_utils import PortConfig, calculate_emulator_ports

        ports = calculate_emulator_ports(next_id)

        # Create instance in database
        instance = self.repository.create_instance(
            display=next_id,
            vnc_port=ports["vnc_port"],
            appium_port=ports["appium_port"],
            emulator_port=ports["emulator_port"],
            appium_system_port=ports.get("system_port", PortConfig.SYSTEM_BASE_PORT + next_id),
            appium_chromedriver_port=ports.get(
                "chromedriver_port", PortConfig.CHROMEDRIVER_BASE_PORT + next_id
            ),
            appium_mjpeg_server_port=PortConfig.MJPEG_BASE_PORT + next_id,
        )

        return self._instance_to_dict(instance)

    def save_instances(self) -> bool:
        """
        Compatibility method - database changes are automatically persisted.

        Returns:
            bool: Always returns True
        """
        return True

    def get_instance_for_profile(self, email: str) -> Optional[Dict]:
        """
        Get the VNC instance assigned to a specific profile.

        Args:
            email: Email address of the profile

        Returns:
            Optional[Dict]: VNC instance dictionary or None if not assigned
        """
        self._ensure_initialized()
        instance = self.repository.get_instance_by_profile(email)
        return self._instance_to_dict(instance) if instance else None

    def assign_instance_to_profile(self, email: str, instance_id: Optional[int] = None) -> Optional[Dict]:
        """
        Assign a VNC instance to a profile. Creates a new instance if needed.
        Always starts a WebSocket proxy for noVNC support.

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
            # Always ensure WebSocket proxy is running for noVNC support
            self._ensure_websocket_proxy(email, existing["vnc_port"])
            return existing

        # Try to assign the specified instance if provided
        if instance_id is not None:
            instance = self.repository.get_instance_by_id(instance_id)
            if instance:
                if instance.assigned_profile is None:
                    if self.repository.assign_instance_to_profile(instance_id, email):
                        logger.info(f"Assigned VNC instance {instance_id} to email {email}")
                        result = self._instance_to_dict(self.repository.get_instance_by_id(instance_id))
                        # Always start WebSocket proxy for noVNC support
                        if result:
                            self._ensure_websocket_proxy(email, result["vnc_port"])
                        return result
                else:
                    logger.warning(
                        f"VNC instance {instance_id} is already assigned to {instance.assigned_profile}"
                    )
                    return None
            else:
                logger.warning(f"VNC instance {instance_id} not found")
                return None

        # Find an available instance to assign
        unassigned = self.repository.get_unassigned_instances()
        if unassigned:
            instance = unassigned[0]
            if self.repository.assign_instance_to_profile(instance.id, email):
                logger.info(f"Assigned VNC instance {instance.id} to email {email}")
                result = self._instance_to_dict(self.repository.get_instance_by_id(instance.id))
                # Always start WebSocket proxy for noVNC support
                if result:
                    self._ensure_websocket_proxy(email, result["vnc_port"])
                return result

        # No available instances, create a new one
        new_instance_dict = self._create_new_instance()
        if self.repository.assign_instance_to_profile(new_instance_dict["id"], email):
            logger.info(f"Created and assigned new VNC instance {new_instance_dict['id']} to email {email}")
            result = self._instance_to_dict(self.repository.get_instance_by_id(new_instance_dict["id"]))
            # Always start WebSocket proxy for noVNC support
            if result:
                self._ensure_websocket_proxy(email, result["vnc_port"])
            return result

        return None

    def _ensure_websocket_proxy(self, email: str, vnc_port: int) -> Optional[int]:
        """
        Ensure WebSocket proxy is running for noVNC support.

        Args:
            email: Email address of the profile
            vnc_port: VNC port to proxy

        Returns:
            Optional[int]: WebSocket port if proxy started, None otherwise
        """
        try:
            from server.utils.websocket_proxy_manager import WebSocketProxyManager

            ws_manager = WebSocketProxyManager.get_instance()

            # Check if proxy is already running
            if not ws_manager.is_proxy_running(email):
                # Start the proxy
                ws_port = ws_manager.start_proxy(email, vnc_port)
                if ws_port:
                    logger.info(
                        f"Started WebSocket proxy for {email} on port {ws_port} (VNC port {vnc_port})"
                    )
                    return ws_port
                else:
                    logger.warning(f"Failed to start WebSocket proxy for {email}")
            else:
                logger.debug(f"WebSocket proxy already running for {email}")

        except Exception as e:
            logger.warning(f"Error ensuring WebSocket proxy for {email}: {e}")

        return None

    def release_instance_from_profile(self, email: str) -> bool:
        """
        Release the VNC instance assigned to a profile.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if an instance was released, False otherwise
        """
        instance = self.repository.get_instance_by_profile(email)
        if not instance:
            logger.info(f"No VNC instance found assigned to profile {email}")
            return False

        instance_id = instance.id

        try:
            # Stop WebSocket proxy if running
            from server.utils.websocket_proxy_manager import WebSocketProxyManager

            ws_proxy_manager = WebSocketProxyManager.get_instance()
            if ws_proxy_manager.is_proxy_running(email):
                logger.info(f"Stopping WebSocket proxy for {email} during cleanup")
                ws_proxy_manager.stop_proxy(email)
        except Exception as e:
            logger.error(f"Error stopping WebSocket proxy during cleanup: {e}", exc_info=True)

        # Release instance in database
        if self.repository.release_instance_from_profile(email):
            logger.info(f"Released VNC instance {instance_id} from profile {email}")
            return True

        return False

    def get_vnc_port(self, email: str) -> Optional[int]:
        """
        Get the VNC port for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The VNC port or None if no instance is assigned
        """
        instance = self.repository.get_instance_by_profile(email)
        return instance.vnc_port if instance else None

    def get_x_display(self, email: str) -> Optional[int]:
        """
        Get the X display number for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The X display number or None if no instance is assigned
        """
        instance = self.repository.get_instance_by_profile(email)
        return instance.display if instance else None

    def get_appium_port(self, email: str) -> Optional[int]:
        """
        Get the Appium port for a profile's assigned instance.

        Args:
            email: Email address of the profile

        Returns:
            Optional[int]: The Appium port or None if no instance is assigned
        """
        instance = self.repository.get_instance_by_profile(email)
        if instance:
            logger.info(f"Using VNC instance appium port {instance.appium_port} for {email}")
            return instance.appium_port

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
        instance = self.repository.get_instance_by_profile(email)
        return instance.emulator_id if instance else None

    def set_emulator_id(self, email: str, emulator_id: str) -> bool:
        """
        Set the emulator ID for a profile's assigned instance.
        Should only be called when an emulator successfully starts.

        Args:
            email: Email address of the profile
            emulator_id: The emulator ID to set (e.g., 'emulator-5554')

        Returns:
            bool: True if successful, False otherwise
        """
        if not emulator_id or not emulator_id.startswith("emulator-"):
            logger.error(f"Invalid emulator_id format: {emulator_id}")
            return False
        return self.repository.update_emulator_id(email, emulator_id)

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
            logger.error(f"Error setting restart flag for {email}: {e}", exc_info=True)
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
            return avd_manager.get_profiles_with_restart_flag()
        except Exception as e:
            logger.error(f"Error getting running at restart emails: {e}", exc_info=True)
            return []

    def clear_running_at_restart_flags(self) -> None:
        """
        Clear all was_running_at_restart flags after server startup.
        """
        try:
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager.get_instance()
            cleared_count = avd_manager.clear_all_restart_flags()
            logger.info(f"Cleared {cleared_count} was_running_at_restart flags")
        except Exception as e:
            logger.error(f"Error clearing was_running_at_restart flags: {e}", exc_info=True)

    def update_appium_status(self, email: str, running: bool, pid: Optional[int] = None) -> bool:
        """
        Update the Appium status for a profile's instance.

        Args:
            email: Email address of the profile
            running: Whether Appium is running
            pid: Optional process ID

        Returns:
            bool: True if update was successful
        """
        from datetime import datetime, timezone

        health_check = datetime.now(timezone.utc) if running else None
        return self.repository.update_appium_status(email, running, pid, health_check)

    def reset_appium_states_on_startup(self) -> None:
        """
        Reset all appium_running states to false on server startup.
        This ensures clean state after unexpected shutdowns.
        """
        try:
            # Don't call _ensure_initialized here to avoid recursion
            reset_count = self.repository.reset_all_appium_states()
        except Exception as e:
            logger.error(f"Error resetting appium states on startup: {e}", exc_info=True)

    def get_all_instances(self) -> List[Dict]:
        """
        Get all VNC instances (both assigned and unassigned).

        Returns:
            List[Dict]: List of all VNC instances
        """
        self._ensure_initialized()
        instances = self.repository.get_all_instances()
        return [self._instance_to_dict(inst) for inst in instances]

    def get_assigned_instances(self) -> List[Dict]:
        """
        Get only VNC instances that are assigned to profiles.

        Returns:
            List[Dict]: List of assigned VNC instances
        """
        instances = self.repository.get_assigned_instances()
        return [self._instance_to_dict(inst) for inst in instances]

    def _instance_to_dict(self, instance) -> Dict:
        """Convert a VNCInstance model to a dictionary matching the old JSON format."""
        if not instance:
            return None

        return {
            "id": instance.id,
            "display": instance.display,
            "vnc_port": instance.vnc_port,
            "appium_port": instance.appium_port,
            "emulator_port": instance.emulator_port,
            "emulator_id": instance.emulator_id,
            "assigned_profile": instance.assigned_profile,
            "appium_pid": instance.appium_pid,
            "appium_running": instance.appium_running,
            "appium_last_health_check": (
                instance.appium_last_health_check.timestamp() if instance.appium_last_health_check else None
            ),
            "appium_system_port": instance.appium_system_port,
            "appium_chromedriver_port": instance.appium_chromedriver_port,
            "appium_mjpeg_server_port": instance.appium_mjpeg_server_port,
        }

    @property
    def instances(self) -> List[Dict]:
        """Property for backward compatibility - returns all instances as dicts."""
        return self.get_all_instances()

    def calculate_vnc_port(self, instance_id: int) -> int:
        """Calculate VNC port from instance ID for backward compatibility."""
        from server.utils.port_utils import calculate_emulator_ports

        ports = calculate_emulator_ports(instance_id)
        return ports["vnc_port"]

    def calculate_appium_port(self, instance_id: int) -> int:
        """Calculate Appium port from instance ID for backward compatibility."""
        from server.utils.port_utils import calculate_emulator_ports

        ports = calculate_emulator_ports(instance_id)
        return ports["appium_port"]

    def audit_and_cleanup_stale_instances(self):
        """
        Audit VNC instances and clean up any that don't have running emulators.
        This ensures the VNC instance table stays accurate and doesn't hold stale entries.
        A stale entry is:
        1. An instance with an emulator_id that's not actually running
        2. An instance with an assigned profile but no emulator_id (indicates failed/crashed emulator)
        """
        logger.debug("Starting VNC instance audit to clean up stale entries")

        # Get all instances for this server
        all_instances = self.repository.get_all_instances()

        # Get list of actually running emulators
        running_emulators = []
        try:
            result = subprocess.run(
                [f"{ANDROID_HOME}/platform-tools/adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                # Parse adb devices output
                for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                    if "\t" in line:
                        device_id = line.split("\t")[0]
                        if device_id.startswith("emulator-"):
                            running_emulators.append(device_id)

            logger.info(f"Found {len(running_emulators)} running emulators: {running_emulators}")
        except Exception as e:
            logger.error(f"Error getting running emulators: {e}")
            return

        cleaned_count = 0

        # Check each instance
        for instance in all_instances:
            # Case 1: Instance has an emulator_id that's not actually running
            if instance.emulator_id and instance.emulator_id not in running_emulators:
                logger.warning(
                    f"Clearing stale emulator_id {instance.emulator_id} from VNC instance {instance.id} "
                    f"(display :{instance.display}, port {instance.emulator_port}, profile {instance.assigned_profile})"
                )

                # Clear the emulator_id since it's not actually running
                self.repository.update_emulator_id(instance.assigned_profile, None)
                cleaned_count += 1

            # Case 2: Instance has an assigned profile but no emulator_id (stale assignment)
            elif instance.assigned_profile and not instance.emulator_id:
                logger.warning(
                    f"Releasing stale assignment: VNC instance {instance.id} assigned to {instance.assigned_profile} "
                    f"but has no emulator_id (display :{instance.display}, port {instance.emulator_port})"
                )
                # Release the stale assignment since users get reassigned dynamically
                self.repository.release_instance_from_profile(instance.assigned_profile)
                cleaned_count += 1

            # Case 3: Instance has no profile and no emulator (available for use)
            elif not instance.assigned_profile and not instance.emulator_id:
                logger.debug(f"VNC instance {instance.id} is available (no profile, no emulator)")

        # Also check for emulator IDs in the table that shouldn't be there
        stale_count = self.repository.clear_stale_emulator_ids(running_emulators)
        if stale_count > 0:
            logger.info(f"Cleared {stale_count} additional stale emulator IDs from VNC instances")
            cleaned_count += stale_count

        if cleaned_count > 0:
            logger.info(f"VNC instance audit complete: cleaned {cleaned_count} stale entries")
        else:
            logger.debug("VNC instance audit complete: no stale entries found")
