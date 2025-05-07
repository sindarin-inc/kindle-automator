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
                    return user_entry.get("avd_name")

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

            logger.info(f"Using standard AVD name {avd_name} for {email}")

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

        email = get_sindarin_email()
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
            vnc_port = 5900 + display_num
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
                logger.error(f"Failed to start VNC server for display :{display_num}")
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
            if avd_name in self.running_emulators:
                emulator_id, display_num = self.running_emulators[avd_name]
                logger.info(
                    f"Emulator already running for AVD {avd_name} (email {email}): {emulator_id} on display :{display_num}"
                )
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
            return self.running_emulators[avd_name]

        return None, None

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
