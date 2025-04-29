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
                logger.info(f"Loaded VNC instance mapping from {self.vnc_instance_map_path}")
            else:
                # Create default instances
                logger.info(f"Creating default VNC instance mapping at {self.vnc_instance_map_path}")
                self.vnc_instances = {
                    "instances": [
                        {
                            "id": i,
                            "display": i,
                            "vnc_port": 5900 + i,
                            "novnc_port": 6080 + i,
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
                # Start Xvfb
                logger.info(f"Starting Xvfb for display :{display_num}")
                subprocess.run(["systemctl", "start", f"xvfb@{display_num}.service"], check=False, timeout=5)
                time.sleep(1)

            # Check if x11vnc is running for this display
            vnc_check = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*:{display_num}"], capture_output=True, text=True
            )

            if vnc_check.returncode != 0:
                # Start VNC service
                logger.info(f"Starting VNC service for display :{display_num}")
                subprocess.run(["systemctl", "start", f"vnc@{display_num}.service"], check=False, timeout=5)
                time.sleep(1)

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
                    "/home/root/.vnc/passwd",
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

            # Get assigned display for this profile
            display_num = self.get_x_display(email)

            if not display_num:
                # Assign a new display
                display_num = self.assign_display_to_profile(email)
                if not display_num:
                    logger.error(f"Failed to assign display for {email}, using default display :1")
                    display_num = 1  # Default to display 1

            logger.info(f"Using display :{display_num} for {email}")

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
                # For Linux, use standard emulator with VNC
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
                    "5554",
                    "-gpu",
                    "swiftshader_indirect",
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
                    "5554",
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
                    "5554",
                ]

            # Start emulator in background
            logger.info(f"Starting emulator for {email} with AVD {avd_name} on display :{display_num}")
            logger.info(f"Emulator command: {' '.join(emulator_cmd)}")

            process = subprocess.Popen(emulator_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Wait a moment for emulator to initialize
            time.sleep(2)

            # Use a fixed emulator ID since we're using port 5554
            emulator_id = "emulator-5554"

            # Store the running emulator info
            self.running_emulators[email] = (emulator_id, display_num)

            # Wait briefly for initialization, then restart VNC with clipping
            time.sleep(5)
            self._restart_vnc_with_clipping(email, display_num)

            return True, emulator_id, display_num

        except Exception as e:
            logger.error(f"Error launching emulator for {avd_name}: {e}")
            return False, None, None

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

            # Force kill if still running
            logger.warning(f"Emulator {emulator_id} did not stop gracefully, forcing termination")
            subprocess.run(["pkill", "-f", "emulator"], check=False, timeout=3)

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
            return False

        try:
            # First check if device is connected
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            if emulator_id not in devices_result.stdout or "device" not in devices_result.stdout:
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

            return boot_completed.stdout.strip() == "1"
        except Exception as e:
            logger.error(f"Error checking if emulator is ready for {email}: {e}")
            return False
