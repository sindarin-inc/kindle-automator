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
from typing import Dict, List, Optional, Set, Tuple

from server.utils import ansi_colors as ansi
from server.utils.request_utils import get_sindarin_email
from server.utils.vnc_instance_manager import VNCInstanceManager

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

        # Set up profiles directory
        self.profiles_dir = os.path.join(android_home, "profiles")

        # Ensure profiles directory exists
        os.makedirs(self.profiles_dir, exist_ok=True)

        # Maps AVD names to (emulator_id, display_num) tuples
        # IMPORTANT: We use AVD names as keys, NOT emails
        self.running_emulators = {}

        # Use the VNCInstanceManager singleton for managing VNC instances
        self.vnc_manager = VNCInstanceManager.get_instance()

    def _get_running_emulator_ids(self) -> Set[str]:
        """
        Get a set of currently running emulator IDs from adb devices.

        Returns:
            Set of emulator IDs (e.g., 'emulator-5554') that are currently running
        """
        running_ids = set()
        try:
            # Check if emulator is running via adb devices
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            # Always log the full adb devices output for debugging
            logger.info(f"ADB devices output: {devices_result.stdout.strip()}")

            if devices_result.returncode == 0:
                # Parse output to get emulator IDs
                lines = devices_result.stdout.strip().split("\n")

                # Skip the header line
                for line in lines[1:]:
                    if not line.strip():
                        continue

                    parts = line.split("\t")
                    if len(parts) >= 2 and "emulator" in parts[0]:
                        status = parts[1].strip()
                        if status != "offline":
                            running_ids.add(parts[0].strip())
                            logger.info(f"Found running emulator: {parts[0].strip()} with status: {status}")
                        else:
                            logger.warning(f"Emulator {parts[0].strip()} found but status is offline")
            else:
                logger.warning(f"Failed to get adb devices: {devices_result.stderr}")

        except Exception as e:
            logger.error(f"Error checking running emulators via adb: {e}")

        logger.info(f"Running emulator IDs: {running_ids}")
        return running_ids

    def _verify_emulator_running(self, emulator_id: str, email: str) -> bool:
        """
        Verify if a specific emulator is running using adb devices and has the correct AVD.

        This checks if the emulator is in adb devices in any state (device or offline)
        and verifies that the emulator's AVD matches the expected AVD for the email.

        Args:
            emulator_id: The emulator ID to check (e.g., 'emulator-5554')
            email: The email to verify that the AVD name matches the expected one

        Returns:
            True if the emulator is running with the correct AVD, False otherwise
        """
        try:
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            # Check if the emulator ID appears in the output at all (includes offline state)
            if emulator_id not in devices_result.stdout:
                logger.debug(f"Emulator {emulator_id} not found in adb devices output")
                return False

            # Get expected AVD name for this email
            email_avd = self._extract_avd_name_from_email(email)

            # Get actual AVD name from running emulator
            emulator_avd = self._extract_avd_name_from_emulator_id(emulator_id)

            # Verify AVD names match
            if not email_avd:
                logger.warning(f"Could not determine expected AVD name for email {email}")
                return False

            if not emulator_avd:
                # If we can't get the AVD name, check if the emulator is still booting
                # by looking at device status
                for line in devices_result.stdout.strip().split("\n"):
                    if emulator_id in line:
                        parts = line.split("\t")
                        if len(parts) >= 2 and parts[1].strip() in ["offline", "device"]:
                            # Emulator is present but still booting
                            # Check if this emulator ID matches our expected one from cache
                            avd_name = self._extract_avd_name_from_email(email)
                            if avd_name and avd_name in self.running_emulators:
                                cached_id, _ = self.running_emulators[avd_name]
                                if cached_id == emulator_id:
                                    logger.info(
                                        f"Emulator {emulator_id} is booting and matches cached ID for {email}"
                                    )
                                    return True
                            logger.warning(
                                f"Could not get AVD name from emulator {emulator_id}, possibly still booting"
                            )
                        break
                return False

            # Check if the AVD names match
            if emulator_avd == email_avd:
                return True
            else:
                logger.warning(
                    f"Emulator {emulator_id} is running with unexpected AVD {emulator_avd}, expected {email_avd}"
                )
                # Clear the cache entry since this emulator is running the wrong AVD
                if email_avd in self.running_emulators:
                    cached_id, _ = self.running_emulators[email_avd]
                    if cached_id == emulator_id:
                        logger.info(f"Clearing cache entry for AVD {email_avd} due to AVD mismatch")
                        del self.running_emulators[email_avd]
                return False

        except Exception as e:
            logger.error(f"Error running adb devices: {e}")
            return False

    def _extract_avd_name_from_emulator_id(self, emulator_id: str) -> Optional[str]:
        """
        Extract the AVD name from an emulator by querying the emulator with adb to get the avd name.

        Args:
            emulator_id: The emulator ID (e.g. 'emulator-5554')

        Returns:
            The AVD name (e.g. 'KindleAVD_user_example_com') or None if not found
        """
        try:
            # Parse the port from the emulator ID
            if not emulator_id.startswith("emulator-"):
                logger.warning(f"Invalid emulator ID format: {emulator_id}")
                return None

            # Get the AVD name from the emulator property ro.kernel.qemu.avd_name
            try:
                result = subprocess.run(
                    [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "shell",
                        "getprop",
                        "ro.kernel.qemu.avd_name",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode == 0 and result.stdout.strip():
                    avd_name = result.stdout.strip()
                    return avd_name

            except Exception as adb_error:
                logger.warning(f"Error getting ro.kernel.qemu.avd_name via ADB: {adb_error}")

            # Try alternative property that might contain AVD information
            try:
                result = subprocess.run(
                    [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "shell",
                        "getprop",
                        "qemu.avd_name",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode == 0 and result.stdout.strip():
                    avd_name = result.stdout.strip()
                    return avd_name

            except Exception as adb_error:
                logger.warning(f"Error getting qemu.avd_name via ADB: {adb_error}")

            # If we still don't have an AVD name, try more generic properties
            try:
                result = subprocess.run(
                    [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "shell",
                        "getprop",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode == 0:
                    # Look for any properties that might contain "avd" in their names
                    properties = result.stdout.strip().split("\n")
                    for prop in properties:
                        if "avd" in prop.lower():
                            # Extract property value if possible
                            if ": [" in prop and "]" in prop:
                                value = prop.split(": [")[1].split("]")[0]
                                if value:
                                    return value

            except Exception as adb_error:
                logger.warning(f"Error getting all properties via ADB: {adb_error}")

            return None

        except Exception as e:
            logger.error(f"Error extracting AVD name from emulator ID {emulator_id}: {e}")
            return None

    def get_x_display(self, email: str) -> Optional[int]:
        """
        Get the X display number for a profile.

        Args:
            email: The profile email

        Returns:
            The display number or None if not found
        """
        try:
            # Use VNCInstanceManager to get display number
            display = self.vnc_manager.get_x_display(email)
            if display is None:
                logger.warning(f"No display found for {email}")
            return display
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
            # Get the instance from VNCInstanceManager
            instance = self.vnc_manager.get_instance_for_profile(email)
            if instance:
                # Check if instance already has emulator_port field
                if "emulator_port" in instance:
                    return instance["emulator_port"]

            # No port found
            logger.warning(f"No emulator port found for {email}")
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
        # First check running emulators cache
        if email in self.running_emulators:
            emulator_id, _ = self.running_emulators[email]
            # Verify the emulator is actually running via adb devices with the correct AVD
            if self._verify_emulator_running(emulator_id, email):
                return emulator_id
            else:
                # Not found in adb devices or AVD mismatch, remove from cache
                logger.debug(
                    f"Cached emulator {emulator_id} for {email} not found in adb devices or has wrong AVD"
                )
                del self.running_emulators[email]

        # Then try to build from port
        port = self.get_emulator_port(email)
        if port:
            return f"emulator-{port}"

        return None

    def assign_display_to_profile(self, email: str) -> Optional[int]:
        """
        Assign a display number to a profile. Creates a new instance if needed.

        Args:
            email: The profile email

        Returns:
            The assigned display number or None if assignment failed
        """
        try:
            # Check if this profile already has a display assigned through VNCInstanceManager
            display = self.vnc_manager.get_x_display(email)
            if display:
                logger.info(f"Profile {email} already assigned to display :{display}")
                return display

            # Assign an instance in VNCInstanceManager
            instance = self.vnc_manager.assign_instance_to_profile(email)
            if instance:
                display = instance.get("display")
                logger.info(f"Assigned display :{display} to profile {email}")
                return display

            # No instance could be assigned
            logger.error(f"Failed to assign display for {email}")
            return None
        except Exception as e:
            logger.error(f"Error assigning display to profile {email}: {e}")
            return None

    def _extract_avd_name_from_email(self, email: str) -> Optional[str]:
        """
        Extract the AVD name for a given email from the profiles index.
        If not found, create it immediately to ensure it exists.
        Handles both standard emails and normalized emails (where @ is replaced with _).

        Args:
            email: The email address or normalized email format

        Returns:
            The AVD name or None if it couldn't be determined
        """
        try:
            profiles_dir = os.path.join(self.android_home, "profiles")
            users_file_path = os.path.join(profiles_dir, "users.json")

            # First check if this email already has an entry in profiles_index
            if os.path.exists(users_file_path):
                with open(users_file_path, "r") as f:
                    users = json.load(f)

                if email in users:
                    user_entry = users.get(email)
                    avd_name = user_entry.get("avd_name")
                    return avd_name

            # No existing entry, detect email format and create appropriate AVD name
            is_normalized = (
                "@" not in email
                and "_" in email
                and (email.endswith("_com") or email.endswith("_org") or email.endswith("_io"))
            )

            # Handle normalized vs. standard email formats
            if is_normalized:
                # Already normalized email format - just add prefix if needed
                avd_name = f"KindleAVD_{email}" if not email.startswith("KindleAVD_") else email
            else:
                # Standard email format - normalize it
                email_parts = email.split("@")
                if len(email_parts) != 2:
                    logger.error(f"Invalid email format: {email}")
                    return None

                username, domain = email_parts
                # Replace dots with underscores in both username and domain
                username = username.replace(".", "_")
                domain = domain.replace(".", "_")
                avd_name = f"KindleAVD_{username}_{domain}"

            # Register this profile in profiles_index
            try:
                # Ensure profiles directory exists
                os.makedirs(profiles_dir, exist_ok=True)

                # Create or load profiles_index
                if os.path.exists(users_file_path):
                    with open(users_file_path, "r") as f:
                        users = json.load(f)
                else:
                    users = {}

                # Add or update the entry for this email
                users[email] = {"avd_name": avd_name}

                # Save to file
                with open(users_file_path, "w") as f:
                    json.dump(users, f, indent=2)
            except Exception as e:
                logger.error(f"Error updating users.json: {e}")

            # Return the AVD name
            logger.info(f"Registered profile for {email} with AVD {avd_name} in users.json")
            return avd_name

        except Exception as e:
            logger.error(f"Error extracting AVD name for email '{email}': {e}")
            return None

    def _ensure_vnc_running(self, display_num: int, email: str = None) -> bool:
        """
        Ensure the VNC server is running for the specified display.

        Args:
            display_num: The X display number
            email: The email to use for AVD lookup. If not provided, attempts to get from context.

        Returns:
            True if VNC is running, False otherwise
        """
        if platform.system() == "Darwin":
            # Skip VNC setup on macOS
            return True

        # Allow email to be passed in, otherwise try to get from context
        if not email:
            email = get_sindarin_email()

        # If still no email, we can't determine the AVD name
        if not email:
            logger.error("No email available for VNC setup - cannot determine AVD name")
            return False

        avd_name = self._extract_avd_name_from_email(email)

        try:
            # Check if Xvfb is running for this display
            xvfb_check = subprocess.run(
                ["pgrep", "-f", f"Xvfb :{display_num}"], capture_output=True, text=True
            )

            if xvfb_check.returncode != 0:
                # Kill any existing Xvfb process for this display
                subprocess.run(["pkill", "-f", f"Xvfb :{display_num}"], check=False)
                # Clean up any lock files
                subprocess.run(
                    ["rm", "-f", f"/tmp/.X{display_num}-lock", f"/tmp/.X11-unix/X{display_num}"], check=False
                )

                # Start Xvfb with 1080x1920 resolution
                xvfb_cmd = [
                    "/usr/bin/Xvfb",
                    f":{display_num}",
                    "-screen",
                    "0",
                    "1080x1920x24",
                    "-ac",
                    "+extension",
                    "GLX",
                    "+render",
                    "-noreset",
                ]

                with open(f"/var/log/xvfb-{display_num}.log", "w") as f:
                    xvfb_process = subprocess.Popen(xvfb_cmd, stdout=f, stderr=f)

                # Verify Xvfb is running
                xvfb_check = subprocess.run(
                    ["pgrep", "-f", f"Xvfb :{display_num}"], capture_output=True, text=True
                )
                if xvfb_check.returncode != 0:
                    logger.error(f"Failed to start Xvfb for display :{display_num}")
                    return False
                else:
                    logger.info(f"Started Xvfb for display :{display_num}")

            # Check if x11vnc is running for this display
            vnc_check = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*:{display_num}"], capture_output=True, text=True
            )

            if vnc_check.returncode == 0:
                logger.error(f"VNC server already running for display :{display_num}, killing")

            # Start VNC directly
            # Kill any existing VNC process for this display
            from server.utils.port_utils import calculate_vnc_port

            vnc_port = calculate_vnc_port(display_num)
            subprocess.run(["pkill", "-f", f"x11vnc.*rfbport {vnc_port}"], check=False)

            # Set up environment
            env = os.environ.copy()
            env["DISPLAY"] = f":{display_num}"

            # First find the Kindle app window ID using xwininfo with retries
            try:
                window_id = None
                start_time = time.time()
                retry_interval = 0.2  # 200ms between retries
                max_wait_time = 5.0  # Max 5 seconds total wait time

                while time.time() - start_time < max_wait_time:
                    # Use xwininfo with -tree to find the emulator window
                    list_windows = subprocess.run(
                        ["xwininfo", "-tree", "-root", "-display", f":{display_num}"],
                        capture_output=True,
                        text=True,
                        check=False,
                        env=env,
                        timeout=3,
                    )

                    if list_windows.returncode == 0:
                        # Look for the Android Emulator window with the Kindle AVD
                        window_lines = list_windows.stdout.splitlines()
                        emulator_window_line = None

                        # First, look for an emulator window with KindleAVD in the name
                        for line in window_lines:
                            if "Android Emulator" in line and avd_name in line:
                                emulator_window_line = line
                                break

                        # Extract window ID if we found a matching window
                        if emulator_window_line:
                            # The window ID is at the beginning of the line, like "0x400007"
                            parts = emulator_window_line.split()
                            if parts and parts[0].startswith("0x"):
                                window_id = parts[0]
                                logger.info(
                                    f"Found emulator window ID: {window_id} after {time.time() - start_time:.2f}s"
                                )
                                break  # Exit the retry loop

                    # If we didn't find the window, wait and retry
                    time.sleep(retry_interval)

                # After all retries, if we still didn't find the window
                if not window_id:
                    logger.warning(
                        f"Could not find any matching window on display :{display_num} after {max_wait_time}s, using full display"
                    )

            except Exception as e:
                logger.warning(f"Error finding Kindle window ID: {e}, using full display")
                window_id = None

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
                "-scale",
                "1:1",
                "-desktop",
                f"Kindle Emulator (Display {display_num})",
                "-o",
                f"/var/log/x11vnc-{display_num}.log",
                "-bg",
            ]

            # Add -id flag if we found a window ID
            if window_id:
                vnc_cmd.extend(["-id", window_id])

            subprocess.run(vnc_cmd, env=env, check=False, timeout=5)

            # Verify VNC is running
            vnc_check = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*rfbport {vnc_port}"], capture_output=True, text=True
            )
            if vnc_check.returncode != 0:
                logger.error(f"x11vnc process not found for display :{display_num} after launch attempt.")
                logger.info(
                    f"For x11vnc startup issues, check its dedicated log: /var/log/x11vnc-{display_num}.log"
                )
                if vnc_check.stderr.strip():  # If pgrep itself had an error
                    logger.warning(
                        f"The pgrep command to check x11vnc status produced an error: {vnc_check.stderr.strip()}"
                    )
                return False

            logger.info(
                f"Started VNC server for :{display_num}: {ansi.YELLOW}vnc://kindle.sindarin.com:{vnc_port}{ansi.RESET}"
            )

            return True

        except Exception as e:
            logger.error(f"Error ensuring VNC is running for display :{display_num}: {e}")
            return False

    def _ensure_avd_ram_upgraded(self, avd_name: str) -> bool:
        """
        Ensure the AVD has at least 8GB of RAM configured.
        Updates the config.ini file if RAM is less than 8192 MB.

        Args:
            avd_name: Name of the AVD to check/upgrade

        Returns:
            True if RAM was already sufficient or successfully upgraded, False on error
        """
        try:
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            config_path = os.path.join(avd_path, "config.ini")

            if not os.path.exists(config_path):
                logger.error(f"Config file not found: {config_path}")
                return False

            # Read current config
            with open(config_path, "r") as f:
                lines = f.readlines()

            # Check current RAM setting
            ram_updated = False
            for i, line in enumerate(lines):
                if line.startswith("hw.ramSize="):
                    current_ram = int(line.split("=")[1].strip())
                    if current_ram < 8192:
                        logger.info(f"Upgrading RAM for {avd_name} from {current_ram}MB to 8192MB")
                        lines[i] = "hw.ramSize=8192\n"
                        ram_updated = True
                    else:
                        logger.debug(f"AVD {avd_name} already has sufficient RAM: {current_ram}MB")
                    break
            else:
                # hw.ramSize not found, add it
                logger.info(f"Adding RAM setting to {avd_name} config")
                lines.append("hw.ramSize=8192\n")
                ram_updated = True

            # Write updated config if needed
            if ram_updated:
                with open(config_path, "w") as f:
                    f.writelines(lines)
                logger.info(f"Successfully upgraded RAM for {avd_name}")

            return True

        except Exception as e:
            logger.error(f"Error ensuring RAM upgrade for {avd_name}: {e}")
            return False

    def launch_emulator(
        self, email: str, cold_boot: bool = False
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Launch an emulator for the specified AVD and email, with proper VNC display coordination.

        Args:
            email: The user's email address
            cold_boot: If True, launch with cold boot (no snapshot loading)

        Returns:
            Tuple of (success, emulator_id, display_num)
        """
        try:
            logger.debug(f"Launching emulator for {email}")

            # Check if AVD exists
            avd_name = self._extract_avd_name_from_email(email)
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            if not os.path.exists(avd_path):
                logger.error(f"AVD {avd_name} does not exist at {avd_path}")
                return False, None, None

            # Ensure AVD has sufficient RAM before launching
            # DISABLED: Auto-upgrading to 8GB breaks auth token in Kindle app
            # if not self._ensure_avd_ram_upgraded(avd_name):
            #     logger.warning(f"Failed to ensure RAM upgrade for {avd_name}, continuing anyway")

            # IMPORTANT: Use AVD name as key for running_emulators, not email
            # Check if emulator already running for this AVD
            # If this AVD is in our running_emulators cache
            if avd_name in self.running_emulators:
                emulator_id, display_num = self.running_emulators[avd_name]

                # Verify the emulator is actually running via adb devices with the correct AVD
                if self._verify_emulator_running(emulator_id, email):
                    logger.info(
                        f"Emulator already running for AVD {avd_name} (email {email}): {emulator_id} on display :{display_num}"
                    )

                    # Check if emulator is actually ready before logging identifiers
                    if self.is_emulator_ready(email):
                        # Log device identifiers for the already running emulator
                        self._log_device_identifiers(emulator_id, email)
                    else:
                        logger.info(f"Emulator {emulator_id} is running but not fully ready yet")

                    # Store this emulator ID in the VNC instance
                    try:
                        from server.utils.vnc_instance_manager import VNCInstanceManager

                        vnc_manager = VNCInstanceManager.get_instance()
                        vnc_manager.set_emulator_id(email, emulator_id)
                        logger.info(f"Updated VNC instance with emulator ID {emulator_id} for {email}")
                    except Exception as e:
                        logger.error(f"Failed to update VNC instance with emulator ID: {e}")

                    return True, emulator_id, display_num
                else:
                    # Emulator not actually running according to adb, remove from our cache
                    logger.info(
                        f"Emulator {emulator_id} for AVD {avd_name} not found in adb devices, removing from cache"
                    )
                    del self.running_emulators[avd_name]
            else:
                logger.info(f"AVD {avd_name} NOT found in running_emulators cache")

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
                        logger.error(
                            f"Failed to get display or port for {email} after assignment: {display_num} {emulator_port}"
                        )
                        return False, None, None
                else:
                    logger.error(f"Failed to assign display for {email} - AVD {avd_name}")
                    return False, None, None

            # Calculate emulator ID based on port
            emulator_id = f"emulator-{emulator_port}"

            # Set up environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir
            env["ANDROID_HOME"] = self.android_home

            # Launch emulator first so the window is available for xwininfo to find
            # VNC server will be started after the emulator is launched

            # Set DISPLAY for VNC if on Linux
            if platform.system() != "Darwin":
                env["DISPLAY"] = f":{display_num}"

            # No longer explicitly loading snapshots - the emulator will use default_boot automatically
            # Log when the default_boot snapshot was last updated
            created_from_seed = False
            avd_manager = None
            try:
                from views.core.avd_creator import AVDCreator
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager.get_instance()
                last_snapshot_timestamp = avd_manager.get_user_field(email, "last_snapshot_timestamp")

                if last_snapshot_timestamp:
                    logger.info(
                        f"Default boot snapshot was last updated at {last_snapshot_timestamp} for {email}"
                    )
                else:
                    logger.info(
                        f"No snapshot timestamp found for {email}, emulator will use default boot if available"
                    )

                # Special handling for seed clone AVDs
                created_from_seed = avd_manager.get_user_field(email, "created_from_seed_clone")
                if created_from_seed:
                    logger.info(f"AVD was created from seed clone")

            except Exception as e:
                logger.warning(f"Error accessing user profile for snapshot info: {e}")
                created_from_seed = False
                # Proceed normally - emulator will use default_boot if available

            # Check if we've already randomized this AVD (needed for cold boot decision)
            post_boot_randomized = False
            needs_device_randomization = False
            try:
                if avd_manager is None:
                    from views.core.avd_profile_manager import AVDProfileManager

                    avd_manager = AVDProfileManager.get_instance()
                post_boot_randomized = avd_manager.get_user_field(email, "post_boot_randomized", False)
                needs_device_randomization = avd_manager.get_user_field(
                    email, "needs_device_randomization", False
                )
            except:
                pass

            # Common emulator arguments for all platforms
            common_args = [
                "-avd",
                avd_name,
                "-no-audio",
                "-no-boot-anim",
                "-writable-system",
                "-port",
                str(emulator_port),
                # Only qemu.* properties can be set via -prop
                # hw.* properties are set in the AVD config.ini file
                "-prop",
                "qemu.settings.system.show_ime_with_hard_keyboard=0",
            ]

            # Add no-window flag only for Linux
            if platform.system() != "Darwin":
                common_args.append("-no-window")

            # Add randomized device identifiers if available
            try:
                from server.utils.device_identifier_utils import get_emulator_prop_args
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager.get_instance()
                device_identifiers = avd_manager.get_user_field(email, "device_identifiers")
                if device_identifiers:
                    prop_args = get_emulator_prop_args(device_identifiers)
                    common_args.extend(prop_args)
                    logger.info(f"Added randomized device identifier props: {prop_args}")
            except Exception as e:
                logger.warning(f"Could not add device identifier props: {e}")
                # Continue without randomized identifiers

            # Determine if we should force cold boot
            # Force cold boot if this AVD needs first-time randomization
            force_cold_boot_for_randomization = False
            if created_from_seed or needs_device_randomization:
                if not post_boot_randomized:
                    force_cold_boot_for_randomization = True
                    logger.info(f"Forcing cold boot for {email} to apply device randomization")

            # Add snapshot or cold boot args
            if cold_boot or force_cold_boot_for_randomization:
                common_args.extend(["-no-snapshot-load"])
                logger.info(f"Starting emulator for {email} with cold boot (no snapshot)")
            else:
                # Load from default_boot snapshot if it exists
                common_args.extend(["-snapshot", "default_boot"])
                logger.info(f"Starting emulator for {email} - will use default_boot snapshot if available")

            # Build platform-specific emulator command
            if platform.system() != "Darwin":
                # For Linux, use standard emulator with VNC with dynamic port
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-verbose",
                    "-feature",
                    "-accel",  # Disable hardware acceleration
                    "-feature",
                    "-Gfxstream",  # Disable gfxstream to use legacy renderer for snapshot compatibility
                    "-gpu",
                    "swiftshader",
                ] + common_args
            elif self.host_arch == "arm64" and platform.system() == "Darwin":
                # For ARM Macs, use native ARM64 emulation
                # The Android emulator will automatically use qemu-system-aarch64
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-accel",
                    "auto",  # Let emulator auto-detect the best acceleration method
                ] + common_args
            else:
                # For Intel Macs
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-feature",
                    "-Gfxstream",  # Disable gfxstream for snapshot compatibility
                    "-accel",
                    "on",
                    "-feature",
                    "HVF",
                ] + common_args

            # Create log files for debugging
            if platform.system() == "Darwin":
                # Use local logs directory on macOS
                log_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "emulator"
                )
            else:
                # Use system log directory on Linux
                log_dir = "/var/log/emulator"
            os.makedirs(log_dir, exist_ok=True)
            stdout_log = os.path.join(log_dir, f"emulator_{avd_name}_stdout.log")
            stderr_log = os.path.join(log_dir, f"emulator_{avd_name}_stderr.log")

            # Start emulator in background with logs
            logger.info(
                f"Starting emulator for AVD {avd_name} (email {email}) on display :{display_num} and port {emulator_port}"
            )
            logger.info(f"Emulator command: {' '.join(emulator_cmd)}")
            # logger.info(f"Logging stdout to {stdout_log} and stderr to {stderr_log}")

            # Wrap with xvfb-run on Linux
            if platform.system() != "Darwin":
                emulator_cmd = [
                    "xvfb-run",
                    "-n",
                    str(display_num),
                    "-s",
                    f"-screen 0 1080x1920x24",
                    "--",
                ] + emulator_cmd

            with open(stdout_log, "w") as stdout_file, open(stderr_log, "w") as stderr_file:
                process = subprocess.Popen(
                    emulator_cmd,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd="/tmp",  # Run in /tmp to avoid permission issues
                )

            # Add immediate check after launch
            import time

            time.sleep(0.5)  # Brief pause to let process start
            poll_result = process.poll()
            if poll_result is not None:
                logger.error(f"Emulator process exited immediately with code: {poll_result}")
                # Read the error logs
                try:
                    with open(stderr_log, "r") as f:
                        stderr_content = f.read()
                        if stderr_content:
                            logger.error(f"Emulator stderr content: {stderr_content}")
                    with open(stdout_log, "r") as f:
                        stdout_content = f.read()
                        if stdout_content:
                            logger.error(f"Emulator stdout content: {stdout_content}")
                except Exception as e:
                    logger.error(f"Failed to read emulator logs: {e}")
                raise Exception(f"Emulator failed to start with exit code {poll_result}")

            # Store the running emulator info in multiple places to ensure tracking:

            # 1. Store in running_emulators map with AVD name as key
            self.running_emulators[avd_name] = (emulator_id, display_num)

            # 2. Also store the emulator ID in the VNC instance manager
            try:
                from server.utils.vnc_instance_manager import VNCInstanceManager

                vnc_manager = VNCInstanceManager.get_instance()
                vnc_manager.set_emulator_id(email, emulator_id)
                logger.info(f"Set emulator ID {emulator_id} for {email} in VNC instance manager")
            except Exception as e:
                logger.error(f"Error storing emulator ID in VNC instance: {e}")

            # 3. No longer storing emulator_id in profiles - VNC instance manager is the source of truth

            # Now ensure VNC is running for this display after emulator is launched
            if platform.system() != "Darwin":
                self._ensure_vnc_running(display_num, email=email)

            # Check if emulator process is actually running
            if process.poll() is not None:
                # Process already exited
                logger.error(f"Emulator process exited immediately with code: {process.poll()}")
                # Check the log files
                with open(stdout_log, "r") as f:
                    stdout_content = f.read()
                    if stdout_content:
                        logger.error(f"Emulator stdout: {stdout_content}")
                with open(stderr_log, "r") as f:
                    stderr_content = f.read()
                    if stderr_content:
                        logger.error(f"Emulator stderr: {stderr_content}")
                exit_code = process.returncode
                logger.error(f"Emulator process exited immediately with code {exit_code}")
                logger.error(f"Check logs at {stdout_log} and {stderr_log}")
                # Read and log stdout
                try:
                    with open(stdout_log, "r") as f:
                        stdout_content = f.read()
                    logger.error(f"Emulator stdout ({stdout_log}):\n{stdout_content}")
                except Exception as e:
                    logger.error(f"Failed to read emulator stdout log {stdout_log}: {e}")
                # Read and log stderr
                try:
                    with open(stderr_log, "r") as f:
                        stderr_content = f.read()
                    logger.error(f"Emulator stderr ({stderr_log}):\n{stderr_content}")
                except Exception as e:
                    logger.error(f"Failed to read emulator stderr log {stderr_log}: {e}")
                return False, None, None

            # Wait for emulator to be ready before applying post-boot randomization
            logger.info(f"Waiting for emulator {emulator_id} to be ready...")
            max_wait_time = 120  # 2 minutes max wait
            start_time = time.time()

            while time.time() - start_time < max_wait_time:
                if self.is_emulator_ready(email):
                    logger.info(f"Emulator {emulator_id} is ready")
                    break
                time.sleep(2)
            else:
                logger.warning(f"Emulator {emulator_id} not ready after {max_wait_time}s, continuing anyway")

            # Log device identifiers once emulator is confirmed ready
            self._log_device_identifiers(emulator_id, email)

            # Apply post-boot randomization ONLY if this is the first boot after cloning
            # Check if we've already randomized this AVD
            post_boot_randomized_check = False
            needs_device_randomization_check = False
            try:
                if avd_manager is None:
                    from views.core.avd_profile_manager import AVDProfileManager

                    avd_manager = AVDProfileManager.get_instance()
                post_boot_randomized_check = avd_manager.get_user_field(email, "post_boot_randomized", False)
                needs_device_randomization_check = avd_manager.get_user_field(
                    email, "needs_device_randomization", False
                )
            except:
                pass

            # Randomize if: (1) created from seed and not randomized, OR (2) explicitly needs randomization (seed clone)
            if (created_from_seed and not post_boot_randomized_check) or (
                needs_device_randomization_check and not post_boot_randomized_check
            ):
                try:
                    from server.utils.post_boot_randomizer import PostBootRandomizer

                    post_boot_randomizer = PostBootRandomizer(self.android_home)
                    # Get stored Android ID if available
                    android_id = None
                    try:
                        device_identifiers = avd_manager.get_user_field(email, "device_identifiers")
                        if device_identifiers and "android_id" in device_identifiers:
                            android_id = device_identifiers["android_id"]
                    except:
                        pass

                    logger.info(f"Applying one-time post-boot randomization for {email} on {emulator_id}")
                    if post_boot_randomizer.randomize_all_post_boot_identifiers(
                        emulator_id, android_id, device_identifiers
                    ):
                        logger.info(f"Successfully applied post-boot randomization")
                        # Mark that we've done post-boot randomization
                        avd_manager.set_user_field(email, "post_boot_randomized", True)
                        # Log identifiers again after randomization to show the changes
                        logger.info("Device identifiers after randomization:")
                        self._log_device_identifiers(emulator_id, email)
                    else:
                        logger.warning(f"Some post-boot randomizations may have failed")
                except Exception as e:
                    logger.error(f"Failed to apply post-boot randomization: {e}")
                    # Continue anyway - better to have a working emulator with duplicate identifiers
            elif (created_from_seed or needs_device_randomization_check) and post_boot_randomized_check:
                logger.info(f"Skipping post-boot randomization for {email} - already randomized")

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
            # Release the profile through VNCInstanceManager
            if self.vnc_manager.release_instance_from_profile(email):
                logger.info(f"Released profile {email} from VNC instance map")
                return True
            else:
                logger.warning(f"No VNC instance found for profile {email}")
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
            # Get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)

            # First try to find emulator by AVD name
            if avd_name and avd_name in self.running_emulators:
                emulator_id, display_num = self.running_emulators[avd_name]

                # Verify the emulator is actually running via adb devices with the correct AVD
                if self._verify_emulator_running(emulator_id, email):
                    logger.info(
                        f"Stopping emulator {emulator_id} for AVD {avd_name} (email {email}) on display :{display_num}"
                    )
                else:
                    # Emulator not actually running according to adb, remove from cache
                    logger.info(
                        f"Emulator {emulator_id} for AVD {avd_name} not found in adb devices, removing from cache"
                    )
                    del self.running_emulators[avd_name]
                    return False

                # Clean up all ports before killing emulator
                logger.info(f"Cleaning up ports for emulator {emulator_id}")
                try:
                    # Remove all ADB port forwards
                    subprocess.run(
                        [f"adb -s {emulator_id} forward --remove-all"],
                        shell=True,
                        check=False,
                        capture_output=True,
                        timeout=5,
                    )
                    # Kill any UiAutomator2 processes
                    subprocess.run(
                        [f"adb -s {emulator_id} shell pkill -f uiautomator"],
                        shell=True,
                        check=False,
                        capture_output=True,
                        timeout=5,
                    )
                except Exception as e:
                    logger.warning(f"Error cleaning up ports before stopping emulator: {e}")

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
                    logger.info(f"Emulator {emulator_id} stopped successfully for AVD {avd_name}")
                    del self.running_emulators[avd_name]
                    return True

                # Force kill if still running - but use the specific emulator port in the pattern
                # to avoid killing other emulators when multiple are running
                emulator_port = self.get_emulator_port(email)
                if emulator_port:
                    logger.warning(
                        f"Emulator {emulator_id} did not stop gracefully, killing process for port {emulator_port}"
                    )
                    subprocess.run(
                        ["pkill", "-f", f"emulator.*-port {emulator_port}"], check=False, timeout=3
                    )
                else:
                    logger.warning("Could not determine emulator port, using generic kill pattern")
                    subprocess.run(["pkill", "-f", f"emulator.*{emulator_id}"], check=False, timeout=3)

                # Remove from running emulators
                del self.running_emulators[avd_name]
                return True

            # For backward compatibility, check using email directly
            elif email in self.running_emulators:
                emulator_id, display_num = self.running_emulators[email]

                # Verify the emulator is actually running via adb devices with the correct AVD
                if self._verify_emulator_running(emulator_id, email):
                    logger.info(
                        f"Stopping emulator {emulator_id} for {email} on display :{display_num} (legacy key)"
                    )
                else:
                    # Emulator not actually running according to adb, remove from cache
                    logger.info(
                        f"Emulator {emulator_id} for {email} not found in adb devices, removing from cache"
                    )
                    del self.running_emulators[email]
                    return False

                # Clean up all ports before killing emulator
                logger.info(f"Cleaning up ports for emulator {emulator_id}")
                try:
                    # Remove all ADB port forwards
                    subprocess.run(
                        [f"adb -s {emulator_id} forward --remove-all"],
                        shell=True,
                        check=False,
                        capture_output=True,
                        timeout=5,
                    )
                    # Kill any UiAutomator2 processes
                    subprocess.run(
                        [f"adb -s {emulator_id} shell pkill -f uiautomator"],
                        shell=True,
                        check=False,
                        capture_output=True,
                        timeout=5,
                    )
                except Exception as e:
                    logger.warning(f"Error cleaning up ports before stopping emulator: {e}")

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
                emulator_port = self.get_emulator_port(email)
                if emulator_port:
                    logger.warning(
                        f"Emulator {emulator_id} did not stop gracefully, killing process for port {emulator_port}"
                    )
                    subprocess.run(
                        ["pkill", "-f", f"emulator.*-port {emulator_port}"], check=False, timeout=3
                    )
                else:
                    logger.warning("Could not determine emulator port, using generic kill pattern")
                    subprocess.run(["pkill", "-f", f"emulator.*{emulator_id}"], check=False, timeout=3)

                # Remove from running emulators
                del self.running_emulators[email]
                return True

            # No running emulator found
            else:
                logger.info(f"No running emulator found for {email} or AVD {avd_name}")
                return False

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

        try:
            # First try to get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)

            # If we have an AVD name and it's in running_emulators, use that
            if avd_name and avd_name in self.running_emulators:
                emulator_id, display_num = self.running_emulators[avd_name]

                # Get the direct ADB output (includes both 'device' and 'offline' status)
                try:
                    devices_result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )

                    # Check if our emulator ID is in the ADB output in any state
                    if emulator_id in devices_result.stdout:
                        return emulator_id, display_num
                    else:
                        # Emulator not found at all, remove from cache
                        logger.debug(
                            f"Cached emulator {emulator_id} for AVD {avd_name} not found in adb devices, removing from cache"
                        )
                        del self.running_emulators[avd_name]
                except Exception as adb_e:
                    logger.error(f"Error running adb devices: {adb_e}")
                    # Fall back to our regular verify method if adb command fails
                    if self._verify_emulator_running(emulator_id, email):
                        return emulator_id, display_num
                    else:
                        del self.running_emulators[avd_name]
        except Exception as e:
            logger.error(f"Error checking running emulator via adb: {e}")

        return None, None

    def is_emulator_ready(self, email: str) -> bool:
        """
        Check if an emulator is running and fully booted for the specified email.

        Args:
            email: The user's email address

        Returns:
            True if an emulator is ready, False otherwise
        """
        try:
            # Step 1: Get emulator ID and verify AVD name matches early
            emulator_id = self._get_emulator_id_for_readiness_check(email)
            if not emulator_id:
                return False

            # Step 2: Verify this emulator is actually running the correct AVD
            # Do this early to avoid wasting time on wrong emulator
            if not self._verify_emulator_running(emulator_id, email):
                logger.warning(f"Emulator {emulator_id} is not running the correct AVD for {email}")
                # The cache should have been cleared by _verify_emulator_running if there was a mismatch
                # Double-check and clear if needed to be extra safe
                avd_name = self._extract_avd_name_from_email(email)
                if avd_name and avd_name in self.running_emulators:
                    cached_id, _ = self.running_emulators[avd_name]
                    if cached_id == emulator_id:
                        logger.info(f"Clearing stale cache entry for AVD {avd_name} in readiness check")
                        del self.running_emulators[avd_name]
                return False

            # Step 3: Check if emulator process is running
            if not self._is_emulator_process_running():
                logger.info("No emulator process found running")
                return False

            # Step 4: Check ADB device status
            device_status = self._get_adb_device_status(emulator_id)
            if not self._is_device_status_ready(device_status):
                return False

            # Step 5: Check if system boot is completed
            if not self._is_boot_completed(emulator_id):
                return False

            # Step 6: Check if package manager is ready
            if not self._is_package_manager_ready(emulator_id):
                return False

            logger.info(f"Emulator {emulator_id} is fully ready")
            return True

        except Exception as e:
            logger.error(f"Error checking if emulator is ready for {email}: {e}")
            return False

    def _get_emulator_id_for_readiness_check(self, email: str) -> Optional[str]:
        """Get the emulator ID for readiness check with AVD verification."""
        # First check if we have the emulator in our cache to get its expected ID
        avd_name = self._extract_avd_name_from_email(email)
        expected_emulator_id = None
        if avd_name and avd_name in self.running_emulators:
            expected_emulator_id, _ = self.running_emulators[avd_name]
            logger.info(f"Found cached emulator {expected_emulator_id} for AVD {avd_name}")

        # Get the emulator ID using get_running_emulator which handles AVD lookup
        emulator_id, _ = self.get_running_emulator(email)

        # If we found an emulator, it's already been verified by get_running_emulator
        if emulator_id:
            return emulator_id

        # No emulator found via normal lookup, check cached ID if available
        if expected_emulator_id:
            logger.info(
                f"No emulator found via get_running_emulator for {email}, but have cached ID {expected_emulator_id}"
            )
            # Check if it's actually running AND has the correct AVD
            # Note: We'll verify AVD again in the main method for consistency
            if self._is_emulator_online(expected_emulator_id):
                logger.info(f"Cached emulator {expected_emulator_id} is online, will verify AVD next")
                # Re-add to cache since it was prematurely removed
                if avd_name and avd_name not in self.running_emulators:
                    # Get display number from VNC instance if available
                    display_num = 2  # Default display
                    vnc_instance = self.vnc_manager.get_instance_for_profile(email)
                    if vnc_instance and vnc_instance.get("display"):
                        display_num = vnc_instance["display"]
                    logger.info(f"Re-adding {expected_emulator_id} to cache for AVD {avd_name}")
                    self.running_emulators[avd_name] = (expected_emulator_id, display_num)
                return expected_emulator_id
            else:
                logger.info(f"Cached emulator {expected_emulator_id} is not online anymore")

        # No emulator found in cache, check if any running emulator matches our AVD
        # This handles cases where the emulator is running but not in cache
        if avd_name:
            running_ids = self._get_running_emulator_ids()
            for emulator_id in running_ids:
                if self._verify_emulator_running(emulator_id, email):
                    logger.info(f"Found running emulator {emulator_id} that matches AVD {avd_name}")
                    # Add to cache
                    display_num = 2  # Default display
                    vnc_instance = self.vnc_manager.get_instance_for_profile(email)
                    if vnc_instance and vnc_instance.get("display"):
                        display_num = vnc_instance["display"]
                    self.running_emulators[avd_name] = (emulator_id, display_num)
                    return emulator_id

        # No valid emulator found
        self._log_missing_emulator_debug_info(email, expected_emulator_id)
        return None

    def _is_emulator_online(self, emulator_id: str) -> bool:
        """Quick check if emulator is online in ADB devices."""
        try:
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            for line in result.stdout.strip().split("\n"):
                if emulator_id in line and "\tdevice" in line:
                    return True
            return False
        except Exception:
            return False

    def _log_missing_emulator_debug_info(self, email: str, expected_emulator_id: Optional[str]) -> None:
        """Log debug information when emulator is not found."""
        logger.info(f"No running emulator found for {email}")

        # Additional debugging: directly check adb devices output
        try:
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            logger.info(f"Direct adb devices check: {devices_result.stdout.strip()}")

            # If expected_emulator_id is in the output but not recognized, log this discrepancy
            if expected_emulator_id and expected_emulator_id in devices_result.stdout:
                logger.warning(
                    f"Expected emulator {expected_emulator_id} appears in adb devices output but wasn't recognized"
                )
        except Exception as e:
            logger.error(f"Error during direct adb devices check: {e}")

    def _is_emulator_process_running(self) -> bool:
        """Check if any emulator process is running."""
        try:
            ps_check = subprocess.run(
                ["pgrep", "-f", "qemu-system-aarch64"], check=False, capture_output=True, text=True
            )
            return ps_check.returncode == 0
        except Exception:
            return False

    def _get_adb_device_status(self, emulator_id: str) -> Optional[str]:
        """Get the ADB device status for the emulator."""
        try:
            device_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            if emulator_id not in device_result.stdout:
                logger.info(f"Emulator {emulator_id} not found in adb devices output")
                return None

            # Parse device status
            for line in device_result.stdout.strip().split("\n"):
                if emulator_id in line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        return parts[1].strip()

            return "unknown"
        except Exception as e:
            logger.error(f"Error checking device status: {e}")
            return None

    def _is_device_status_ready(self, device_status: Optional[str]) -> bool:
        """Check if the device status indicates readiness."""
        if not device_status:
            return False

        if device_status == "offline":
            return False
        elif device_status == "device":
            return True
        else:
            logger.info(f"Emulator is in unexpected state: {device_status}")
            return False

    def _is_boot_completed(self, emulator_id: str) -> bool:
        """Check if system boot is completed."""
        try:
            boot_check = subprocess.run(
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

            if boot_check.returncode != 0:
                logger.warning(f"Boot completed check failed: {boot_check.stderr.strip()}")
                return False

            return boot_check.stdout.strip() == "1"
        except Exception as e:
            logger.error(f"Error checking boot status: {e}")
            return False

    def _log_device_identifiers(self, emulator_id: str, email: str) -> None:
        """
        Log device identifiers for the emulator once it's ready.
        This helps verify that device randomization is working.

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')
            email: The user's email address
        """
        try:
            logger.info(f"Device identifiers for {email} on {emulator_id}:")

            # Get various device properties
            properties = {
                "Android ID": "settings get secure android_id",
                "Serial Number": "getprop ro.serialno",
                "Build ID": "getprop ro.build.id",
                "Product Name": "getprop ro.product.name",
                "Device Name": "getprop ro.product.device",
                "AVD Name": "getprop ro.kernel.qemu.avd_name",
            }

            identifier_values = {}
            for prop_name, cmd in properties.items():
                try:
                    result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "shell", cmd],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        value = result.stdout.strip()
                        identifier_values[prop_name] = value if value and value != "null" else "Not set"
                except Exception:
                    identifier_values[prop_name] = "Error retrieving"

            # Get MAC addresses from network interfaces
            try:
                result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "shell", "ip link show"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    output = result.stdout
                    # Extract MAC addresses
                    mac_addresses = {}
                    current_interface = None
                    for line in output.split("\n"):
                        # Check for interface names
                        if ": " in line and not line.startswith(" "):
                            parts = line.split(": ")
                            if len(parts) >= 2:
                                current_interface = parts[1].split("@")[0]
                        # Check for MAC addresses
                        elif "link/ether" in line and current_interface:
                            parts = line.strip().split()
                            for i, part in enumerate(parts):
                                if part == "link/ether" and i + 1 < len(parts):
                                    mac_addresses[current_interface] = parts[i + 1]
                                    break

                    # Log commonly used interfaces
                    if "wlan0" in mac_addresses:
                        identifier_values["WiFi MAC"] = mac_addresses["wlan0"]
                    if "eth0" in mac_addresses:
                        identifier_values["Ethernet MAC"] = mac_addresses["eth0"]
            except Exception:
                pass

            # Format and log all identifiers in a single line for easy comparison
            id_parts = []
            for key, value in identifier_values.items():
                id_parts.append(f"{key}: {value}")

            logger.info(f"  {' | '.join(id_parts)}")

        except Exception as e:
            logger.error(f"Error logging device identifiers: {e}")

    def _is_package_manager_ready(self, emulator_id: str) -> bool:
        """Check if package manager is ready to accept commands."""
        logger.info(f"Emulator {emulator_id} boot completed, checking package manager...")

        # First, try to list packages
        if not self._can_list_packages(emulator_id):
            return False

        # Then verify we can query package paths
        if not self._can_query_package_path(emulator_id):
            return False

        logger.info(f"Package manager is ready on {emulator_id}")
        return True

    def _can_list_packages(self, emulator_id: str) -> bool:
        """Check if package manager can list packages."""
        try:
            pm_check = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "pm",
                    "list",
                    "packages",
                    "-3",  # List third-party packages only (faster)
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if pm_check.returncode != 0:
                logger.debug(f"Package manager not ready yet: {pm_check.stderr.strip()}")
                return False

            return True
        except Exception as e:
            logger.error(f"Error checking package list: {e}")
            return False

    def _can_query_package_path(self, emulator_id: str) -> bool:
        """Check if package manager can query package paths."""
        try:
            pm_path_check = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "pm",
                    "path",
                    "android",  # Check the core android package
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            if pm_path_check.returncode != 0 or not pm_path_check.stdout.strip():
                logger.debug("Package manager service not fully ready")
                return False

            return True
        except Exception as e:
            logger.error(f"Error checking package path: {e}")
            return False

    def save_snapshot(self, email: str) -> bool:
        """
        Save a snapshot of the current emulator state.

        Uses the default snapshot which is automatically loaded by the emulator
        on startup. This avoids accumulating multiple 4GB snapshots.

        Args:
            email: The user's email address

        Returns:
            True if snapshot was saved successfully, False otherwise
        """
        try:
            # Get the running emulator ID for this email
            emulator_id, _ = self.get_running_emulator(email)
            if not emulator_id:
                # Try using cached emulator if get_running_emulator fails
                avd_name = self._extract_avd_name_from_email(email)
                if avd_name and avd_name in self.running_emulators:
                    emulator_id, _ = self.running_emulators[avd_name]
                    logger.info(f"Using cached emulator ID {emulator_id} for snapshot")
                else:
                    logger.error(f"No running emulator found for {email}")
                    return False

            # Use avdmanager to save the snapshot
            # First, get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)
            if not avd_name:
                logger.error(f"Could not determine AVD name for {email}")
                return False

            # Method 1: Try using ADB emu command first (more reliable than telnet)
            try:
                logger.info(f"Attempting to save snapshot using adb emu command")
                adb_result = subprocess.run(
                    [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "emu",
                        "avd",
                        "snapshot",
                        "save",
                        "default_boot",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,  # Give it more time for snapshot creation
                )

                if adb_result.returncode == 0:
                    logger.info(f"Successfully saved snapshot for {email} on emulator {emulator_id}")
                    # Verify the snapshot was created
                    if self.has_snapshot(email, "default_boot"):
                        logger.info(f"Verified snapshot exists on disk")
                        return True
                    else:
                        logger.warning(f"Snapshot command succeeded but snapshot not found on disk")
                else:
                    logger.warning(f"ADB emu snapshot failed: {adb_result.stderr}")
            except Exception as adb_e:
                logger.warning(f"ADB emu method failed: {adb_e}")

            # Method 2: Fall back to telnet if ADB method fails
            logger.info("Falling back to telnet method for snapshot creation")
            # The emulator port is the last part of the emulator-xxxx ID
            emulator_port = int(emulator_id.split("-")[1])
            console_port = emulator_port - 1  # Console port is usually emulator_port - 1

            # First check if console port is available
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            try:
                result = sock.connect_ex(("localhost", console_port))
                sock.close()
                if result != 0:
                    logger.error(f"Console port {console_port} is not available")
                    return False
            except Exception as sock_e:
                logger.error(f"Error checking console port: {sock_e}")
                return False

            # Create the telnet command to save the snapshot
            telnet_commands = f"avd snapshot save default_boot\nquit\n"

            # Execute the command
            result = subprocess.run(
                ["telnet", "localhost", str(console_port)],
                input=telnet_commands,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and "OK" in result.stdout:
                logger.info(f"Successfully saved snapshot for {email} on emulator {emulator_id}")
                return True
            else:
                logger.error(f"Failed to save snapshot for {email}: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error saving snapshot for {email}: {e}")
            return False

    def has_snapshot(self, email: str, snapshot_name: str) -> bool:
        """
        Check if a snapshot exists for the given AVD.

        Args:
            email: The user's email address
            snapshot_name: Name of the snapshot to check

        Returns:
            True if snapshot exists, False otherwise
        """
        try:
            # Get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)
            if not avd_name:
                logger.error(f"Could not determine AVD name for {email}")
                return False

            # Check if the snapshot exists in the AVD directory
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            snapshots_dir = os.path.join(avd_path, "snapshots")
            snapshot_path = os.path.join(snapshots_dir, snapshot_name)

            exists = os.path.exists(snapshot_path)
            logger.info(
                f"Snapshot '{snapshot_name}' for {email} {'exists' if exists else 'does not exist'} at {snapshot_path}"
            )
            return exists

        except Exception as e:
            logger.error(f"Error checking if snapshot '{snapshot_name}' exists for {email}: {e}")
            return False

    def list_snapshots(self, email: str) -> List[str]:
        """
        List all available snapshots for the given AVD.

        Args:
            email: The user's email address

        Returns:
            List of snapshot names
        """
        try:
            # Get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)
            if not avd_name:
                logger.error(f"Could not determine AVD name for {email}")
                return []

            # List snapshots in the AVD directory
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            snapshots_dir = os.path.join(avd_path, "snapshots")

            if not os.path.exists(snapshots_dir):
                logger.info(f"No snapshots directory found for {email} at {snapshots_dir}")
                return []

            # List all subdirectories in the snapshots directory
            snapshots = []
            for entry in os.listdir(snapshots_dir):
                snapshot_path = os.path.join(snapshots_dir, entry)
                if os.path.isdir(snapshot_path):
                    snapshots.append(entry)

            logger.info(f"Found {len(snapshots)} snapshots for {email}: {snapshots}")
            return snapshots

        except Exception as e:
            logger.error(f"Error listing snapshots for {email}: {e}")
            return []

    def cleanup_old_snapshots(self, email: str, keep_count: int = 3) -> int:
        """
        Clean up old library park snapshots for the given email.

        Args:
            email: The user's email address
            keep_count: Number of recent snapshots to keep (default: 3)

        Returns:
            Number of snapshots deleted
        """
        try:
            # Get the AVD name for this email
            avd_name = self._extract_avd_name_from_email(email)
            if not avd_name:
                logger.error(f"Could not determine AVD name for {email}")
                return 0

            # Get the AVD identifier for snapshot naming
            if avd_name and avd_name.startswith("KindleAVD_"):
                avd_identifier = avd_name.replace("KindleAVD_", "")
            else:
                avd_identifier = email.replace("@", "_").replace(".", "_")

            # List all snapshots
            all_snapshots = self.list_snapshots(email)

            # Filter for library park snapshots
            library_snapshots = [s for s in all_snapshots if s.startswith(f"library_park_{avd_identifier}_")]

            if len(library_snapshots) <= keep_count:
                logger.info(
                    f"Found {len(library_snapshots)} library park snapshots for {email}, no cleanup needed (keep_count={keep_count})"
                )
                return 0

            # Sort by timestamp (newest first)
            library_snapshots.sort(reverse=True)

            # Determine which snapshots to delete
            snapshots_to_delete = library_snapshots[keep_count:]

            logger.info(f"Cleaning up {len(snapshots_to_delete)} old library park snapshots for {email}")
            logger.info(f"Keeping the {keep_count} most recent: {library_snapshots[:keep_count]}")
            logger.info(f"Deleting: {snapshots_to_delete}")

            # Delete the old snapshots
            deleted_count = 0
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            snapshots_dir = os.path.join(avd_path, "snapshots")

            for snapshot_name in snapshots_to_delete:
                snapshot_path = os.path.join(snapshots_dir, snapshot_name)
                try:
                    if os.path.exists(snapshot_path):
                        # Use shutil.rmtree to remove the entire snapshot directory
                        import shutil

                        shutil.rmtree(snapshot_path)
                        logger.info(f"Deleted snapshot: {snapshot_name}")
                        deleted_count += 1
                    else:
                        logger.warning(f"Snapshot not found at expected path: {snapshot_path}")
                except Exception as del_error:
                    logger.error(f"Error deleting snapshot {snapshot_name}: {del_error}")

            logger.info(f"Successfully deleted {deleted_count} old library park snapshots for {email}")
            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up old snapshots for {email}: {e}")
            return 0
