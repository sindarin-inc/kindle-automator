import logging
import os
import subprocess
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

import requests

from automator import Automator
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class AutomationServer:
    def __init__(self, android_home: str, avd_dir: str):
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.profile_manager = AVDProfileManager(android_home, avd_dir)
        self.automators: Dict[str, Automator] = {}  # Per-email automators

        # Multiple Appium instances tracked by email/port
        self.appium_processes = {}

        # Track allocated ports by email instead of a single global set
        self.allocated_ports = {}  # email -> ports dict

        # Track the last activity time for each email in Unix timestamp
        self.last_activity = {}

        # Track current books by email
        self.current_books = {}  # email -> book info dict

        # LRU cache for recently accessed profiles
        self.recent_profiles = deque(maxlen=10)  # Keep track of 10 most recent

    def shutdown_emulator(self, email: str) -> bool:
        """Shutdown the emulator for a specific email.

        Args:
            email: Email associated with the emulator

        Returns:
            bool: True if shutdown was successful
        """
        # Get the automator instance for this email
        automator = self.automators.get(email)

        # If the automator exists and has a device_id, then we know the emulator is running
        if automator and hasattr(automator, "device_id") and automator.device_id:
            device_id = automator.device_id
            logger.info(f"Shutting down emulator {device_id} for {email}")

            try:
                subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "-s", device_id, "emu", "kill"], check=True
                )

                # Clean up the automator instance
                logger.info(f"Cleaning up automator instance for {email}")
                if automator:
                    automator.cleanup()
                    self.automators[email] = None

                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to shutdown emulator {device_id}: {e}")
                return False
        elif hasattr(self.profile_manager, "get_profile_for_email"):
            # Check if there's a recent emulator for this email
            profile = self.profile_manager.get_profile_for_email(email)
            if profile and profile.get("emulator_id"):
                device_id = profile["emulator_id"]
                logger.info(f"Found device {device_id} from profile for {email}, shutting down...")
                try:
                    subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "-s", device_id, "emu", "kill"],
                        check=True,
                    )
                    return True
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to shutdown emulator {device_id}: {e}")
                    return False
        else:
            logger.info(f"No running emulator found for {email}")
            return True

    def stop_appium(self, port: Optional[int] = None, email: Optional[str] = None) -> bool:
        """Stop the Appium server for the given port or email.

        Args:
            port: The port to stop Appium on
            email: The email associated with the Appium instance

        Returns:
            bool: True if stopped successfully
        """
        # Find the port by email if not provided
        if email and not port:
            appium_info = self.appium_processes.get(email)
            if appium_info:
                port = appium_info.get("port")

        if not port:
            logger.warning("No port or email provided to stop_appium")
            return False

        # Clean up the process tracking if we have an email
        if email and email in self.appium_processes:
            del self.appium_processes[email]
            logger.info(f"Removed appium process tracking for {email}")

        try:
            # Use lsof to find all processes on this port
            lsof_output = subprocess.run(
                ["lsof", "-i", f"tcp:{port}"], capture_output=True, text=True, check=False
            ).stdout

            if lsof_output:
                # Parse the output and kill all processes
                lines = lsof_output.strip().split("\n")[1:]  # Skip header
                for line in lines:
                    if line:
                        parts = line.split()
                        if len(parts) > 1:
                            pid = parts[1]
                            try:
                                subprocess.run(["kill", "-9", pid], check=False)
                                logger.info(f"Killed process {pid} on port {port}")
                            except Exception as e:
                                logger.warning(f"Failed to kill process {pid}: {e}")

            return True
        except Exception as e:
            logger.error(f"Error stopping Appium on port {port}: {e}")
            return False

    def clear_current_book(self, email: str):
        """Clear the current book tracking for a given email.

        Args:
            email: Email to clear book tracking for
        """
        if email in self.current_books:
            del self.current_books[email]
            logger.info(f"Cleared current book tracking for {email}")

    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """Switch to a profile for the given email address.

        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any emulator for this email and start a new one
                               (used with recreate=1 flag)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        if not email:
            logger.error("Email parameter is required for switch_profile")
            return False, "Email parameter is required"

        # Set email context for this thread so logs go to the right file
        from server.logging_config import EmailContext

        with EmailContext(email):
            return self._switch_profile_impl(email, force_new_emulator)

    def _switch_profile_impl(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """Internal implementation of switch_profile with email context already set."""

        # current_email field has been removed
        # Always use explicit email parameters in all operations

        # Check if there's a running emulator for this profile
        is_running, emulator_id, avd_name = self.profile_manager.find_running_emulator_for_email(email)

        # Check if we already have an automator for this email
        if email in self.automators and self.automators[email]:
            # Ensure existing automator has the emulator_manager property
            if not hasattr(self.automators[email], "emulator_manager"):
                logger.info(f"Adding missing emulator_manager to existing automator for {email}")
                self.automators[email].emulator_manager = self.profile_manager.emulator_manager

            # Check if the automator's device is actually available via ADB
            device_available = False
            if hasattr(self.automators[email], "device_id") and self.automators[email].device_id:
                # Try to verify if the device is actually available in ADB
                device_id = self.automators[email].device_id
                logger.info(f"Verifying if automator's device {device_id} is actually available")
                try:
                    # This will throw an exception if the device isn't recognized by ADB
                    result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "-s", device_id, "get-state"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    device_available = result.returncode == 0 and "device" in result.stdout
                    logger.info(
                        f"Device {device_id} verification: available={device_available}, result={result.stdout.strip()}"
                    )
                except Exception as e:
                    logger.warning(f"Error checking device {device_id} availability: {e}")
                    device_available = False

            # Handle different scenarios based on emulator state
            if is_running and not force_new_emulator and device_available:
                logger.info(
                    f"Automator already exists with running emulator for profile {email}, skipping profile switch"
                )
                return True, f"Already using profile for {email} with running emulator"
            elif not is_running or not device_available:
                # Either the emulator isn't running or the device isn't available in ADB
                if not is_running:
                    logger.info(f"Emulator not running for {email} according to ADB")
                if not device_available:
                    logger.info(f"Device ID {self.automators[email].device_id} no longer available in ADB")

                if not force_new_emulator:
                    # We no longer have a concept of "current" profile
                    # Always switch to the requested profile if needed

                    # We need to force a new emulator since the old one is no longer available
                    logger.info(f"Emulator for {email} no longer available, forcing new emulator creation")
                    # Cleanup existing automator
                    self.automators[email].cleanup()
                    self.automators[email] = None
                    # Force a new emulator
                    force_new_emulator = True
                else:
                    # Need to recreate the automator since force_new_emulator is True
                    logger.info(f"Force new emulator requested for {email}, cleaning up existing automator")
                    self.automators[email].cleanup()
                    self.automators[email] = None

        # Switch to the profile for this email - this will not stop other emulators
        success, message = self.profile_manager.switch_profile_and_start_emulator(
            email, force_new_emulator=force_new_emulator
        )
        if not success:
            logger.error(f"Failed to switch profile: {message}")
            return False, message

        # Clear current book since we're switching profiles
        self.clear_current_book(email)

        # Update activity timestamp
        self.update_activity(email)

        return True, message

    def unified_emulator_startup(
        self, email: str, force_new_emulator: bool = False, is_auto_restart: bool = False
    ) -> Tuple[bool, str]:
        """Unified emulator startup that ensures consistent behavior for both auto-restart and middleware paths.

        Args:
            email: The email address to start emulator for
            force_new_emulator: If True, always stop any emulator for this email and start a new one
            is_auto_restart: If True, indicates this is an auto-restart scenario (may need different timeouts)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        from server.logging_config import EmailContext
        from server.utils.port_utils import get_appium_port_for_email
        from server.utils.vnc_instance_manager import VNCInstanceManager

        with EmailContext(email):
            try:
                logger.info(f"Starting unified emulator setup for {email} (auto_restart={is_auto_restart})")

                # Check if Appium is needed for this email
                vnc_manager = VNCInstanceManager.get_instance()

                # Check if profile exists
                profile = self.profile_manager.get_profile_for_email(email)
                if not profile or not profile.get("avd_name"):
                    logger.error(f"No AVD profile found for {email}")
                    return False, f"No AVD profile found for {email}"

                avd_name = profile.get("avd_name")

                # First ensure Appium is running for this email
                if email not in self.appium_processes:
                    port = get_appium_port_for_email(
                        email, vnc_manager=vnc_manager, profiles_index=self.profile_manager.profiles_index
                    )
                    appium_started = self.start_appium(port=port, email=email)
                    if not appium_started:
                        logger.error(f"Failed to start Appium server for {email}")
                        return False, f"Failed to start Appium server for {email}"

                    # Give Appium a moment to fully initialize
                    time.sleep(2)

                logger.info(f"Appium server ready for {email}")

                # Set up the profile context with proper VNC settings before launching
                # This is critical for window cropping during auto-restart
                vnc_instance = vnc_manager.get_instance_for_email(email)
                if not vnc_instance:
                    vnc_instance = vnc_manager.assign_instance_to_email(email)
                    if vnc_instance:
                        logger.info(f"Assigned VNC instance {vnc_instance} to {email}")

                # Call switch_profile to handle the actual emulator launch
                success, message = self.switch_profile(email, force_new_emulator=force_new_emulator)

                if success:
                    # Initialize the automator
                    automator = self.initialize_automator(email)
                    if automator and automator.initialize_driver():
                        logger.info(f"✓ Successfully started emulator for {email} via unified startup")
                        return True, "Emulator started successfully"
                    else:
                        logger.error(f"Failed to initialize driver for {email}")
                        return False, "Failed to initialize driver"
                else:
                    logger.error(f"Failed to start emulator for {email}: {message}")
                    return False, message

            except Exception as e:
                logger.error(f"Error in unified emulator startup for {email}: {e}")
                return False, str(e)

    def _check_appium_health(self, port: int, timeout: int = 5) -> bool:
        """Check if an Appium server is running and healthy on the given port.

        Args:
            port: Port number to check
            timeout: Request timeout in seconds

        Returns:
            bool: True if Appium is healthy, False otherwise
        """
        try:
            response = requests.get(f"http://127.0.0.1:{port}/status", timeout=timeout)
            # For Appium 2.x, the status endpoint returns different structure
            if response.status_code == 200:
                status_data = response.json()
                # Check if value.ready is true or if the response has a ready field
                if "value" in status_data and isinstance(status_data["value"], dict):
                    is_ready = status_data["value"].get("ready", False)
                    if is_ready:
                        logger.debug(f"Healthy Appium 2.x server found on port {port}")
                        return True
                # Legacy check for older versions or direct ready field
                if status_data.get("ready"):
                    logger.debug(f"Appium server is ready on port {port}")
                    return True
                logger.debug(f"Appium server on port {port} is not ready yet: {status_data}")
                return False
            else:
                logger.debug(f"Appium server on port {port} returned status code: {response.status_code}")
                return False
        except requests.RequestException as e:
            logger.debug(f"Failed to connect to Appium server on port {port}: {e}")
            return False

    def start_appium(self, port: int = 4723, email: Optional[str] = None) -> bool:
        """Start an Appium server instance on the specified port.

        Args:
            port: Port to start Appium on. Default 4723.
            email: Optional email to associate with this Appium instance.

        Returns:
            bool: True if Appium started successfully, False otherwise
        """
        # Check if Appium is already running on this port
        if self._check_appium_health(port):
            # Check if we already have this tracked
            if email and email not in self.appium_processes:
                logger.info(f"Reusing existing Appium server on port {port} for {email}")
                self.appium_processes[email] = {
                    "port": port,
                    "process": None,  # We don't have the process object for pre-existing servers
                    "email": email,
                }
            elif not email:
                logger.info(f"Appium server already running on port {port}")
            return True

        # Additional ports needed by Appium
        from server.utils.port_utils import calculate_appium_bootstrap_port

        bootstrap_port = calculate_appium_bootstrap_port(port)
        chromedriver_port = bootstrap_port + 4515  # Fixed offset from bootstrap port
        mjpeg_server_port = bootstrap_port + 2810  # Fixed offset for MJPEG server

        # Ensure any existing process on this port is stopped
        if email and email in self.appium_processes:
            old_port = self.appium_processes[email].get("port")
            if old_port and old_port != port:
                logger.info(f"Stopping previous Appium instance on port {old_port} for {email}")
                self.stop_appium(port=old_port, email=email)

        # Stop any orphaned process on the target port
        self.stop_appium(port=port)

        logger.info(f"Starting Appium server for {email} on port {port}")

        # Build Appium command
        appium_cmd = [
            "appium",
            "--address",
            "127.0.0.1",
            "--port",
            str(port),
            "--base-path",
            "/",
            "--log-level",
            "error",
            "--log-no-colors",
            "--session-override",
            "--suppress-adb-kill-server",
            "--allow-insecure",
            "adb_shell",
            "--relaxed-security",
            "--default-capabilities",
            (
                f'{{"appium:systemPort": 8200, "appium:bootstrapPort": {bootstrap_port}, '
                f'"appium:chromedriverPort": {chromedriver_port}, "appium:mjpegServerPort": {mjpeg_server_port}}}'
            ),
        ]

        # Add log file path for email-specific instances
        if email:
            log_file = f"/tmp/appium-{email.replace('@', '_').replace('.', '_')}.log"
            appium_cmd.extend(["--log", log_file])

        try:
            # Start the process
            env = os.environ.copy()
            env["ANDROID_HOME"] = self.android_home
            process = subprocess.Popen(appium_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Wait for Appium to be ready with progressive backoff
            max_wait = 30
            check_interval = 0.5
            waited = 0

            while waited < max_wait:
                if self._check_appium_health(port):
                    logger.info(f"Appium server successfully started and responsive on port {port}")
                    # Track the process if we have an email
                    if email:
                        self.appium_processes[email] = {"port": port, "process": process, "email": email}
                    return True

                # Check if process died
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    logger.error(f"Appium process died unexpectedly. Exit code: {process.returncode}")
                    if stdout:
                        logger.error(f"Stdout: {stdout.decode('utf-8', errors='ignore')}")
                    if stderr:
                        logger.error(f"Stderr: {stderr.decode('utf-8', errors='ignore')}")
                    return False

                time.sleep(check_interval)
                waited += check_interval

                # Log progress every 5 seconds
                if int(waited) % 5 == 0:
                    logger.info(
                        f"Still waiting for Appium to start on port {port}... ({waited}s/{max_wait}s)"
                    )

            # Timeout reached
            process.terminate()
            process.wait()
            logger.error(f"Appium failed to start on port {port} within {max_wait} seconds")
            return False

        except Exception as e:
            logger.error(f"Failed to start Appium: {e}")
            return False

    def initialize_automator(self, email: str) -> Optional[Automator]:
        """Initialize automator instance for the given email.

        This method handles automator initialization with proper error handling
        and ensures state consistency across the automation server.

        Args:
            email: Email address to initialize automator for

        Returns:
            Automator instance if successful, None otherwise
        """
        try:
            logger.info(f"Initializing automator for {email}")

            # Clean up any existing automator for this email
            if email in self.automators and self.automators[email]:
                logger.info(f"Cleaning up existing automator for {email}")
                self.automators[email].cleanup()
                self.automators[email] = None

            # Create new automator instance
            automator = Automator(specific_device_id=None)

            # Set emulator_manager from profile_manager
            if hasattr(self.profile_manager, "emulator_manager"):
                automator.emulator_manager = self.profile_manager.emulator_manager

            # Store the automator instance
            self.automators[email] = automator

            # Update activity timestamp
            self.update_activity(email)

            # Update recent profiles
            if email not in self.recent_profiles:
                self.recent_profiles.append(email)

            logger.info(f"Successfully initialized automator for {email}")
            return automator

        except Exception as e:
            logger.error(f"Failed to initialize automator for {email}: {e}")
            # Clean up on failure
            if email in self.automators:
                if self.automators[email]:
                    self.automators[email].cleanup()
                self.automators[email] = None
            return None

    def allocate_ports_for_email(self, email: str, device_id: Optional[str] = None) -> Dict[str, int]:
        """Allocate unique ports for an email and optional device ID combination.

        Args:
            email: The email to allocate ports for
            device_id: Optional device ID to create a unique allocation key

        Returns:
            Dict containing allocated port numbers
        """
        # Create a unique key based on email and device_id
        allocation_key = f"{email}:{device_id}" if device_id else email

        # Check if we already have allocated ports for this key
        if allocation_key in self.allocated_ports:
            logger.info(
                f"Reusing existing ports for {allocation_key}: {self.allocated_ports[allocation_key]}"
            )
            return self.allocated_ports[allocation_key]

        # Also check if we have ports allocated just for the email (backward compatibility)
        if email in self.allocated_ports and allocation_key != email:
            # Migrate the old allocation to the new key
            logger.info(f"Migrating port allocation from {email} to {allocation_key}")
            self.allocated_ports[allocation_key] = self.allocated_ports[email]
            return self.allocated_ports[allocation_key]

        # Find first available slot (up to 100 slots)
        for slot in range(100):
            # Calculate all ports for this slot
            base_offset = slot
            ports = {
                "slot": slot,
                "systemPort": 8200 + base_offset,
                "bootstrapPort": 5000 + base_offset,
                "chromedriverPort": 9515 + base_offset,
                "mjpegServerPort": 7810 + base_offset,
                "appiumPort": 4723 + base_offset,
            }

            # Check if any of these ports are already in use
            ports_in_use = False
            for existing_allocation in self.allocated_ports.values():
                for port_type, port_num in ports.items():
                    if port_type != "slot" and existing_allocation.get(port_type) == port_num:
                        ports_in_use = True
                        break
                if ports_in_use:
                    break

            if not ports_in_use:
                # Found free slot, allocate it
                self.allocated_ports[allocation_key] = ports
                logger.info(f"Allocated ports for {allocation_key}: {ports}")
                return ports

        # No free slots found
        logger.error("No free port slots available")
        return {}

    def check_port_conflicts(self, email: str, appium_port: int) -> Dict[str, int]:
        """Check if the requested Appium port conflicts with existing allocations.

        Args:
            email: The email to check
            appium_port: The Appium port being requested

        Returns:
            Dict containing existing allocation if there's a conflict, empty dict otherwise
        """
        for allocation_key, ports in self.allocated_ports.items():
            # Skip our own allocation
            if allocation_key.startswith(email):
                continue

            if ports.get("appiumPort") == appium_port:
                logger.warning(f"Port {appium_port} is already allocated to {allocation_key}")
                return ports

        return {}

    def get_or_create_automator(self, email: str) -> Optional[Automator]:
        """Get existing automator or create a new one for the email.

        Args:
            email: Email to get/create automator for

        Returns:
            Automator instance or None if creation fails
        """
        # Check if we already have an automator for this email
        if email in self.automators and self.automators[email]:
            logger.info(f"Found existing automator for {email}")
            automator = self.automators[email]

            # Verify the driver is still valid
            if hasattr(automator, "driver") and automator.driver:
                try:
                    # Quick health check - try to get current activity
                    automator.driver.current_activity
                    return automator
                except Exception as e:
                    logger.warning(f"Existing driver for {email} appears to be dead: {e}")
                    # Fall through to create a new one

        # Create a new automator
        logger.info(f"Creating new automator for {email}")
        return self.initialize_automator(email)

    def ensure_appium_running(self, email: str) -> bool:
        """Ensure Appium is running for the given email."""
        if email not in self.appium_processes:
            from server.utils.port_utils import get_appium_port_for_email
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            port = get_appium_port_for_email(
                email, vnc_manager=vnc_manager, profiles_index=self.profile_manager.profiles_index
            )

            if not self.start_appium(port=port, email=email):
                logger.error(f"Failed to start Appium server on port {port} for {email}")
                return False

        return True

    def release_ports_for_email(self, email: str):
        """Release allocated ports for an email.

        Args:
            email: The email to release ports for
        """
        # Try to release with device ID first
        device_id = None
        if hasattr(self, "profile_manager"):
            profile = self.profile_manager.get_profile_for_email(email)
            if profile:
                device_id = profile.get("emulator_id")

        allocation_key = f"{email}:{device_id}" if device_id else email

        # Try to release with the key that includes device ID
        if allocation_key in self.allocated_ports:
            logger.info(
                f"Releasing allocated ports for {allocation_key}: {self.allocated_ports[allocation_key]}"
            )
            del self.allocated_ports[allocation_key]
        # Also try with just email for backward compatibility
        elif email in self.allocated_ports:
            logger.info(f"Releasing allocated ports for {email}: {self.allocated_ports[email]}")
            del self.allocated_ports[email]

        # Also clean up appium_processes if the instance is no longer running
        if email in self.appium_processes:
            appium_info = self.appium_processes[email]
            port = appium_info.get("port")

            # Check if the process is still running
            if port and not self._check_appium_health(port):
                logger.info(f"Removing dead appium process info for {email}")
                del self.appium_processes[email]

    def update_activity(self, email):
        """Update the last activity timestamp for an email.

        Args:
            email: The email address to update activity for
        """
        if email:
            self.last_activity[email] = time.time()
            logger.debug(f"Updated activity timestamp for {email}")

    def get_last_activity_time(self, email):
        """Get the last activity timestamp for an email.

        Args:
            email: The email address to get activity time for

        Returns:
            The last activity timestamp or None if not found
        """
        return self.last_activity.get(email)

    def clear_activity(self, email):
        """Clear the activity tracking for an email.

        Args:
            email: The email address to clear activity for
        """
        if email in self.last_activity:
            del self.last_activity[email]
            logger.debug(f"Cleared activity tracking for {email}")
