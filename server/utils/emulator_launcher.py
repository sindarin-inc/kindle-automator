"""
Emulator launcher module that handles the coordination between 
VNC servers, emulators, and the X display numbers.
"""

import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Directory for storing VNC instance mapping directly with user profiles
# Use the same directory as user profiles ($ANDROID_HOME/profiles)
USER_PROFILES_DIR = None  # Will be set at runtime based on android_home


class EmulatorLauncher:
    """
    Manages the lifecycle and coordination of emulators with VNC displays.
    This class replaces the shell script-based approach with a pure Python implementation.
    """

    def __init__(self, android_home: str, avd_dir: str, host_arch: str):
        """
        Initialize the emulator launcher.

        Args:
            android_home: Path to the Android SDK directory
            avd_dir: Path to the AVD directory
            host_arch: Host architecture (e.g. 'arm64', 'x86_64')
        """
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.host_arch = host_arch

        # Set up profiles directory and VNC instance map path
        self.profiles_dir = os.path.join(android_home, "profiles")
        self.vnc_instance_map_path = os.path.join(self.profiles_dir, "vnc_instance_map.json")

        # Ensure profiles directory exists
        os.makedirs(self.profiles_dir, exist_ok=True)

        # Maps emails to (emulator_id, display_num) tuples
        self.running_emulators = {}

        # Load existing mapping if available
        self._load_vnc_instance_map()

    def _load_vnc_instance_map(self):
        """Load VNC instance mapping from JSON file."""
        try:
            if os.path.exists(self.vnc_instance_map_path):
                with open(self.vnc_instance_map_path, "r") as f:
                    self.vnc_instances = json.load(f)

                # Check if the existing instances have emulator_port - migrate if needed
                need_migration = False
                for instance in self.vnc_instances["instances"]:
                    if "emulator_port" not in instance:
                        need_migration = True
                        break

                if need_migration:
                    logger.info("Migrating VNC instance mapping to include emulator ports")
                    for i, instance in enumerate(self.vnc_instances["instances"]):
                        # Add emulator port (5554, 5556, 5558, etc.) - each uses 2 consecutive ports
                        instance["emulator_port"] = 5554 + (i * 2)
                    self._save_vnc_instance_map()

                logger.info(f"Loaded VNC instance mapping from {self.vnc_instance_map_path}")
            else:
                # Create default instances with unique emulator ports
                logger.info(f"Creating default VNC instance mapping at {self.vnc_instance_map_path}")
                self.vnc_instances = {
                    "instances": [
                        {
                            "id": i,
                            "display": i,
                            "vnc_port": 5900 + i,
                            "novnc_port": 6080 + i,
                            "emulator_port": 5554 + ((i - 1) * 2),  # 5554, 5556, 5558, etc.
                            "assigned_profile": None,
                        }
                        for i in range(1, 9)  # Create 8 default instances
                    ]
                }
                # Save to file
                self._save_vnc_instance_map()
        except Exception as e:
            logger.error(f"Error loading VNC instance mapping: {e}")
            # Create a default mapping
            self.vnc_instances = {"instances": []}

    def _save_vnc_instance_map(self):
        """Save VNC instance mapping to JSON file."""
        try:
            with open(self.vnc_instance_map_path, "w") as f:
                json.dump(self.vnc_instances, f, indent=2)
            logger.info(f"Saved VNC instance mapping to {self.vnc_instance_map_path}")
        except Exception as e:
            logger.error(f"Error saving VNC instance mapping: {e}")

    def get_x_display(self, email: str) -> Optional[int]:
        """
        Get the X display number for a profile.

        Args:
            email: The profile email

        Returns:
            The display number or None if not found
        """
        try:
            # First check running emulators
            if email in self.running_emulators:
                _, display_num = self.running_emulators[email]
                return display_num

            # Then check the VNC instance map
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    return instance["display"]

            # No display found
            return None
        except Exception as e:
            logger.error(f"Error getting X display for {email}: {e}")
            return None

    def get_emulator_port(self, email: str) -> Optional[int]:
        """
        Get the emulator port for a profile.

        Args:
            email: The profile email

        Returns:
            The emulator port or None if not found
        """
        try:
            # First check the VNC instance map
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    return instance["emulator_port"]

            # No port found
            return None
        except Exception as e:
            logger.error(f"Error getting emulator port for {email}: {e}")
            return None

    def get_emulator_id(self, email: str) -> Optional[str]:
        """
        Get the emulator ID for a profile.

        Args:
            email: The profile email

        Returns:
            The emulator ID (e.g. emulator-5554) or None if not found
        """
        # First check running emulators
        if email in self.running_emulators:
            emulator_id, _ = self.running_emulators[email]
            return emulator_id

        # Then try to build from port
        port = self.get_emulator_port(email)
        if port:
            return f"emulator-{port}"

        return None

    def assign_display_to_profile(self, email: str) -> Optional[int]:
        """
        Assign a display number to a profile.

        Args:
            email: The profile email

        Returns:
            The assigned display number or None if assignment failed
        """
        try:
            # First check if the profile already has an assigned display
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    logger.info(f"Profile {email} already assigned to display :{instance['display']}")
                    return instance["display"]

            # Find an available instance
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] is None:
                    # Assign this instance to the profile
                    instance["assigned_profile"] = email
                    self._save_vnc_instance_map()
                    logger.info(f"Assigned display :{instance['display']} to profile {email}")
                    return instance["display"]

            # No available instances, return None
            logger.error(f"No available displays for profile {email}")
            return None
        except Exception as e:
            logger.error(f"Error assigning display to profile {email}: {e}")
            return None

    @staticmethod
    def _extract_email_from_avd_name(avd_name: str) -> Optional[str]:
        """
        Extract email from AVD name using the format {platform}_{email}_{domain}.

        Args:
            avd_name: The AVD name to extract email from

        Returns:
            Extracted email or None if no email found
        """
        try:
            if not avd_name or "_" not in avd_name:
                return None

            parts = avd_name.split("_")
            if len(parts) < 3:
                return None

            # Handle emails with underscores or dots in username
            email_part = parts[1]
            domain_part = parts[2]

            # Replace underscores with dots if needed
            if "_" in email_part:
                email_part = email_part.replace("_", ".")

            return f"{email_part}@{domain_part}"
        except Exception as e:
            logger.error(f"Error extracting email from AVD name '{avd_name}': {e}")
            return None

    def _ensure_vnc_running(self, display_num: int) -> bool:
        """
        Ensure the VNC server is running for the specified display.

        Args:
            display_num: The X display number

        Returns:
            True if VNC is running, False otherwise
        """
        if platform.system() == "Darwin":
            # Skip VNC setup on macOS
            return True

        try:
            # Check if Xvfb is running for this display
            xvfb_check = subprocess.run(
                ["pgrep", "-f", f"Xvfb :{display_num}"], capture_output=True, text=True
            )

            if xvfb_check.returncode != 0:
                # Start Xvfb directly
                logger.info(f"Starting Xvfb for display :{display_num}")

                # Kill any existing Xvfb process for this display
                subprocess.run(["pkill", "-f", f"Xvfb :{display_num}"], check=False)
                # Clean up any lock files
                subprocess.run(
                    ["rm", "-f", f"/tmp/.X{display_num}-lock", f"/tmp/.X11-unix/X{display_num}"], check=False
                )

                # Start Xvfb with 1280x800 resolution
                xvfb_cmd = [
                    "/usr/bin/Xvfb",
                    f":{display_num}",
                    "-screen",
                    "0",
                    "1280x800x24",
                    "-ac",
                    "+extension",
                    "GLX",
                    "+render",
                    "-noreset",
                ]

                with open(f"/var/log/xvfb-{display_num}.log", "w") as f:
                    xvfb_process = subprocess.Popen(xvfb_cmd, stdout=f, stderr=f)

                time.sleep(2)

                # Verify Xvfb is running
                xvfb_check = subprocess.run(
                    ["pgrep", "-f", f"Xvfb :{display_num}"], capture_output=True, text=True
                )
                if xvfb_check.returncode != 0:
                    logger.error(f"Failed to start Xvfb for display :{display_num}")
                    return False
                else:
                    logger.info(f"Successfully started Xvfb for display :{display_num}")

            # Check if x11vnc is running for this display
            vnc_check = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*:{display_num}"], capture_output=True, text=True
            )

            if vnc_check.returncode != 0:
                # Start VNC directly
                logger.info(f"Starting VNC service for display :{display_num}")

                # Kill any existing VNC process for this display
                vnc_port = 5900 + display_num
                subprocess.run(["pkill", "-f", f"x11vnc.*rfbport {vnc_port}"], check=False)

                # Set up environment
                env = os.environ.copy()
                env["DISPLAY"] = f":{display_num}"

                # Start x11vnc
                vnc_cmd = [
                    "/usr/bin/x11vnc",
                    "-display",
                    f":{display_num}",
                    "-forever",
                    "-shared",
                    "-rfbport",
                    str(vnc_port),
                    "-rfbauth",
                    "/opt/keys/vnc.pass",  # VNC password file created by Ansible
                    "-cursor",
                    "arrow",
                    "-noxdamage",
                    "-noxfixes",
                    "-noipv6",
                    "-desktop",
                    f"VNC Server :{display_num}",
                    "-o",
                    f"/var/log/x11vnc-{display_num}.log",
                    "-bg",
                ]

                subprocess.run(vnc_cmd, env=env, check=False, timeout=5)
                time.sleep(2)

                # Verify VNC is running
                vnc_check = subprocess.run(
                    ["pgrep", "-f", f"x11vnc.*rfbport {vnc_port}"], capture_output=True, text=True
                )
                if vnc_check.returncode != 0:
                    logger.error(f"Failed to start VNC server for display :{display_num}")
                    return False
                else:
                    logger.info(f"Successfully started VNC server for display :{display_num}")

            return True

        except Exception as e:
            logger.error(f"Error ensuring VNC is running for display :{display_num}: {e}")
            return False

    def _restart_vnc_with_clipping(self, email: str, display_num: int) -> bool:
        """
        Restart the VNC server for the specified email and display with app window clipping.

        Args:
            email: The user's email address
            display_num: The X display number

        Returns:
            True if restart was successful, False otherwise
        """
        if platform.system() == "Darwin":
            # Skip VNC clipping on macOS
            return True

        try:
            # Get the VNC port for this display
            vnc_port = 5900 + display_num

            # Kill existing x11vnc process for this display
            subprocess.run(["pkill", "-f", f"x11vnc.*rfbport {vnc_port}"], check=False)
            time.sleep(1)

            # Set up the environment
            env = os.environ.copy()
            env["DISPLAY"] = f":{display_num}"

            # Try to get app window position for clipping
            try:
                app_finder = "/usr/local/bin/find-app-position.sh"
                if os.path.exists(app_finder) and os.access(app_finder, os.X_OK):
                    logger.info(f"Using app finder to determine clip region for display :{display_num}")
                    clip_result = subprocess.run(
                        [app_finder, f":{display_num}"], env=env, capture_output=True, text=True, check=False
                    )

                    clip_region = clip_result.stdout.strip()
                    # Verify it's a valid geometry
                    if clip_region and "x" in clip_region and "+" in clip_region:
                        logger.info(f"Using clip region: {clip_region}")
                    else:
                        # Default clipping for Kindle app (centered)
                        logger.info("Using default clip region (center of screen)")
                        x_pos = 400 - 360 // 2
                        y_pos = 300 - 640 // 2
                        clip_region = f"360x640+{x_pos}+{y_pos}"
                else:
                    # Default clipping for Kindle app (centered)
                    logger.info("App finder not available, using default clip region")
                    x_pos = 400 - 360 // 2
                    y_pos = 300 - 640 // 2
                    clip_region = f"360x640+{x_pos}+{y_pos}"
            except Exception as e:
                logger.error(f"Error getting clip region: {e}")
                # Default clipping for Kindle app (centered)
                x_pos = 400 - 360 // 2
                y_pos = 300 - 640 // 2
                clip_region = f"360x640+{x_pos}+{y_pos}"

            # Restart x11vnc with clipping
            vnc_process = subprocess.Popen(
                [
                    "/usr/bin/x11vnc",
                    "-display",
                    f":{display_num}",
                    "-forever",
                    "-shared",
                    "-rfbport",
                    str(vnc_port),
                    "-rfbauth",
                    "/opt/keys/vnc.pass",  # VNC password file created by Ansible
                    "-clip",
                    clip_region,
                    "-cursor",
                    "arrow",
                    "-noxdamage",
                    "-noxfixes",
                    "-noipv6",
                    "-desktop",
                    f"Kindle App ({email})",
                    "-o",
                    f"/var/log/x11vnc-{display_num}.log",
                    "-bg",
                ],
                env=env,
            )

            logger.info(f"Restarted VNC server for {email} on display :{display_num} with clipping")
            return True

        except Exception as e:
            logger.error(f"Error restarting VNC with clipping for {email} on display :{display_num}: {e}")
            return False

    def launch_emulator(self, avd_name: str, email: str = None) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Launch an emulator for the specified AVD and email, with proper VNC display coordination.

        Args:
            avd_name: The AVD name to launch
            email: The user's email address (optional, will be extracted from AVD name if not provided)

        Returns:
            Tuple of (success, emulator_id, display_num)
        """
        try:
            # Check if AVD exists
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            if not os.path.exists(avd_path):
                logger.error(f"AVD {avd_name} does not exist at {avd_path}")
                return False, None, None

            # Get or extract email
            if not email:
                email = self._extract_email_from_avd_name(avd_name)
                if not email:
                    logger.warning(f"Could not extract email from AVD name {avd_name}, using 'default'")
                    email = "default"

            # Check if emulator already running for this email
            if email in self.running_emulators:
                emulator_id, display_num = self.running_emulators[email]
                logger.info(f"Emulator already running for {email}: {emulator_id} on display :{display_num}")
                return True, emulator_id, display_num

            # Get assigned display and emulator port for this profile
            display_num = self.get_x_display(email)
            emulator_port = self.get_emulator_port(email)

            if not display_num or not emulator_port:
                # Assign a new display and port
                instance_id = self.assign_display_to_profile(email)
                if instance_id:
                    display_num = self.get_x_display(email)
                    emulator_port = self.get_emulator_port(email)
                    if not display_num or not emulator_port:
                        logger.error(f"Failed to get display or port for {email} after assignment")
                        return False, None, None
                else:
                    logger.error(f"Failed to assign display for {email}")
                    return False, None, None

            # Calculate emulator ID based on port
            emulator_id = f"emulator-{emulator_port}"

            logger.info(f"Using display :{display_num} and emulator port {emulator_port} for {email}")

            # Ensure VNC is running for this display
            self._ensure_vnc_running(display_num)

            # Set up environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir
            env["ANDROID_HOME"] = self.android_home

            # Set DISPLAY for VNC if on Linux
            if platform.system() != "Darwin":
                env["DISPLAY"] = f":{display_num}"
                logger.info(f"Setting DISPLAY={env['DISPLAY']} for VNC")

            # Build emulator command based on host architecture
            if platform.system() != "Darwin":
                # For Linux, use standard emulator with VNC with dynamic port
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-writable-system",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-verbose",
                    "-port",
                    str(emulator_port),  # Use the assigned port
                    "-feature",
                    "-accel",  # Disable hardware acceleration
                    "-gpu",
                    "swiftshader",
                    "-no-boot-anim",
                ]
            elif self.host_arch == "arm64":
                # For ARM Macs, use Rosetta to run x86_64 emulator
                emulator_cmd = [
                    "arch",
                    "-x86_64",
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-feature",
                    "-HVF",  # Disable hardware virtualization
                    "-accel",
                    "off",
                    "-port",
                    str(emulator_port),  # Use the assigned port
                ]
            else:
                # For Intel Macs
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-accel",
                    "on",
                    "-feature",
                    "HVF",
                    "-port",
                    str(emulator_port),  # Use the assigned port
                ]

            # Create log files for debugging
            log_dir = "/var/log/emulator"
            os.makedirs(log_dir, exist_ok=True)
            stdout_log = os.path.join(log_dir, f"emulator_{email}_stdout.log")
            stderr_log = os.path.join(log_dir, f"emulator_{email}_stderr.log")

            # Start emulator in background with logs
            logger.info(
                f"Starting emulator for {email} with AVD {avd_name} on display :{display_num} and port {emulator_port}"
            )
            logger.info(f"Emulator command: {' '.join(emulator_cmd)}")
            logger.info(f"Logging stdout to {stdout_log} and stderr to {stderr_log}")

            with open(stdout_log, "w") as stdout_file, open(stderr_log, "w") as stderr_file:
                process = subprocess.Popen(
                    emulator_cmd,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd="/tmp",  # Run in /tmp to avoid permission issues
                )

            # Store the running emulator info with the correct ID based on port
            self.running_emulators[email] = (emulator_id, display_num)

            # Configure VNC with clipping immediately
            self._restart_vnc_with_clipping(email, display_num)

            # Check if emulator process is actually running
            if process.poll() is not None:
                # Process already exited
                exit_code = process.returncode
                logger.error(f"Emulator process exited immediately with code {exit_code}")
                logger.error(f"Check logs at {stdout_log} and {stderr_log}")
                return False, None, None

            # Process is running
            logger.info(f"Emulator process started with PID {process.pid}")
            logger.info(f"Emulator started for {email} with ID {emulator_id} on display :{display_num}")

            return True, emulator_id, display_num

        except Exception as e:
            logger.error(f"Error launching emulator for {avd_name}: {e}")
            return False, None, None

    def release_profile(self, email: str) -> bool:
        """
        Release the profile assignment in the VNC instance map.

        Args:
            email: The user's email address

        Returns:
            True if successful, False otherwise
        """
        try:
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    instance["assigned_profile"] = None
                    self._save_vnc_instance_map()
                    logger.info(f"Released profile {email} from VNC instance map")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error releasing profile {email}: {e}")
            return False

    def stop_emulator(self, email: str) -> bool:
        """
        Stop the emulator for the specified email.

        Args:
            email: The user's email address

        Returns:
            True if emulator was stopped, False otherwise
        """
        try:
            if email not in self.running_emulators:
                logger.info(f"No running emulator found for {email}")
                return False

            emulator_id, display_num = self.running_emulators[email]
            logger.info(f"Stopping emulator {emulator_id} for {email} on display :{display_num}")

            # Use adb to send kill command to emulator
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                check=False,
                timeout=5,
            )

            # Wait briefly for emulator to shut down
            time.sleep(3)

            # Check if emulator is still running
            check_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            if emulator_id not in check_result.stdout:
                logger.info(f"Emulator {emulator_id} stopped successfully for {email}")
                del self.running_emulators[email]
                return True

            # Force kill if still running - but use the specific emulator port in the pattern
            # to avoid killing other emulators when multiple are running
            emulator_port = self.get_emulator_port(email)
            if emulator_port:
                logger.warning(
                    f"Emulator {emulator_id} did not stop gracefully, killing process for port {emulator_port}"
                )
                subprocess.run(["pkill", "-f", f"emulator.*-port {emulator_port}"], check=False, timeout=3)
            else:
                logger.warning("Could not determine emulator port, using generic kill pattern")
                subprocess.run(["pkill", "-f", f"emulator.*{emulator_id}"], check=False, timeout=3)

            # Remove from running emulators
            del self.running_emulators[email]
            return True

        except Exception as e:
            logger.error(f"Error stopping emulator for {email}: {e}")
            return False

    def get_running_emulator(self, email: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Get the emulator ID and display number for the specified email.

        Args:
            email: The user's email address

        Returns:
            Tuple of (emulator_id, display_num) or (None, None) if not found
        """
        if email in self.running_emulators:
            return self.running_emulators[email]
        return None, None

    def is_emulator_running(self, email: str) -> bool:
        """
        Check if an emulator is running for the specified email.

        Args:
            email: The user's email address

        Returns:
            True if an emulator is running, False otherwise
        """
        emulator_id, _ = self.get_running_emulator(email)
        if not emulator_id:
            return False

        try:
            # Check if emulator is responding to adb
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "get-state"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            return "device" in result.stdout.strip()
        except Exception as e:
            logger.error(f"Error checking if emulator is running for {email}: {e}")
            return False

    def is_emulator_ready(self, email: str) -> bool:
        """
        Check if an emulator is running and fully booted for the specified email.

        Args:
            email: The user's email address

        Returns:
            True if an emulator is ready, False otherwise
        """
        emulator_id, _ = self.get_running_emulator(email)
        if not emulator_id:
            logger.info(f"No running emulator found for {email}")
            return False

        try:
            # Check process first - is the emulator still running?
            ps_check = subprocess.run(
                ["pgrep", "-f", "qemu-system-x86_64"], check=False, capture_output=True, text=True
            )

            if ps_check.returncode != 0:
                logger.info(f"No emulator process found running")
                return False

            # First check if device is connected
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            if emulator_id not in devices_result.stdout:
                logger.info(
                    f"Emulator {emulator_id} not found in adb devices: {devices_result.stdout.strip()}"
                )
                return False

            if "device" not in devices_result.stdout:
                logger.info(f"Emulator {emulator_id} found but not shown as 'device' state")
                return False

            # Check if boot is completed
            boot_completed = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "getprop",
                    "sys.boot_completed",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            result = boot_completed.stdout.strip() == "1"
            if result:
                logger.info(f"Emulator {emulator_id} is fully booted (sys.boot_completed=1)")
            else:
                logger.info(f"Emulator boot not complete: sys.boot_completed={boot_completed.stdout.strip()}")

            return result

        except Exception as e:
            logger.error(f"Error checking if emulator is ready for {email}: {e}")
            return False
