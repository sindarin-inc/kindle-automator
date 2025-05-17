"""Automation server core module for managing emulators and automators."""

import logging
import os
import platform
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from automator import KindleAutomator
from views.core.app_state import AppState
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class AutomationServer:
    def __init__(self):
        self.automators = {}  # Dictionary to track multiple automators by email
        self.appium_process = None
        self.appium_processes = {}  # Dictionary to track appium instances by email
        self.allocated_ports = {}  # Track allocated ports to prevent conflicts
        self.pid_dir = "logs"
        self.current_books = {}  # Track the currently open book title for each email
        self.last_activity = {}  # Track last activity time for each email
        os.makedirs(self.pid_dir, exist_ok=True)

        # Initialize the AVD profile manager
        self.android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        self.profile_manager = AVDProfileManager(base_dir=self.android_home)

    # automator property has been removed - use get_automator(email) instead

    def get_automator(self, email):
        """Get automator for a specific email.

        Args:
            email: The email address to get the automator for

        Returns:
            The automator instance for the given email, or None if not found
        """
        if not email:
            logger.warning("Attempted to get automator with empty email")
            return None

        return self.automators.get(email)

    def get_or_create_automator(self, email):
        """Get existing automator or create a new one for the given email.

        Args:
            email: The email address to get or create automator for

        Returns:
            The automator instance or None if creation failed
        """
        if not email:
            logger.error("Email parameter is required for get_or_create_automator")
            return None

        # Check if we already have an automator
        existing = self.get_automator(email)
        if existing:
            return existing

        # Create a new one
        return self.initialize_automator(email)

    def start_emulator(self, email):
        """Start an emulator for the given email address.

        Args:
            email: The email address to start emulator for

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        if not email:
            logger.error("Email parameter is required for start_emulator")
            return False

        from server.utils.request_utils import email_override

        try:
            # Use email override context to ensure proper email routing
            with email_override(email):
                # Initialize automator which will start the emulator
                automator = self.initialize_automator(email)
                
                if automator:
                    # The emulator should already be started by initialize_automator
                    # but we can verify it's running
                    return True
                else:
                    logger.error(f"Failed to initialize automator for {email}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error starting emulator for {email}: {e}")
            return False

    def initialize_automator(self, email):
        """Initialize automator for VNC-based manual authentication.

        Args:
            email: The profile ID for which to initialize an automator. REQUIRED.

        Returns:
            The automator instance or None if no email provided
        """
        if not email:
            logger.error("Email parameter is required for initialize_automator")
            return None

        # Check if we already have an automator for this profile
        if email in self.automators and self.automators[email]:
            logger.info(f"Using existing automator for profile {email}")
            return self.automators[email]

        # Set email context for this thread so logs go to the right file
        from server.logging_config import EmailContext

        with EmailContext(email):
            # Initialize a new automator
            automator = KindleAutomator()
            # Connect profile manager to automator for device ID tracking
            automator.profile_manager = self.profile_manager

            # Pass emulator_manager to automator for VNC integration
            automator.emulator_manager = self.profile_manager.emulator_manager

            # Store the automator
            self.automators[email] = automator
            # Set initial activity time
            self.update_activity(email)

            automator.initialize_driver()

        return automator

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

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        # For appium processes, save in the appium_logs directory
        if name.startswith("appium"):
            pid_dir = os.path.join(self.pid_dir, "appium_logs")
            os.makedirs(pid_dir, exist_ok=True)
        else:
            pid_dir = self.pid_dir

        pid_file = os.path.join(pid_dir, f"{name}.pid")
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
            # Set file permissions to be readable by all
            os.chmod(pid_file, 0o644)
        except Exception as e:
            logger.error(f"Error saving PID file: {e}")

    def kill_existing_process(self, name: str):
        """Kill existing process if running on port 4098"""
        try:
            if name == "flask":
                # Use lsof to find process on port 4098
                pid = subprocess.check_output(["lsof", "-t", "-i:4098"]).decode().strip()
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    logger.info(f"Killed existing flask process with PID {pid}")
            elif name == "appium":
                subprocess.run(["pkill", "-f", "appium"], check=False)
                logger.info("Killed existing appium processes")
        except subprocess.CalledProcessError:
            logger.info(f"No existing {name} process found")
        except Exception as e:
            logger.error(f"Error killing {name} process: {e}")

    def _check_appium_health(self, port):
        """Check if Appium server is healthy on the specified port.

        Args:
            port: The port to check

        Returns:
            bool: True if Appium is running and healthy, False otherwise
        """
        try:
            # Check if anything is listening on the port
            port_check = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, check=False
            )
            if not port_check.stdout.strip():
                logger.debug(f"No process found listening on port {port}")
                return False

            # Check Appium server status endpoint
            check_result = subprocess.run(
                ["curl", "-s", f"http://localhost:{port}/status"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )

            if check_result.returncode != 0:
                logger.debug(f"Appium health check failed with return code {check_result.returncode}")
                return False

            # Parse the response
            import json

            try:
                response_json = json.loads(check_result.stdout)

                # Check for Appium 1.x format: {"status": 0, ...}
                if "status" in response_json and response_json["status"] == 0:
                    logger.debug(f"Healthy Appium 1.x server found on port {port}")
                    return True

                # Check for Appium 2.x format: {"value": {"ready": true, ...}}
                if "value" in response_json and isinstance(response_json["value"], dict):
                    if response_json["value"].get("ready") == True:
                        logger.debug(f"Healthy Appium 2.x server found on port {port}")
                        return True

                logger.debug(f"Appium server on port {port} returned unknown format: {response_json}")

            except json.JSONDecodeError:
                # Not valid JSON, fallback to string check
                if '"status":0' in check_result.stdout or '"ready":true' in check_result.stdout:
                    logger.debug(f"Healthy Appium server found on port {port} (string check)")
                    return True
                else:
                    logger.debug(f"Invalid JSON response from Appium on port {port}: {check_result.stdout}")

        except Exception as e:
            logger.debug(f"Error checking Appium health on port {port}: {e}")

        return False

    def get_unique_ports_for_email(self, email):
        """Get unique port numbers for an email, ensuring no conflicts.

        This method now includes device ID to ensure different devices get different ports.

        Args:
            email: The email to get ports for

        Returns:
            dict: A dictionary of port assignments
        """
        # Get the current device ID for this email from the profile
        device_id = None
        if hasattr(self, "profile_manager"):
            profile = self.profile_manager.get_profile_for_email(email)
            if profile:
                device_id = profile.get("emulator_id")

        # Create a unique key combining email and device
        allocation_key = f"{email}:{device_id}" if device_id else email

        # Check if we already have ports allocated for this email+device combination
        if allocation_key in self.allocated_ports:
            logger.info(f"Reusing existing ports for {allocation_key}")
            return self.allocated_ports[allocation_key]

        # Find the next available slot
        base_system_port = 8200
        base_bootstrap_port = 5000
        base_chromedriver_port = 9515
        base_mjpeg_port = 7810
        base_appium_port = 4723

        # Check existing allocations and find a free slot
        used_slots = set()
        for allocated in self.allocated_ports.values():
            slot = allocated.get("slot", 0)
            used_slots.add(slot)

        # Find the first available slot
        slot = 0
        while slot in used_slots:
            slot += 1

        # Allocate ports
        ports = {
            "slot": slot,
            "systemPort": base_system_port + slot,
            "bootstrapPort": base_bootstrap_port + slot,
            "chromedriverPort": base_chromedriver_port + slot,
            "mjpegServerPort": base_mjpeg_port + slot,
            "appiumPort": base_appium_port + slot,
        }

        self.allocated_ports[allocation_key] = ports
        logger.info(f"Allocated ports for {allocation_key}: {ports}")
        return ports

    def start_appium(self, port=4723, email=None):
        """Start Appium server for a specific profile on a specific port.

        Args:
            port: The port to start Appium on (default: 4723)
            email: The email address for which this Appium instance is being started
                   If provided, this will be used to track the Appium instance

        Returns:
            bool: True if Appium server started successfully, False otherwise
        """
        # If email is provided, get the allocated port for this email
        if email:
            ports = self.get_unique_ports_for_email(email)
            port = ports["appiumPort"]
            logger.info(f"Using allocated port {port} for {email}")

        # Generate a unique name for the Appium process - either based on email or port
        process_name = f"appium_{email}" if email else f"appium_{port}"

        # First, check if Appium is already running on this port and is healthy
        if self._check_appium_health(port):
            logger.info(f"Healthy Appium server already running on port {port}, reusing it")

            # Get the PID of the existing process
            existing_pid = None
            try:
                pid_check = subprocess.run(
                    ["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, check=False
                )
                if pid_check.stdout.strip():
                    # lsof might return multiple PIDs; take the first one
                    pids = pid_check.stdout.strip().split("\n")
                    existing_pid = int(pids[0])
                    logger.debug(
                        f"Found existing Appium process with PID {existing_pid} (total PIDs: {len(pids)})"
                    )
            except Exception as e:
                logger.warning(f"Could not get PID of existing Appium process: {e}")

            # Store the process reference if we have an email
            if email:
                # Update our tracking with the existing process
                self.appium_processes[email] = {
                    "process": None,  # We don't have the process object, but it's running
                    "port": port,
                    "pid": existing_pid,
                }

            return True

        # If Appium isn't healthy or not running, then kill any existing process on this port
        try:
            # Try to find and kill any process using this port
            port_check = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, check=False
            )
            if port_check.stdout.strip():
                pid = port_check.stdout.strip()
                logger.info(f"Killing unhealthy/stale process with PID {pid} on port {port}")
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)  # Give it time to terminate
                except Exception as kill_e:
                    logger.warning(f"Error killing process on port {port}: {kill_e}")
        except Exception as e:
            logger.warning(f"Error checking for processes on port {port}: {e}")

        # Also try killing by name pattern
        self.kill_existing_process(process_name)

        try:
            # Start Appium on the specified port
            logger.info(f"Starting Appium server for {email if email else 'default'} on port {port}")

            # Path for log files
            logs_dir = os.path.join(self.pid_dir, "appium_logs")
            os.makedirs(logs_dir, exist_ok=True)
            log_file = os.path.join(logs_dir, f"{process_name}.log")

            # Start Appium with the specific port
            # Find the appium executable - first check common locations
            appium_paths = [
                "appium",  # Try PATH first
                "/opt/homebrew/bin/appium",  # Common macOS Homebrew location
                "/usr/local/bin/appium",  # Common Linux/macOS location
                "/usr/bin/appium",  # Common Linux location
                os.path.expanduser("~/.nvm/versions/node/*/bin/appium"),  # NVM install
                os.path.expanduser("~/.npm-global/bin/appium"),  # NPM global
            ]

            # Try each potential path
            appium_cmd = None
            for path in appium_paths:
                # If path contains a wildcard, try to expand it
                if "*" in path:
                    import glob

                    matching_paths = glob.glob(path)
                    # Sort by version (assuming newer is better)
                    matching_paths.sort(reverse=True)
                    if matching_paths:
                        path = matching_paths[0]

                # Check if the path exists and is executable
                if path != "appium":  # Skip PATH check
                    if not os.path.exists(path) or not os.access(path, os.X_OK):
                        continue

                # Try to run the command to verify it works
                try:
                    version_check = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, check=False, timeout=2
                    )
                    if version_check.returncode == 0:
                        appium_cmd = path
                        break
                except (subprocess.SubprocessError, OSError):
                    continue

            # If we didn't find Appium, try PATH as a last resort
            if not appium_cmd:
                appium_cmd = "appium"
                logger.warning(f"Could not find Appium in standard locations, falling back to PATH")

            # Add environment variables to ensure proper Node.js execution
            env = os.environ.copy()

            # Ensure these paths are in PATH if they exist
            for bin_path in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
                if os.path.exists(bin_path) and bin_path not in env.get("PATH", ""):
                    env["PATH"] = f"{bin_path}:{env.get('PATH', '')}"

            # Start Appium with more detailed logs
            with open(log_file, "w") as log:
                appium_process = subprocess.Popen(
                    [
                        appium_cmd,
                        "--port",
                        str(port),
                        "--log-level",
                        "info",
                    ],
                    stdout=log,
                    stderr=log,
                    text=True,
                    env=env,
                )

            # Save the PID
            self.save_pid(process_name, appium_process.pid)

            # Store the process in either the global appium_process or in the per-email dictionary
            if email:
                # Create a dictionary to track per-email Appium processes if it doesn't exist
                if not hasattr(self, "appium_processes"):
                    self.appium_processes = {}

                # Store the process and port information
                self.appium_processes[email] = {
                    "process": appium_process,
                    "port": port,
                    "pid": appium_process.pid,
                }
            else:
                # Fall back to the global appium_process for backward compatibility
                self.appium_process = appium_process

            # Wait briefly for Appium to start up
            time.sleep(2)

            # Verify Appium is running on this port - try multiple times with increasing delays
            max_retries = 3
            retry_delay = 1  # Start with 1 second, will increase

            for attempt in range(max_retries):
                if self._check_appium_health(port):
                    logger.info(f"Appium server successfully started and responsive on port {port}")
                    return True

                # If this is the last attempt, don't continue
                if attempt == max_retries - 1:
                    logger.error(f"Appium server failed to respond correctly after {max_retries} attempts")

                    # Kill the process since it's not working properly
                    if email and email in self.appium_processes:
                        try:
                            process = self.appium_processes[email].get("process")
                            if process:
                                process.terminate()
                                logger.info(f"Terminated non-responsive Appium process for {email}")
                        except Exception as term_e:
                            logger.warning(f"Error terminating non-responsive Appium process: {term_e}")

                    return False

                # Wait before trying again
                logger.info(f"Waiting {retry_delay}s before checking Appium server again...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

            # Should never reach here due to returns in the loop
            return False

        except Exception as e:
            logger.error(f"Failed to start Appium server on port {port}: {e}")
            return False

    def set_current_book(self, book_title, email):
        """Set the currently open book title for a specific email

        Args:
            book_title: The title of the book
            email: The email to associate with this book. REQUIRED.
        """
        if not email:
            logger.error("Email parameter is required for set_current_book")
            return

        self.current_books[email] = book_title
        logger.info(f"Set current book for {email} to: {book_title}")

    def clear_current_book(self, email):
        """Clear the currently open book tracking variable for a specific email

        Args:
            email: The email for which to clear the book. REQUIRED.
        """
        if not email:
            logger.error("Email parameter is required for clear_current_book")
            return

        if email in self.current_books:
            logger.info(f"Cleared current book for {email}: {self.current_books[email]}")
            del self.current_books[email]

    def get_current_book(self, email):
        """Get the current book for the specified email.

        Args:
            email: The email to get the current book for. REQUIRED.

        Returns:
            str: The title of the current book, or None if no book is open
        """
        if not email:
            logger.error("Email parameter is required for get_current_book")
            return None

        return self.current_books.get(email)

    # current_book property has been removed - use get_current_book(email) instead

    def release_allocated_ports(self, email):
        """Release allocated ports for an email when they're no longer needed.

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
