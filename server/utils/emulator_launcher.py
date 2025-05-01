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

        # Maps AVD names to (emulator_id, display_num) tuples
        # IMPORTANT: We use AVD names as keys, NOT emails
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

            # Extract AVD name from email to find the correct profile
            normalized_form = "@" not in email and "_" in email and (email.endswith("_com") or email.endswith("_org") or email.endswith("_io"))
            avd_name = self._extract_avd_name_from_email(email)

            # Check the VNC instance map with AVD name
            if avd_name:
                for instance in self.vnc_instances["instances"]:
                    if instance["assigned_profile"] == avd_name:
                        logger.info(f"Found display for {email} with AVD {avd_name}: {instance['display']}")
                        return instance["display"]

            # For backward compatibility, also try by email directly
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    logger.warning(
                        f"Found display using legacy email match for {email}: {instance['display']}"
                    )
                    # Update to use AVD name for future lookups
                    if avd_name and not normalized_form:
                        logger.info(f"Updating legacy email assignment to AVD name {avd_name}")
                        instance["assigned_profile"] = avd_name
                        self._save_vnc_instance_map()
                    return instance["display"]

            # No display found
            logger.debug(f"No display found for {email} with AVD {avd_name}")
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
            # Extract AVD name from email to find the correct profile
            normalized_form = "@" not in email and "_" in email and (email.endswith("_com") or email.endswith("_org") or email.endswith("_io"))
            avd_name = self._extract_avd_name_from_email(email)

            # Look up the port using the AVD name
            if avd_name:
                for instance in self.vnc_instances["instances"]:
                    if instance["assigned_profile"] == avd_name:
                        logger.info(
                            f"Found emulator port for {email} with AVD {avd_name}: {instance['emulator_port']}"
                        )
                        return instance["emulator_port"]

            # For backward compatibility, also try by email
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    logger.warning(
                        f"Found emulator port using legacy email match for {email}: {instance['emulator_port']}"
                    )
                    # Update to use AVD name for future lookups
                    if avd_name and not normalized_form:
                        logger.info(f"Updating legacy email assignment to AVD name {avd_name}")
                        instance["assigned_profile"] = avd_name
                        self._save_vnc_instance_map()
                    return instance["emulator_port"]

            # No port found
            logger.debug(f"No emulator port found for {email} with AVD {avd_name}")
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
            # Extract AVD name from email to find the correct profile
            normalized_form = "@" not in email and "_" in email and (email.endswith("_com") or email.endswith("_org") or email.endswith("_io"))
            if normalized_form:
                logger.info(f"[PROFILE DEBUG] Detected already-normalized email in assign_display_to_profile: {email}")
            
            avd_name = self._extract_avd_name_from_email(email)
            logger.info(f"[PROFILE DEBUG] Got AVD name {avd_name} from _extract_avd_name_from_email")

            if not avd_name:
                logger.error(f"Could not extract AVD name for email {email}")
                logger.error("Cannot assign display without a valid AVD name")
                return None

            logger.info(f"Using AVD name '{avd_name}' as assigned_profile for email {email}")

            # First check if the profile already has an assigned display
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == avd_name:
                    logger.info(
                        f"Profile {email} with AVD {avd_name} already assigned to display :{instance['display']}"
                    )
                    return instance["display"]
                # Also check for legacy email assignment for backward compatibility
                elif instance["assigned_profile"] == email:
                    # Update to use AVD name instead
                    logger.info(f"Found legacy email assignment for {email}, updating to AVD name {avd_name}")
                    instance["assigned_profile"] = avd_name
                    self._save_vnc_instance_map()
                    return instance["display"]

            # Find an available instance
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] is None:
                    # Assign this instance to the profile using AVD name
                    instance["assigned_profile"] = avd_name
                    self._save_vnc_instance_map()
                    logger.info(f"Assigned display :{instance['display']} to AVD {avd_name} (email {email})")
                    return instance["display"]

            # No available instances, return None
            logger.error(f"No available displays for profile {email} with AVD {avd_name}")
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
            profiles_index_path = os.path.join(profiles_dir, "profiles_index.json")
            
            # First check if this email already has an entry in profiles_index
            if os.path.exists(profiles_index_path):
                with open(profiles_index_path, "r") as f:
                    profiles_index = json.load(f)
                    logger.info(f"[PROFILE DEBUG] Loaded profiles_index with keys: {list(profiles_index.keys())}")

                if email in profiles_index:
                    profile_entry = profiles_index.get(email)
                    logger.info(f"[PROFILE DEBUG] Found entry for {email}: {profile_entry}")

                    # Handle different formats (backward compatibility)
                    if isinstance(profile_entry, str):
                        logger.info(f"[PROFILE DEBUG] Using string format AVD name: {profile_entry}")
                        return profile_entry
                    elif isinstance(profile_entry, dict) and "avd_name" in profile_entry:
                        logger.info(f"[PROFILE DEBUG] Using dict format AVD name: {profile_entry['avd_name']}")
                        return profile_entry["avd_name"]

            # No existing entry, detect email format and create appropriate AVD name
            is_normalized = "@" not in email and "_" in email and (
                email.endswith("_com") or email.endswith("_org") or email.endswith("_io")
            )
            
            # Log email format detection for troubleshooting
            logger.info(f"[PROFILE DEBUG] Email format detection for {email}:")
            logger.info(f"[PROFILE DEBUG]   - Contains @: {'@' in email}")
            logger.info(f"[PROFILE DEBUG]   - Contains _: {'_' in email}")
            logger.info(f"[PROFILE DEBUG]   - Is normalized format: {is_normalized}")

            # Handle normalized vs. standard email formats
            if is_normalized:
                # Already normalized email format - just add prefix if needed
                logger.info(f"[PROFILE DEBUG] Input appears to be already normalized: {email}")
                avd_name = f"KindleAVD_{email}" if not email.startswith("KindleAVD_") else email
                logger.info(f"[PROFILE DEBUG] Using AVD name {avd_name} for already normalized email")
            else:
                # Standard email format - normalize it
                email_parts = email.split("@")
                if len(email_parts) != 2:
                    logger.error(f"[PROFILE DEBUG] Invalid email format: {email}")
                    return None

                username, domain = email_parts
                # Replace dots with underscores in both username and domain
                username = username.replace(".", "_")
                domain = domain.replace(".", "_")
                avd_name = f"KindleAVD_{username}_{domain}"
                logger.info(f"[PROFILE DEBUG] Normalized {email} to {avd_name}")

            logger.info(f"[PROFILE DEBUG] Using standard AVD name {avd_name} for {email}")

            # Register this profile in profiles_index
            try:
                # Ensure profiles directory exists
                os.makedirs(profiles_dir, exist_ok=True)
                
                # Create or load profiles_index
                if os.path.exists(profiles_index_path):
                    with open(profiles_index_path, "r") as f:
                        profiles_index = json.load(f)
                else:
                    profiles_index = {}
                    logger.info(f"[PROFILE DEBUG] Created new profiles_index")
                
                # Add or update the entry for this email
                profiles_index[email] = {"avd_name": avd_name}
                logger.info(f"[PROFILE DEBUG] Added profile entry for {email}")
                
                # Save to file
                with open(profiles_index_path, "w") as f:
                    json.dump(profiles_index, f, indent=2)
            except Exception as e:
                logger.error(f"[PROFILE DEBUG] Error updating profiles_index: {e}")
                
            # Return the AVD name
            logger.info(f"Registered profile for {email} with AVD {avd_name} in profiles_index")
            return avd_name

        except Exception as e:
            logger.error(f"Error extracting AVD name for email '{email}': {e}")
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

                time.sleep(2)

                # Verify Xvfb is running
                xvfb_check = subprocess.run(
                    ["pgrep", "-f", f"Xvfb :{display_num}"], capture_output=True, text=True
                )
                if xvfb_check.returncode != 0:
                    logger.error(f"Failed to start Xvfb for display :{display_num}")
                    return False

            # Check if x11vnc is running for this display
            vnc_check = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*:{display_num}"], capture_output=True, text=True
            )

            if vnc_check.returncode != 0:
                # Start VNC directly
                # Kill any existing VNC process for this display
                vnc_port = 5900 + display_num
                subprocess.run(["pkill", "-f", f"x11vnc.*rfbport {vnc_port}"], check=False)

                # Set up environment
                env = os.environ.copy()
                env["DISPLAY"] = f":{display_num}"

                # First find the Kindle app window ID using xwininfo
                try:
                    # Wait longer for the emulator window to appear
                    time.sleep(5)

                    # Use xwininfo with -tree to find the emulator window
                    list_windows = subprocess.run(
                        ["xwininfo", "-tree", "-root", "-display", f":{display_num}"],
                        capture_output=True,
                        text=True,
                        check=False,
                        env=env,
                        timeout=5,
                    )

                    window_id = None

                    if list_windows.returncode == 0:
                        # Look for the Android Emulator window with the Kindle AVD
                        window_lines = list_windows.stdout.splitlines()
                        emulator_window_line = None

                        # First, look for an emulator window with KindleAVD in the name
                        for line in window_lines:
                            if "Android Emulator" in line and "KindleAVD" in line:
                                emulator_window_line = line
                                break
                        else:
                            logger.warning(
                                f"Could not find any matching window on display :{display_num}, using full display"
                            )
                            window_id = None

                        # Extract window ID if we found a matching window
                        if emulator_window_line:
                            # The window ID is at the beginning of the line, like "0x400007"
                            parts = emulator_window_line.split()
                            if parts and parts[0].startswith("0x"):
                                window_id = parts[0]
                                # logger.info(
                                #     f"Found emulator window ID: {window_id} from line: {emulator_window_line}"
                                # )

                        # Log the full list of windows for debugging
                        # logger.info(f"Available windows on display :{display_num}:\n{list_windows.stdout}")

                    # Just use the window_id we found
                    if not window_id:
                        logger.warning(
                            f"Could not find any matching window on display :{display_num}, using full display"
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
                time.sleep(2)

                # Verify VNC is running
                vnc_check = subprocess.run(
                    ["pgrep", "-f", f"x11vnc.*rfbport {vnc_port}"], capture_output=True, text=True
                )
                if vnc_check.returncode != 0:
                    logger.error(f"Failed to start VNC server for display :{display_num}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error ensuring VNC is running for display :{display_num}: {e}")
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

            # Get or extract email if needed (for logging and display assignment)
            if not email:
                email = self._extract_email_from_avd_name(avd_name)
                if not email:
                    logger.warning(f"Could not extract email from AVD name {avd_name}, using 'default'")
                    email = "default"

            # IMPORTANT: Use AVD name as key for running_emulators, not email
            # Check if emulator already running for this AVD
            if avd_name in self.running_emulators:
                emulator_id, display_num = self.running_emulators[avd_name]
                logger.info(
                    f"Emulator already running for AVD {avd_name} (email {email}): {emulator_id} on display :{display_num}"
                )
                return True, emulator_id, display_num

            # Get assigned display and emulator port for this profile
            # We still need to use email for backward compatibility with VNC instance manager
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

            # Common emulator arguments for all platforms
            common_args = [
                "-avd",
                avd_name,
                "-no-audio",
                "-no-boot-anim",
                "-no-snapshot",
                "-no-snapshot-load",
                "-no-snapshot-save",
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

            # IMPORTANT: Store the running emulator info with the AVD name as key, not email
            self.running_emulators[avd_name] = (emulator_id, display_num)

            # Now ensure VNC is running for this display after emulator is launched
            if platform.system() != "Darwin":
                self._ensure_vnc_running(display_num)

            # Check if emulator process is actually running
            if process.poll() is not None:
                # Process already exited
                exit_code = process.returncode
                logger.error(f"Emulator process exited immediately with code {exit_code}")
                logger.error(f"Check logs at {stdout_log} and {stderr_log}")
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
            # Extract AVD name from email to find the correct profile
            avd_name = self._extract_avd_name_from_email(email)

            # First try to find and release by AVD name
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == avd_name:
                    instance["assigned_profile"] = None
                    self._save_vnc_instance_map()
                    logger.info(f"Released AVD {avd_name} (email {email}) from VNC instance map")
                    return True

            # For backward compatibility, also try by email
            for instance in self.vnc_instances["instances"]:
                if instance["assigned_profile"] == email:
                    instance["assigned_profile"] = None
                    self._save_vnc_instance_map()
                    logger.info(f"Released profile by legacy email {email} from VNC instance map")
                    return True

            logger.warning(f"No VNC instance found for profile {email} with AVD {avd_name}")
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
                logger.info(
                    f"Stopping emulator {emulator_id} for AVD {avd_name} (email {email}) on display :{display_num}"
                )

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
                logger.info(
                    f"Stopping emulator {emulator_id} for {email} on display :{display_num} (legacy key)"
                )

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
        # First try to get the AVD name for this email
        avd_name = self._extract_avd_name_from_email(email)

        # If we have an AVD name and it's in running_emulators, use that
        if avd_name and avd_name in self.running_emulators:
            logger.info(f"Found running emulator for AVD {avd_name} (email {email})")
            return self.running_emulators[avd_name]

        # For backward compatibility during transition, also check using email
        # This branch should be removed after full transition to AVD names
        if email in self.running_emulators:
            logger.warning(
                f"Found running emulator using legacy email key for {email} - should migrate to AVD name"
            )
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
        # Get the emulator ID using get_running_emulator which handles AVD lookup
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

            return result

        except Exception as e:
            logger.error(f"Error checking if emulator is ready for {email}: {e}")
            return False
