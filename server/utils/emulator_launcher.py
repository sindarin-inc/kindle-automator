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
                return False

            logger.info(f"Comparing AVD names: expected={email_avd}, actual={emulator_avd}")

            # Check if the AVD names match
            if emulator_avd == email_avd:
                logger.info(f"Emulator {emulator_id} is running with expected AVD {email_avd}")
                return True
            else:
                logger.warning(
                    f"Emulator {emulator_id} is running with unexpected AVD {emulator_avd}, expected {email_avd}"
                )
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
                    logger.info(f"Found AVD name for {emulator_id} via ro.kernel.qemu.avd_name: {avd_name}")
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
                    logger.info(f"Found AVD name for {emulator_id} via qemu.avd_name: {avd_name}")
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
                            logger.info(f"Found potential AVD-related property: {prop}")
                            # Extract property value if possible
                            if ": [" in prop and "]" in prop:
                                value = prop.split(": [")[1].split("]")[0]
                                if value:
                                    logger.info(f"Using AVD name from property: {value}")
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

    def launch_emulator(self, email: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Launch an emulator for the specified AVD and email, with proper VNC display coordination.

        Args:
            email: The user's email address

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

            # Check if there's a library snapshot for this AVD
            snapshot_name = None

            # First check if the user profile has a saved snapshot name
            try:
                from views.core.avd_creator import AVDCreator
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager()
                saved_snapshot = avd_manager.get_user_field(email, "last_snapshot")

                if saved_snapshot and self.has_snapshot(email, saved_snapshot):
                    snapshot_name = saved_snapshot
                    logger.info(f"Using saved snapshot '{snapshot_name}' from user profile for {email}")
                else:
                    # Refresh profiles to ensure we have the latest data
                    avd_manager._load_profiles_index()

                    # Check if this AVD was created from seed clone - if so, use seed clone snapshot
                    created_from_seed = avd_manager.get_user_field(email, "created_from_seed_clone")
                    logger.info(
                        f"Checking seed clone status for {email}: created_from_seed_clone={created_from_seed}"
                    )

                    if created_from_seed:
                        logger.info(
                            f"AVD for {email} was created from seed clone, checking for snapshot '{AVDCreator.SEED_CLONE_SNAPSHOT}'"
                        )
                        # Check if we have the seed clone snapshot
                        # List all available snapshots first
                        all_snapshots = self.list_snapshots(email)
                        logger.info(f"All available snapshots for {email}: {all_snapshots}")

                        has_seed_snapshot = self.has_snapshot(email, AVDCreator.SEED_CLONE_SNAPSHOT)
                        logger.info(
                            f"has_snapshot({email}, '{AVDCreator.SEED_CLONE_SNAPSHOT}') returned: {has_seed_snapshot}"
                        )

                        if has_seed_snapshot:
                            snapshot_name = AVDCreator.SEED_CLONE_SNAPSHOT
                            logger.info(f"Using seed clone snapshot '{snapshot_name}' for {email}")
                        else:
                            logger.warning(
                                f"User was created from seed clone but seed clone snapshot '{AVDCreator.SEED_CLONE_SNAPSHOT}' not found"
                            )

                    if not snapshot_name:
                        # Fall back to looking for the most recent library park snapshot
                        # Get the AVD identifier for snapshot naming
                        if avd_name and avd_name.startswith("KindleAVD_"):
                            avd_identifier = avd_name.replace("KindleAVD_", "")
                        else:
                            avd_identifier = email.replace("@", "_").replace(".", "_")

                        # List all snapshots and find the most recent library park snapshot
                        available_snapshots = self.list_snapshots(email)
                        library_snapshots = [
                            s for s in available_snapshots if s.startswith(f"library_park_{avd_identifier}_")
                        ]

                        if library_snapshots:
                            # Sort by timestamp embedded in the filename (newest first)
                            library_snapshots.sort(reverse=True)
                            snapshot_name = library_snapshots[0]
                            logger.info(
                                f"Found {len(library_snapshots)} library park snapshots, using most recent: {snapshot_name}"
                            )
                        else:
                            logger.info(f"No library park snapshots found for {avd_identifier}")
            except Exception as e:
                logger.warning(f"Error accessing user profile for snapshot lookup: {e}")
                # Proceed without the saved snapshot

            # Common emulator arguments for all platforms
            common_args = [
                "-avd",
                avd_name,
                "-no-audio",
                "-no-boot-anim",
                "-writable-system",
                "-port",
                str(emulator_port),
                # Keyboard configuration - disable soft keyboard
                "-prop",
                "hw.keyboard=yes",
                "-prop",
                "hw.keyboard.lid=yes",  # Force hardware keyboard mode
                "-prop",
                "hw.mainKeys=yes",  # Enable hardware keys
                # Status bar and nav buttons configuration
                "-prop",
                "hw.statusBar=no",  # Disable status bar
                "-prop",
                "hw.navButtons=no",  # Disable navigation buttons
                # Additional keyboard settings to disable soft keyboard
                "-prop",
                "qemu.settings.system.show_ime_with_hard_keyboard=0",
            ]

            # Check if we found a snapshot and add it to arguments if we did
            if snapshot_name:
                logger.info(f"Using snapshot '{snapshot_name}' for {email} for faster startup")
                common_args.extend(["-snapshot", snapshot_name])
            else:
                logger.info(f"No snapshot found for {email}, starting emulator normally")

            # Build platform-specific emulator command
            if platform.system() != "Darwin":
                # For Linux, use standard emulator with VNC with dynamic port
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-verbose",
                    "-feature",
                    "-accel",  # Disable hardware acceleration
                    "-gpu",
                    "swiftshader",
                ] + common_args
            elif self.host_arch == "arm64":
                # For ARM Macs, use Rosetta to run x86_64 emulator
                emulator_cmd = [
                    "arch",
                    "-x86_64",
                    f"{self.android_home}/emulator/emulator",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-feature",
                    "-HVF",  # Disable hardware virtualization
                    "-accel",
                    "off",
                ] + common_args
            else:
                # For Intel Macs
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-accel",
                    "on",
                    "-feature",
                    "HVF",
                ] + common_args

            # Create log files for debugging
            log_dir = "/var/log/emulator"
            os.makedirs(log_dir, exist_ok=True)
            stdout_log = os.path.join(log_dir, f"emulator_{avd_name}_stdout.log")
            stderr_log = os.path.join(log_dir, f"emulator_{avd_name}_stderr.log")

            # Start emulator in background with logs
            logger.info(
                f"Starting emulator for AVD {avd_name} (email {email}) on display :{display_num} and port {emulator_port}"
            )
            # logger.info(f"Emulator command: {' '.join(emulator_cmd)}")
            # logger.info(f"Logging stdout to {stdout_log} and stderr to {stderr_log}")

            with open(stdout_log, "w") as stdout_file, open(stderr_log, "w") as stderr_file:
                process = subprocess.Popen(
                    emulator_cmd,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd="/tmp",  # Run in /tmp to avoid permission issues
                )

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

            # 3. Update the user profile directly
            try:
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager()
                if email in avd_manager.profiles_index:
                    avd_manager.profiles_index[email]["emulator_id"] = emulator_id
                    avd_manager._save_profiles_index()
                    logger.info(f"Updated profile with emulator ID {emulator_id} for {email}")
            except Exception as e:
                logger.error(f"Error updating profile with emulator ID: {e}")

            # Now ensure VNC is running for this display after emulator is launched
            if platform.system() != "Darwin":
                self._ensure_vnc_running(display_num, email=email)

            # Check if emulator process is actually running
            if process.poll() is not None:
                # Process already exited
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
        # First check if we have the emulator in our cache to get its expected ID
        avd_name = self._extract_avd_name_from_email(email)
        expected_emulator_id = None
        if avd_name and avd_name in self.running_emulators:
            expected_emulator_id, _ = self.running_emulators[avd_name]

        # Get the emulator ID using get_running_emulator which handles AVD lookup
        emulator_id, _ = self.get_running_emulator(email)
        if not emulator_id:
            # Special handling: if we have an expected emulator ID in cache, check if it's actually running
            if expected_emulator_id:
                logger.info(
                    f"No emulator found via get_running_emulator for {email}, but have cached ID {expected_emulator_id}"
                )
                # Verify the cached emulator is still running
                if self._verify_emulator_running(expected_emulator_id, email):
                    logger.info(f"Cached emulator {expected_emulator_id} is still running, using it")
                    emulator_id = expected_emulator_id
                else:
                    logger.info(f"Cached emulator {expected_emulator_id} is not running anymore")

            if not emulator_id:
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

                return False

        try:
            # Check process first - is the emulator still running?
            ps_check = subprocess.run(
                ["pgrep", "-f", "qemu-system-x86_64"], check=False, capture_output=True, text=True
            )

            if ps_check.returncode != 0:
                logger.info(f"No emulator process found running")
                return False

            # First check if device is connected using our helper
            if not self._verify_emulator_running(emulator_id, email):
                return False

            # First check the device status - it might be in 'offline' state initially
            try:
                device_result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if emulator_id in device_result.stdout:
                    # Get the device status
                    devices_lines = device_result.stdout.strip().split("\n")
                    device_status = "unknown"

                    for line in devices_lines:
                        if emulator_id in line:
                            parts = line.split("\t")
                            if len(parts) >= 2:
                                device_status = parts[1].strip()
                                break

                    if device_status == "offline":
                        return False
                    elif device_status != "device":
                        logger.info(f"Emulator {emulator_id} is in unexpected state: {device_status}")
                        return False

                    logger.info(f"Emulator {emulator_id} is in 'device' state, checking boot completion")
                else:
                    logger.info(f"Emulator {emulator_id} not found in adb devices output")
                    return False
            except Exception as e:
                logger.error(f"Error checking device status: {e}")
                return False

            # Now check if the system has fully booted
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

            # logger.info(
            #     f"Boot completed check result: '{boot_completed.stdout.strip()}', return code: {boot_completed.returncode}"
            # )

            if boot_completed.returncode != 0:
                logger.warning(f"Boot completed check failed with error: {boot_completed.stderr.strip()}")
                return False

            result = boot_completed.stdout.strip() == "1"
            if result:
                logger.info(f"Emulator {emulator_id} is fully booted (sys.boot_completed=1)")
            else:
                logger.info(
                    f"Emulator {emulator_id} is still booting (sys.boot_completed={boot_completed.stdout.strip()})"
                )

            return result

        except Exception as e:
            logger.error(f"Error checking if emulator is ready for {email}: {e}")
            return False

    def save_snapshot(self, email: str, snapshot_name: str) -> bool:
        """
        Save a snapshot of the current emulator state.

        Args:
            email: The user's email address
            snapshot_name: Name of the snapshot to save

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
                logger.info(f"Attempting to save snapshot '{snapshot_name}' using adb emu command")
                adb_result = subprocess.run(
                    [
                        f"{self.android_home}/platform-tools/adb",
                        "-s",
                        emulator_id,
                        "emu",
                        "avd",
                        "snapshot",
                        "save",
                        snapshot_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,  # Give it more time for snapshot creation
                )

                if adb_result.returncode == 0:
                    logger.info(
                        f"Successfully saved snapshot '{snapshot_name}' for {email} on emulator {emulator_id}"
                    )
                    # Verify the snapshot was created
                    if self.has_snapshot(email, snapshot_name):
                        logger.info(f"Verified snapshot '{snapshot_name}' exists on disk")
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
            telnet_commands = f"avd snapshot save {snapshot_name}\nquit\n"

            # Execute the command
            result = subprocess.run(
                ["telnet", "localhost", str(console_port)],
                input=telnet_commands,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and "OK" in result.stdout:
                logger.info(
                    f"Successfully saved snapshot '{snapshot_name}' for {email} on emulator {emulator_id}"
                )
                return True
            else:
                logger.error(f"Failed to save snapshot '{snapshot_name}' for {email}: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error saving snapshot '{snapshot_name}' for {email}: {e}")
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
