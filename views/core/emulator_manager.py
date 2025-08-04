import logging
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from server.utils.android_path_utils import get_android_home, get_avd_dir
from server.utils.emulator_launcher import EmulatorLauncher
from server.utils.request_utils import get_sindarin_email
from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)

# Singleton instance
_instance = None


class EmulatorManager:
    """
    Manages the lifecycle of Android emulators.

    This is a singleton class shared between all users. User-specific state
    is stored in VNCInstanceManager instead.

    Handles starting, stopping, and monitoring emulator instances.
    """

    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance of EmulatorManager.

        Returns:
            EmulatorManager: The singleton instance
        """
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    def __init__(self):
        # Check if this is being called directly or through get_instance()
        if _instance is not None and _instance is not self:
            logger.warning("EmulatorManager initialized directly. Use get_instance() instead.")

        # Use centralized path determination
        self.android_home = get_android_home()
        self.avd_dir = get_avd_dir()

        # Detect host architecture
        self.host_arch = self._detect_host_architecture()

        logger.debug(f"EmulatorManager initialized with:")
        logger.debug(f"  android_home: {self.android_home}")
        logger.debug(f"  avd_dir: {self.avd_dir}")
        logger.debug(f"  host_arch: {self.host_arch}")

        self.emulator_launcher = EmulatorLauncher(self.android_home, self.avd_dir, self.host_arch)

    def _detect_host_architecture(self) -> str:
        """Detect the host system architecture."""
        machine = platform.machine().lower()

        if machine in ["x86_64", "amd64"]:
            return "x86_64"
        elif machine in ["aarch64", "arm64"]:
            return "arm64"
        elif machine in ["armv7l", "armv7"]:
            return "arm"
        elif machine in ["i386", "i686"]:
            return "x86"
        else:
            logger.warning(f"Unknown architecture: {machine}, defaulting to x86_64")
            return "x86_64"

    def is_emulator_running(self, email: str) -> bool:
        """Check if an emulator is currently running for a specific email."""
        try:
            # Execute with a shorter timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,  # Add a timeout to prevent potential hang
            )

            # More precise check - look for "emulator-" followed by a port number
            if result.returncode != 0:
                return False

            lines = [
                line.strip() for line in result.stdout.splitlines() if line.strip().startswith("emulator-")
            ]

            # Corroborate with the profiles index
            if lines:
                vnc_manager = VNCInstanceManager.get_instance()
                emulator_id = vnc_manager.get_emulator_id(email)
                if emulator_id and any(emulator_id in line for line in lines):
                    return True
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is running, assuming it's not running")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}", exc_info=True)
            return False

    def stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Public method for external use.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        success = self._stop_specific_emulator(emulator_id)
        if success:
            # Release the VNC instance assignment
            vnc_manager = VNCInstanceManager.get_instance()

            # Find the email by looking through all instances
            for instance in vnc_manager.instances:
                if instance.get("emulator_id") == emulator_id and instance.get("assigned_profile"):
                    email_to_release = instance.get("assigned_profile")
                    vnc_manager.release_instance_from_profile(email_to_release)
                    logger.info(f"Released VNC instance for {email_to_release}")
                    break

        return success

    def _stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Internal implementation.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Stopping specific emulator: {emulator_id}")

            # First try graceful shutdown
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                check=False,
                timeout=5,
            )

            # Wait briefly for emulator to shut down
            for i in range(10):
                devices_result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if emulator_id not in devices_result.stdout:
                    logger.info(f"Emulator {emulator_id} stopped successfully")
                    return True

                logger.info(f"Waiting for emulator {emulator_id} to stop... ({i+1}/10)")
                time.sleep(1)

            # If still running, force kill
            logger.warning(f"Emulator {emulator_id} didn't stop gracefully, forcing termination")
            return False

        except Exception as e:
            logger.error(f"Error stopping emulator {emulator_id}: {e}", exc_info=True)
            return False

    def start_emulator_with_retries(self, email: str) -> bool:
        """
        Start the specified AVD in headless mode.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # Check if we have emulator info in VNC instance manager for this email
            vnc_manager = VNCInstanceManager.get_instance()
            emulator_id = vnc_manager.get_emulator_id(email)

            if emulator_id:
                logger.info(f"Found emulator info for {email}: {emulator_id}")

                # Verify the emulator is still running
                if self.emulator_launcher._verify_emulator_running(emulator_id, email):
                    logger.info(f"Emulator {emulator_id} is still running for {email}")
                    return True
                else:
                    logger.info(f"Emulator {emulator_id} is no longer running, clearing from VNC instance")
                    vnc_manager.set_emulator_id(email, None)

            # First check for stale cache entries and clean them before launching
            avd_name = self.emulator_launcher._extract_avd_name_from_email(email)
            if avd_name and avd_name in self.emulator_launcher.running_emulators:
                emulator_id, display_num = self.emulator_launcher.running_emulators[avd_name]

                # Verify the emulator is actually running via adb devices
                if not self.emulator_launcher._verify_emulator_running(emulator_id, email):
                    # Emulator not actually running according to adb, remove from cache
                    logger.info(
                        f"Cached emulator {emulator_id} for AVD {avd_name} not found in adb devices, removing from cache before launch"
                    )
                    # Remove stale cache entry before launching
                    del self.emulator_launcher.running_emulators[avd_name]

            # Directly check adb devices before launching to know the initial state
            try:
                devices_before = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                logger.debug(f"ADB devices before launch: {devices_before.stdout.strip()}")
            except Exception as e:
                logger.error(f"Error checking ADB devices before launch: {e}", exc_info=True)

            # Now use the Python-based launcher
            # For seed clone, always use cold boot to ensure device randomization
            from views.core.avd_creator import AVDCreator

            cold_boot = email == AVDCreator.SEED_CLONE_EMAIL
            if cold_boot:
                logger.info(f"Launching seed clone with cold boot to allow device randomization")
            success, emulator_id, display_num = self.emulator_launcher.launch_emulator(
                email, cold_boot=cold_boot
            )

            if success:
                logger.debug(f"Emulator {emulator_id} launched successfully on display :{display_num}")

                # Store the emulator ID in VNC instance manager
                vnc_manager.set_emulator_id(email, emulator_id)
                logger.debug(f"Stored emulator info for {email}: {emulator_id}")

                # Check adb devices immediately after launch to see if it's detected
                try:
                    devices_after = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    logger.debug(f"ADB devices immediately after launch: {devices_after.stdout.strip()}")

                    # Check if our emulator ID appears in the output
                    if emulator_id in devices_after.stdout:
                        logger.debug(f"Emulator {emulator_id} is visible to ADB immediately after launch")
                    else:
                        logger.warning(
                            f"Emulator {emulator_id} is NOT visible to ADB immediately after launch"
                        )
                except Exception as e:
                    logger.error(f"Error checking ADB devices after launch: {e}", exc_info=True)

                # Wait for emulator to boot with active polling (should take ~7-8 seconds)
                logger.debug("Waiting for emulator to boot...")
                deadline = time.time() + 45  # 45 seconds timeout

                # Active polling approach - check every second and log consistently
                check_count = 0
                last_check_time = 0
                while time.time() < deadline:
                    current_time = time.time()

                    # Ensure we're not logging more than once per second
                    if current_time - last_check_time >= 1.0:
                        check_count += 1
                        last_check_time = current_time

                        # Log each check with timestamp
                        logger.debug(f"Checking if emulator is ready for {email} (check #{check_count})")

                        # Check if emulator is ready through the launcher
                        if self.emulator_launcher.is_emulator_ready(email):
                            # Apply memory optimizations if enabled
                            self._apply_memory_optimizations(email, emulator_id)
                            return True

                logger.error(
                    f"Timeout waiting for emulator to boot for {email} after 45 seconds and {check_count} checks",
                    exc_info=True,
                )

                # Check for crash dialog on timeout
                if self.emulator_launcher._check_and_dismiss_crash_dialog(display_num):
                    logger.warning("Found and dismissed crash dialog after emulator boot timeout")

                return False
            else:
                logger.error(f"Failed to launch emulator", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"Error starting emulator: {e}", exc_info=True)
            return False

    def _apply_memory_optimizations(self, email: str, emulator_id: str) -> None:
        """
        Apply memory optimization settings to prevent OOM kills.
        Only applied once per AVD, tracked in user profile.

        Args:
            email: User email to check preferences
            emulator_id: The emulator ID (e.g. emulator-5554)
        """
        try:
            # Check if we've already applied optimizations to this AVD
            from views.core.avd_profile_manager import AVDProfileManager

            profile_manager = AVDProfileManager.get_instance()

            # Check if memory optimizations have been applied to this AVD
            memory_optimized = profile_manager.get_user_field(
                email, "memory_optimizations_applied", default=False, section="emulator_settings"
            )

            if memory_optimized:
                logger.debug(f"Memory optimizations already applied to AVD for {email}")
                return

            logger.info(f"Applying memory optimization settings for {email}...")

            # Build adb command prefix
            adb_prefix = [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "shell"]

            # List of commands to run
            optimization_commands = [
                # Disable stylus features (Android 36)
                (
                    ["settings", "put", "secure", "stylus_handwriting_enabled", "0"],
                    "Disabling stylus handwriting",
                ),
                (
                    ["settings", "put", "global", "stylus_handwriting", "0"],
                    "Disabling global stylus handwriting",
                ),
                (["settings", "put", "secure", "stylus_buttons_enabled", "0"], "Disabling stylus buttons"),
                (
                    ["settings", "put", "global", "pen_detachment_alert", "0"],
                    "Disabling pen detachment alert",
                ),
                # Disable Play Store (prevents auto-updates)
                (["pm", "disable-user", "com.android.vending"], "Disabling Play Store"),
                # Disable YouTube (prevents background crashes)
                (["pm", "disable-user", "com.google.android.youtube"], "Disabling YouTube"),
                # Disable Gboard to prevent soft keyboard from appearing
                (["pm", "disable-user", "com.google.android.inputmethod.latin"], "Disabling Gboard"),
                # Configure system to think hardware keyboard is connected
                (
                    ["settings", "put", "secure", "show_ime_with_hard_keyboard", "0"],
                    "Hide IME with hardware keyboard",
                ),
                (["settings", "put", "secure", "default_input_method", "null"], "Clear default input method"),
                # Disable voice input settings
                (
                    ["settings", "put", "secure", "voice_interaction_service", ""],
                    "Disable voice interaction service",
                ),
                (
                    ["settings", "put", "secure", "voice_recognition_service", ""],
                    "Disable voice recognition service",
                ),
                # Disable auto app updates
                (["settings", "put", "global", "auto_update_apps", "0"], "Disabling auto app updates"),
                # Deny background execution for Play Services
                (
                    ["cmd", "appops", "set", "com.google.android.gms", "RUN_IN_BACKGROUND", "deny"],
                    "Denying background execution for Play Services",
                ),
                # Deny background execution for Play Store
                (
                    ["cmd", "appops", "set", "com.android.vending", "RUN_IN_BACKGROUND", "deny"],
                    "Denying background execution for Play Store",
                ),
                # Disable all animations (frees memory)
                (["settings", "put", "global", "window_animation_scale", "0"], "Disabling window animations"),
                (
                    ["settings", "put", "global", "transition_animation_scale", "0"],
                    "Disabling transition animations",
                ),
                (
                    ["settings", "put", "global", "animator_duration_scale", "0"],
                    "Disabling animator duration",
                ),
                # Aggressive memory management settings
                (["settings", "put", "global", "ram_expand_size", "0"], "Setting RAM expand size to 0"),
                (["settings", "put", "global", "zram_enabled", "0"], "Disabling ZRAM"),
                # Force stop unnecessary services
                (
                    ["am", "force-stop", "com.google.android.googlequicksearchbox"],
                    "Force stopping Google Search",
                ),
                (
                    ["am", "force-stop", "com.google.android.apps.wellbeing"],
                    "Force stopping Digital Wellbeing",
                ),
                (["am", "force-stop", "com.google.android.youtube"], "Force stopping YouTube"),
                # Trim memory from system processes
                (
                    ["am", "send-trim-memory", "com.google.android.gms", "RUNNING_CRITICAL"],
                    "Trimming memory from Play Services",
                ),
                (
                    ["am", "send-trim-memory", "com.android.systemui", "RUNNING_CRITICAL"],
                    "Trimming memory from System UI",
                ),
            ]

            # Run each command
            keyboard_disabled = False
            for cmd, description in optimization_commands:
                try:
                    full_cmd = adb_prefix + cmd
                    logger.debug(f"{description}...")
                    result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=5, check=False)

                    # Check if keyboard-related commands were successful
                    if (
                        any(
                            keyword in description
                            for keyword in [
                                "Disabling Gboard",
                                "Hide IME with hardware keyboard",
                                "Clear default input method",
                            ]
                        )
                        and result.returncode == 0
                    ):
                        keyboard_disabled = True
                        logger.info(f"Keyboard configuration successful: {description}")
                        logger.debug(f"Setting keyboard_disabled=True after: {description}")

                    # Only log errors, not successes
                    if result.returncode != 0 and result.stderr:
                        illegal_arg_exception = None
                        for line in result.stderr.splitlines():
                            if "java.lang.IllegalArgumentException:" in line:
                                illegal_arg_exception = line[line.find(":") + 1 :]
                                break
                        logger.warning(f"Command failed: {' '.join(cmd)} - {illegal_arg_exception}")

                except subprocess.TimeoutExpired:
                    logger.warning(f"Command timed out: {' '.join(cmd)}")
                except Exception as cmd_e:
                    logger.warning(f"Error running command {' '.join(cmd)}: {cmd_e}")

            # Mark optimizations as applied for this AVD
            profile_manager.set_user_field(
                email, "memory_optimizations_applied", True, section="emulator_settings"
            )
            profile_manager.set_user_field(
                email,
                "memory_optimization_timestamp",
                datetime.now(timezone.utc),
                section="emulator_settings",
            )
            # Store keyboard disabled state
            logger.debug(f"keyboard_disabled flag is: {keyboard_disabled}")
            if keyboard_disabled:
                logger.info(f"Setting keyboard_disabled=True in profile for {email}")
                success = profile_manager.set_user_field(
                    email, "keyboard_disabled", True, section="emulator_settings"
                )
                logger.debug(f"keyboard_disabled flag set result: {success}")
            else:
                logger.warning(f"keyboard_disabled flag is False, not setting in profile for {email}")

            logger.info(f"Memory optimization settings applied successfully for {email}")

        except Exception as e:
            logger.error(f"Error applying memory optimizations for {email}: {e}", exc_info=True)
            # Continue even if optimizations fail - they're not critical
