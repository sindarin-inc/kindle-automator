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
        self.pid_dir = "logs"
        self.current_books = {}  # Track the currently open book title for each email
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

        # Initialize a new automator
        automator = KindleAutomator()
        # Connect profile manager to automator for device ID tracking
        automator.profile_manager = self.profile_manager

        # Pass emulator_manager to automator for VNC integration
        automator.emulator_manager = self.profile_manager.emulator_manager

        # Store the automator
        self.automators[email] = automator
        logger.info(f"Initialized automator for {email}: {automator}/{automator.driver}")

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

        logger.info(f"Switching to profile for email: {email}, force_new_emulator={force_new_emulator}")

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

        return True, message

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        pid_file = os.path.join(self.pid_dir, f"{name}.pid")
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

    def start_appium(self, port=4723, email=None):
        """Start Appium server for a specific profile on a specific port.

        Args:
            port: The port to start Appium on (default: 4723)
            email: The email address for which this Appium instance is being started
                   If provided, this will be used to track the Appium instance

        Returns:
            bool: True if Appium server started successfully, False otherwise
        """
        # Generate a unique name for the Appium process - either based on email or port
        process_name = f"appium_{email}" if email else f"appium_{port}"

        # Kill any existing Appium process with this name or on this port
        try:
            # Try to find and kill any process using this port
            port_check = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, check=False
            )
            if port_check.stdout.strip():
                pid = port_check.stdout.strip()
                logger.info(f"Killing existing process with PID {pid} on port {port}")
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

            # Start Appium with the specific port and base path set to /wd/hub
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
                    [appium_cmd, "--port", str(port), "--base-path", "/wd/hub", "--log-level", "debug"],
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
                try:
                    check_result = subprocess.run(
                        ["curl", "-s", f"http://localhost:{port}/wd/hub/status"],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=5,
                    )

                    # Appium 2.x returns a different format than Appium 1.x
                    # Check for both response formats

                    # Try to parse the response as JSON
                    import json

                    try:
                        response_json = json.loads(check_result.stdout)

                        # Check for Appium 1.x format: {"status": 0, ...}
                        if "status" in response_json and response_json["status"] == 0:
                            logger.info(
                                f"Appium 1.x server successfully started and responsive on port {port}"
                            )
                            return True

                        # Check for Appium 2.x format: {"value": {"ready": true, ...}}
                        if "value" in response_json and isinstance(response_json["value"], dict):
                            if response_json["value"].get("ready") == True:
                                return True

                        # If we get here, the response is in an unknown format
                        logger.warning(
                            f"Appium server started but returned unknown format on port {port} (attempt {attempt+1}/{max_retries}): {check_result.stdout}"
                        )
                    except json.JSONDecodeError:
                        # Not valid JSON, fallback to string check
                        if '"status":0' in check_result.stdout or '"ready":true' in check_result.stdout:
                            logger.info(
                                f"Appium server successfully started and responsive on port {port} (string check)"
                            )
                            return True
                        else:
                            logger.warning(
                                f"Appium server started but returned invalid JSON on port {port} (attempt {attempt+1}/{max_retries}): {check_result.stdout}"
                            )

                    # If this is the last attempt, don't continue
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Appium server failed to respond correctly after {max_retries} attempts"
                        )

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

                        # Wait with increasing delay before trying again
                        logger.info(f"Waiting {retry_delay}s before checking Appium server again...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff

                except Exception as check_e:
                    logger.warning(
                        f"Error checking Appium server status (attempt {attempt+1}/{max_retries}): {check_e}"
                    )

                    # If this is the last attempt, don't continue
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to verify Appium server status after {max_retries} attempts")
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
