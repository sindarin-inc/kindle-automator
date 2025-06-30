"""
Appium driver management and control utilities.

This module handles all Appium-related functionality including:
- Starting/stopping Appium processes
- Health checking Appium servers
- Port allocation and management
- Process tracking
"""

import json
import logging
import os
import platform
import signal
import subprocess
import time
from typing import Dict, Optional

from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)


class AppiumDriver:
    """
    Manages Appium server instances for multiple profiles.
    Works in conjunction with VNCInstanceManager to provide centralized
    instance management.

    This is a singleton class - use AppiumDriver.get_instance() to access it.
    """

    _instance = None

    def __new__(cls):
        """Enforce singleton pattern."""
        if cls._instance is None:
            cls._instance = super(AppiumDriver, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the Appium driver manager."""
        if self._initialized:
            return
        self.vnc_manager = VNCInstanceManager.get_instance()
        self.pid_dir = "logs"
        os.makedirs(self.pid_dir, exist_ok=True)
        self._initialized = True

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of AppiumDriver."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_appium_for_profile(self, email: str) -> bool:
        """
        Start Appium server for a specific profile.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if Appium started successfully, False otherwise
        """
        # Get instance for this profile
        instance = self.vnc_manager.get_instance_for_profile(email)
        if not instance:
            logger.error(f"Could not start appium, no VNC instance found for profile {email}")
            return False

        # Check if already running - verify with actual health check
        if instance.get("appium_running", False):
            # Verify the process is actually healthy
            if self._check_appium_health(email):
                logger.info(f"Appium already running and healthy for {email}")
                return True
            else:
                logger.info(f"Appium marked as running but not healthy for {email}, restarting")
                instance["appium_running"] = False
                self.vnc_manager.save_instances()

        port = instance["appium_port"]
        process_name = f"appium_{email}"

        # First check if anything is already using this port
        if self._check_appium_health(email):
            logger.info(f"Healthy Appium server already on port {port}, marking as running")
            instance["appium_running"] = True
            self.vnc_manager.save_instances()
            return True

        # Kill any existing process on this port
        self._kill_process_on_port(port)

        # Kill any existing process by name
        self._kill_existing_process(process_name)

        # Start Appium
        try:
            # Create logs directory
            logs_dir = os.path.join(self.pid_dir, "appium_logs")
            os.makedirs(logs_dir, exist_ok=True)
            log_file = os.path.join(logs_dir, f"{process_name}.log")

            # Find appium executable
            appium_cmd = self._find_appium_executable()

            # Start Appium with all necessary ports
            env = os.environ.copy()
            # Ensure proper PATH for macOS
            if platform.system() == "Darwin":
                for bin_path in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
                    if os.path.exists(bin_path) and bin_path not in env.get("PATH", ""):
                        env["PATH"] = f"{bin_path}:{env.get('PATH', '')}"

            # No need to pass additional ports via command line
            # These ports are configured via appium:capabilities in the client

            # Configure Appium server to keep sessions alive for 30 minutes (1800 seconds)
            cmd = [
                appium_cmd,
                "--port",
                str(port),
                "--log-level",
                "info",
                "--session-override",  # Allow overriding stale sessions
                "--relaxed-security",  # Allow more flexible session management
            ]

            with open(log_file, "w") as log:
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=log,
                    text=True,
                    env=env,
                )
                logger.info(f"Appium process started on port {port} with PID: {process.pid}")

            # Save PID
            self._save_pid(process_name, process.pid)

            # Update instance with process info
            instance["appium_pid"] = process.pid
            instance["appium_running"] = True
            instance["appium_last_health_check"] = time.time()
            self.vnc_manager.save_instances()

            # Keep process reference in memory only (not serialized)
            self._runtime_processes = getattr(self, "_runtime_processes", {})
            self._runtime_processes[email] = process

            # Wait for Appium to start with retries
            max_retries = 3
            retry_delay = 1

            for attempt in range(max_retries):
                if self._check_appium_health(email):
                    logger.info(f"Appium started successfully on port {port} for {email}")
                    return True

                if attempt < max_retries - 1:
                    logger.info(f"Waiting {retry_delay}s before checking Appium again...")
                    time.sleep(retry_delay)
                    retry_delay *= 2

            # Failed after all retries
            logger.error(f"Appium failed to start correctly on port {port}")
            self.stop_appium_for_profile(email)
            return False

        except Exception as e:
            logger.error(f"Error starting Appium for {email}: {e}", exc_info=True)
            return False

    def stop_appium_for_profile(self, email: str) -> bool:
        """
        Stop Appium server for a specific profile.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if stopped successfully, False otherwise
        """
        instance = self.vnc_manager.get_instance_for_profile(email)
        if not instance:
            logger.warning(f"No instance found for profile {email}")
            return False

        # Try to stop the process gracefully
        if instance.get("appium_pid"):
            try:
                os.kill(instance["appium_pid"], signal.SIGTERM)
                time.sleep(1)
                # Force kill if still running
                try:
                    os.kill(instance["appium_pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except Exception as e:
                logger.warning(f"Error stopping Appium process: {e}")

        # Remove from runtime processes
        runtime_processes = getattr(self, "_runtime_processes", {})
        if email in runtime_processes:
            del runtime_processes[email]

        # Clear process info
        instance["appium_pid"] = None
        instance["appium_running"] = False
        self.vnc_manager.save_instances()

        return True

    def _check_appium_health(self, email: str) -> bool:
        """
        Check if Appium server is healthy for a profile.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if healthy, False otherwise
        """
        instance = self.vnc_manager.get_instance_for_profile(email)
        if not instance:
            return False

        port = instance["appium_port"]

        try:
            # Check if anything is listening on the port first
            port_check = subprocess.run(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, check=False
            )
            if not port_check.stdout.strip():
                return False

            # Check Appium status endpoint
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

            # Parse response for both Appium 1.x and 2.x formats
            try:
                response = json.loads(check_result.stdout)

                # Appium 1.x: {"status": 0}
                if "status" in response and response["status"] == 0:
                    logger.debug(f"Healthy Appium 1.x server found on port {port}")
                    return True

                # Appium 2.x: {"value": {"ready": true}}
                if "value" in response and isinstance(response["value"], dict):
                    if response["value"].get("ready") == True:
                        logger.debug(f"Healthy Appium 2.x server found on port {port}")
                        return True

                logger.debug(f"Appium server on port {port} returned unknown format: {response}")

            except json.JSONDecodeError:
                # Fallback to string check
                if '"status":0' in check_result.stdout or '"ready":true' in check_result.stdout:
                    logger.debug(f"Healthy Appium server found on port {port} (string check)")
                    return True
                else:
                    logger.debug(f"Invalid JSON response from Appium on port {port}")

        except Exception as e:
            logger.debug(f"Error checking Appium health on port {port}: {e}")

        return False

    def get_appium_ports_for_profile(self, email: str) -> Optional[Dict]:
        """
        Get all Appium-related ports for a profile.

        Args:
            email: Email address of the profile

        Returns:
            Dict with all Appium ports or None if no instance
        """
        instance = self.vnc_manager.get_instance_for_profile(email)
        if not instance:
            return None

        return {
            "appiumPort": instance.get("appium_port"),
            "systemPort": instance.get("appium_system_port"),
            "chromedriverPort": instance.get("appium_chromedriver_port"),
            "mjpegServerPort": instance.get("appium_mjpeg_server_port"),
        }

    def get_appium_process_info(self, email: str) -> Optional[Dict]:
        """
        Get Appium process information for a profile.

        Args:
            email: Email address of the profile

        Returns:
            Dict with process info or None if not running
        """
        instance = self.vnc_manager.get_instance_for_profile(email)
        if not instance or not instance.get("appium_running"):
            return None

        return {
            "pid": instance.get("appium_pid"),
            "port": instance.get("appium_port"),
            "running": instance.get("appium_running", False),
            "last_health_check": instance.get("appium_last_health_check"),
        }

    def _find_appium_executable(self) -> str:
        """
        Find the Appium executable path.

        Returns:
            str: Path to Appium executable
        """
        appium_paths = [
            "appium",  # Try PATH first
            "/opt/homebrew/bin/appium",  # Common macOS Homebrew location
            "/usr/local/bin/appium",  # Common Linux/macOS location
            "/usr/bin/appium",  # Common Linux location
            "/usr/local/lib/node_modules/.bin/appium",  # npm bin symlink
            os.path.expanduser("~/.nvm/versions/node/*/bin/appium"),  # NVM install
            os.path.expanduser("~/.npm-global/bin/appium"),  # NPM global
        ]

        for path in appium_paths:
            # Handle wildcards
            if "*" in path:
                import glob

                matching_paths = glob.glob(path)
                matching_paths.sort(reverse=True)  # Prefer newer versions
                if matching_paths:
                    path = matching_paths[0]

            # Skip PATH check for now
            if path != "appium":
                exists = os.path.exists(path)
                executable = os.access(path, os.X_OK) if exists else False
                logger.debug(f"Checking path {path}: exists={exists}, executable={executable}")
                if not exists or not executable:
                    continue

            # Try to verify it works
            try:
                version_check = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, check=False, timeout=2
                )
                if version_check.returncode == 0:
                    return path
            except (subprocess.SubprocessError, OSError) as e:
                logger.debug(f"Error checking {path}: {e}")
                continue

        # Fallback to PATH
        logger.warning("Could not find Appium in standard locations, falling back to PATH")
        return "appium"

    def _save_pid(self, name: str, pid: int):
        """Save process ID to file."""
        pid_dir = os.path.join(self.pid_dir, "appium_logs")
        os.makedirs(pid_dir, exist_ok=True)

        pid_file = os.path.join(pid_dir, f"{name}.pid")
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
            os.chmod(pid_file, 0o644)
        except Exception as e:
            logger.error(f"Error saving PID file: {e}")

    def _kill_existing_process(self, name: str):
        """Kill existing process by PID file."""
        pid_dir = os.path.join(self.pid_dir, "appium_logs")
        pid_file = os.path.join(pid_dir, f"{name}.pid")

        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                # Force kill if still alive
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                # Remove the PID file
                os.remove(pid_file)
                logger.info(f"Killed existing {name} process using PID {pid}")
            except Exception as e:
                logger.error(f"Error killing {name} process by PID: {e}")
        else:
            logger.debug(f"No PID file found for {name}")

    def _kill_process_on_port(self, port: int):
        """Kill any process using the specified port."""
        try:
            port_check = subprocess.run(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, check=False
            )
            if port_check.stdout.strip():
                pids = port_check.stdout.strip().split("\n")
                for pid in pids:
                    logger.info(f"Killing process {pid} on port {port}")
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        time.sleep(0.5)
                        # Force kill if still alive
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    except Exception as e:
                        logger.warning(f"Error killing process {pid}: {e}")
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Error checking for processes on port {port}: {e}")
