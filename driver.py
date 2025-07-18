import logging
import os
import platform
import subprocess
import tempfile
import time
from functools import wraps
from typing import Optional

import requests
from appium import webdriver
from appium.options.android import UiAutomator2Options
from flask import current_app
from urllib3.exceptions import MaxRetryError

from server.utils.appium_driver import AppiumDriver
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class Driver:
    def __init__(self):
        if hasattr(self, "_initialized_attributes"):
            logger.error(f"Driver already initialized, instance: {self}", exc_info=True)
            return
        self.driver = None
        self.device_id = None
        self.automator = None  # Reference to the automator instance
        self.appium_port = None  # Must be set
        self._session_retries = 0
        self._reconnecting = False  # Flag to prevent infinite recursion
        self._max_session_retries = 2
        self._initialized_attributes = True

    def _get_emulator_device_id(self, specific_device_id: Optional[str] = None) -> Optional[str]:
        """
        Get the emulator device ID from adb devices, optionally targeting a specific device.

        Args:
            specific_device_id: Optional device ID to specifically connect to (e.g., 'emulator-5554')

        Returns:
            Optional[str]: The device ID if found, None otherwise
        """
        email = get_sindarin_email()

        try:
            # If we have a specific device ID to use, check if it's available first
            if specific_device_id:
                result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)

                if specific_device_id in result.stdout and "device" in result.stdout:
                    # Verify this is actually a working emulator
                    try:
                        verify_result = subprocess.run(
                            ["adb", "-s", specific_device_id, "shell", "getprop", "ro.product.model"],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=5,
                        )
                        return specific_device_id
                    except Exception as e:
                        logger.warning(f"Could not verify specific device {specific_device_id}: {e}")
                        # Failed to verify specific device - return None instead of falling back to any device
                        logger.error(
                            f"Requested specific device {specific_device_id} could not be verified for email={email}",
                            exc_info=True,
                        )
                        return None
                else:
                    logger.warning(
                        f"Specified device ID {specific_device_id} not found or not ready for email={email}"
                    )
                    # Do not continue to regular device search if a specific device was requested
                    # but is not available. This prevents using the wrong device.
                    logger.error(
                        f"Requested specific device {specific_device_id} was not found or is not ready for email={email}",
                        exc_info=True,
                    )
                    return None

            # CRITICAL: Do NOT search for ANY available emulator when no specific device is requested
            # This prevents cross-user emulator access in production
            logger.error(
                f"No specific device requested for email={email}. "
                f"Refusing to search for ANY available emulator to prevent cross-user access."
            )
            return None
        except Exception as e:
            logger.error(f"Error getting emulator device ID: {e}", exc_info=True)
            return None

    def _disable_hw_overlays(self) -> bool:
        """Disable hardware overlays to improve WebView visibility."""
        try:
            # Check if we already applied this setting to the current emulator
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            # If this is the same device and we already set hw_overlays_disabled, skip
            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "hw_overlays_disabled", False, section="emulator_settings"
                )
            ):
                return True

            # Check current state
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", "settings", "get", "global", "debug.hw.overlay"],
                check=True,
                capture_output=True,
                text=True,
            )
            current_state = result.stdout.strip()

            if current_state == "1":
                # Record this setting in the profile
                self._update_profile_setting("hw_overlays_disabled", True)
                return True

            logger.info(f"Disabling HW overlays on device {self.device_id}")
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", "settings", "put", "global", "debug.hw.overlay", "1"],
                check=True,
                capture_output=True,
                text=True,
            )

            # Record this setting in the profile
            self._update_profile_setting("hw_overlays_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to handle HW overlays: {e.stderr}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error handling HW overlays: {e}", exc_info=True)
            return False

    def _update_profile_setting(self, setting_name: str, value: bool) -> None:
        """Update a setting in the current profile under emulator_settings.

        Args:
            setting_name: The name of the setting to update
            value: The value to set
        """
        try:
            profile = self.automator.profile_manager.get_current_profile()
            if not profile:
                logger.warning("Cannot update profile setting: no current profile")
                return

            email = get_sindarin_email()
            avd_name = profile.get("avd_name")

            if email and avd_name:
                # Use the profile manager's set_user_field method to properly store under emulator_settings
                self.automator.profile_manager.set_user_field(
                    email, setting_name, value, section="emulator_settings"
                )

                logger.info(f"Updated profile setting emulator_settings.{setting_name}={value} for {email}")
            else:
                logger.error(
                    f"Failed to update profile setting: {setting_name}={value} for {email}", exc_info=True
                )
        except Exception as e:
            logger.error(f"Error updating profile setting {setting_name}: {e}", exc_info=True)
            # Continue execution even if we can't update the profile

    def _clean_old_version_info(self, email: str) -> None:
        """Remove Kindle version information from preferences if present.

        Args:
            email: Email address of the profile
        """
        try:
            profile_index = self.automator.profile_manager.profiles_index

            if email in profile_index and "preferences" in profile_index[email]:
                preferences = profile_index[email]["preferences"]
                cleaned = False

                # Remove version info from preferences if present
                if "kindle_version_name" in preferences:
                    preferences.pop("kindle_version_name")
                    cleaned = True
                if "kindle_version_code" in preferences:
                    preferences.pop("kindle_version_code")
                    cleaned = True

                # Save changes if we cleaned anything
                if cleaned:
                    self.automator.profile_manager._save_profiles_index()
        except Exception as e:
            logger.error(f"Error cleaning old version info for {email}: {e}", exc_info=True)

    def _update_kindle_version_in_profile(self, version_name: str, version_code: int) -> None:
        """Update Kindle version information in the current profile.

        Args:
            version_name: The version name (e.g. "8.121.0.100")
            version_code: The version code (e.g. 1286055411)
        """
        profile = self.automator.profile_manager.get_current_profile()
        if not profile:
            logger.warning("Cannot update Kindle version in profile: no current profile")
            return

        email = profile.get("email") or profile.get("assigned_profile")
        avd_name = profile.get("avd_name")

        if email and avd_name:
            # Update version info at top level using generic field setter if available
            self.automator.profile_manager.set_user_field(email, "kindle_version_name", version_name)
            self.automator.profile_manager.set_user_field(email, "kindle_version_code", str(version_code))

            logger.info(
                f"Updated Kindle version in profile to {version_name} (code: {version_code}) for {email}"
            )

    def _disable_animations(self) -> bool:
        """Disable all system animations to improve reliability."""
        try:
            # Check if we already applied this setting to the current emulator
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            # If this is the same device and we already set animations_disabled, skip
            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "animations_disabled", False, section="emulator_settings"
                )
            ):
                return True

            logger.info(f"Disabling system animations on device {self.device_id}")

            # Disable all three types of Android animations
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "window_animation_scale",
                    "0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "transition_animation_scale",
                    "0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "animator_duration_scale",
                    "0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Record this setting in the profile
            self._update_profile_setting("animations_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to disable animations: {e.stderr}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error disabling animations: {e}", exc_info=True)
            return False

    def _disable_sleep(self) -> bool:
        """Disable sleep and app standby modes to prevent the device and app from sleeping."""
        try:
            # Check if we already applied this setting to the current emulator
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            # If this is the same device and we already set sleep_disabled, skip
            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "sleep_disabled", False, section="emulator_settings"
                )
            ):
                return True

            logger.info(f"Disabling sleep and app standby for device {self.device_id}")

            # Set the device to never sleep when plugged in
            # Value 7 means stay on while power AND USB AND wireless charging
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "stay_on_while_plugged_in",
                    "7",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Disable app standby and doze mode for the Kindle app
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "dumpsys",
                    "deviceidle",
                    "whitelist",
                    "+com.amazon.kindle",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Set screen timeout to never (max value for Android settings)
            # 2147483647 is max integer value (around 24.8 days) Android allows
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "system",
                    "screen_off_timeout",
                    "2147483647",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Record this setting in the profile
            self._update_profile_setting("sleep_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to disable sleep: {e.stderr}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error disabling sleep: {e}", exc_info=True)
            return False

    def _disable_status_bar(self) -> bool:
        """Hide the status bar at runtime using ADB."""
        try:
            # Check if we already applied this setting to the current emulator
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            # If this is the same device and we already set status_bar_disabled, skip
            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "status_bar_disabled", False, section="emulator_settings"
                )
            ):
                return True

            logger.info(f"Hiding status bar for device {self.device_id}")

            # Run the ADB command to hide the status bar using immersive mode
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "policy_control",
                    "immersive.status=*",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Record this setting in the profile
            self._update_profile_setting("status_bar_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to hide status bar: {e.stderr}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error hiding status bar: {e}", exc_info=True)
            return False

    def _disable_auto_updates(self) -> bool:
        """Disable automatic app updates to prevent apps from being killed during updates."""
        try:
            # Check if we already applied this setting to the current emulator
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            # If this is the same device and we already set auto_updates_disabled, skip
            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "auto_updates_disabled", False, section="emulator_settings"
                )
            ):
                return True

            logger.info(f"Disabling automatic app updates for device {self.device_id}")

            # Disable automatic app updates globally
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "auto_update_disabled",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Also disable auto-update over WiFi only
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "update_over_wifi_only",
                    "0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Disable background data for Play Store to prevent updates
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "cmd",
                    "netpolicy",
                    "set",
                    "restrict-background",
                    "true",
                    "com.android.vending",
                ],
                capture_output=True,
                text=True,
            )

            # Record this setting in the profile
            self._update_profile_setting("auto_updates_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to disable auto updates: {e.stderr}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error disabling auto updates: {e}", exc_info=True)
            return False

    def _cleanup_old_sessions(self):
        """Clean up any existing UiAutomator2 sessions."""
        email = get_sindarin_email()

        try:
            # CRITICAL: Verify this device belongs to the current user before cleaning
            try:
                avd_result = subprocess.run(
                    ["adb", "-s", self.device_id, "emu", "avd", "name"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if avd_result.returncode == 0:
                    device_avd = avd_result.stdout.strip()
                    # Handle "AVD_NAME\nOK" format
                    if "\n" in device_avd:
                        device_avd = device_avd.split("\n")[0].strip()

                    logger.info(f"Device {self.device_id} is running AVD: {device_avd}")

                    # Get expected AVD name for this email
                    profile = self.automator.profile_manager.get_current_profile()
                    expected_avd = profile.get("avd_name") if profile else None

                    if expected_avd and device_avd != expected_avd:
                        logger.error(
                            f"CRITICAL: Device {self.device_id} is running AVD {device_avd} "
                            f"but email {email} expects AVD {expected_avd}. REFUSING to clean sessions to prevent "
                            f"cross-user interference!"
                        )
                        return False
                else:
                    logger.warning(f"Could not determine AVD for device {self.device_id}")
            except Exception as e:
                logger.warning(f"Error checking AVD name: {e}")

            # Instead of clearing data, just force-stop the Appium process
            # This avoids triggering logout in the Kindle app
            try:
                subprocess.run(
                    [
                        "adb",
                        "-s",
                        self.device_id,
                        "shell",
                        "am",
                        "force-stop",
                        "io.appium.uiautomator2.server",
                    ],
                    capture_output=True,
                    text=True,
                )
                logger.info(f"Force-stopped io.appium.uiautomator2.server successfully")
            except Exception:
                pass  # It's okay if the process wasn't running

            return True
        except Exception as e:
            logger.error(f"Error cleaning up old sessions for email={email}: {e}", exc_info=True)
            return False

    def _is_kindle_installed(self) -> bool:
        """Check if the Kindle app is installed on the device."""
        try:
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", "pm", "list", "packages", "com.amazon.kindle"],
                capture_output=True,
                text=True,
                check=True,
            )
            return "com.amazon.kindle" in result.stdout
        except Exception as e:
            logger.error(f"Error checking Kindle installation: {e}", exc_info=True)
            return False

    def _get_installed_kindle_version(self) -> tuple:
        """Get the version of the installed Kindle app.

        Returns:
            tuple: (version_name, version_code) or (None, None) if failed
        """
        try:
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", "dumpsys", "package", "com.amazon.kindle"],
                capture_output=True,
                text=True,
                check=True,
            )

            version_name = None
            version_code = None

            for line in result.stdout.splitlines():
                if "versionName=" in line:
                    version_name = line.split("versionName=")[1].strip()
                if "versionCode=" in line:
                    # Extract only the version code number
                    version_code_str = line.split("versionCode=")[1].strip().split(" ")[0]
                    try:
                        version_code = int(version_code_str)
                    except ValueError:
                        logger.error(f"Could not parse version code: {version_code_str}", exc_info=True)

            return (version_name, version_code)
        except Exception as e:
            logger.error(f"Error getting installed Kindle version: {e}", exc_info=True)
            return (None, None)

    def _get_apk_version(self, apk_path) -> tuple:
        """Extract version information from an APK file.

        Args:
            apk_path: Path to the APK file

        Returns:
            tuple: (version_name, version_code) or (None, None) if failed
        """
        try:
            # Parse the filename to extract version info
            # Format is usually: com.amazon.kindle_8.121.0.100(2.0.40027.0)-1286055411_minAPI28(arm64-v8a)(nodpi)_apkmirror.com.apk
            filename = os.path.basename(apk_path)

            # Extract version name from filename
            version_name_match = None
            if "_" in filename and "(" in filename:
                version_part = filename.split("_")[1]
                if "(" in version_part:
                    version_name_match = version_part.split("(")[0]

            # Extract version code from filename (usually after the hyphen)
            version_code = None
            if "-" in filename and "_" in filename:
                try:
                    version_code_part = filename.split("-")[1].split("_")[0]
                    version_code = int(version_code_part)
                except (IndexError, ValueError):
                    logger.warning(f"Could not parse version code from filename: {filename}")

            # If we couldn't parse from filename, try using ADB
            if not version_name_match or not version_code:
                # First check if the APK file exists
                if not os.path.exists(apk_path):
                    logger.warning(f"APK file not found at {apk_path}, skipping ADB version check")
                    return (None, None)

                logger.info(f"Using ADB to get version info from {apk_path}")
                # Upload APK to device temporarily
                temp_path = "/sdcard/temp_kindle.apk"
                try:
                    result = subprocess.run(
                        ["adb", "-s", self.device_id, "push", apk_path, temp_path],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to push APK to device: {e}")
                    logger.error(f"stdout: {e.stdout}")
                    logger.error(f"stderr: {e.stderr}")
                    # Don't fail completely if we can't get version info
                    logger.warning("Continuing without APK version information")
                    return (None, None)

                # Use package manager to get info
                result = subprocess.run(
                    ["adb", "-s", self.device_id, "shell", "pm", "dump", temp_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                # Clean up
                subprocess.run(
                    ["adb", "-s", self.device_id, "shell", "rm", temp_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                # Parse output
                for line in result.stdout.splitlines():
                    if "versionName=" in line:
                        version_name_match = line.split("versionName=")[1].strip()
                    if "versionCode=" in line:
                        code_str = line.split("versionCode=")[1].strip().split(" ")[0]
                        try:
                            version_code = int(code_str)
                        except ValueError:
                            pass

            return (version_name_match, version_code)
        except Exception as e:
            logger.error(f"Error getting APK version: {e}", exc_info=True)
            return (None, None)

    def _find_newest_kindle_apk(self) -> str:
        """Find the newest Kindle APK among available options.

        Returns:
            str: Path to the newest APK
        """
        apk_paths = []

        # Check standard installation path - note this likely doesn't exist
        standard_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "android-sdk",
            "apk",
            "kindle.apk",
        )
        if os.path.exists(standard_path):
            apk_paths.append(standard_path)

        # Check ansible directory for additional APKs (android_arm)
        kindle_apk_dir = os.path.join(
            os.path.dirname(__file__),
            "ansible",
            "roles",
            "android_arm",
            "files",
        )
        if os.path.exists(kindle_apk_dir):
            for file in os.listdir(kindle_apk_dir):
                if "com.amazon.kindle" in file:
                    apk_paths.append(os.path.join(kindle_apk_dir, file))

        # Also check android_x86 directory for APKs
        kindle_x86_dir = os.path.join(
            os.path.dirname(__file__),
            "ansible",
            "roles",
            "android_x86",
            "files",
        )
        if os.path.exists(kindle_x86_dir):
            for file in os.listdir(kindle_x86_dir):
                if "com.amazon.kindle" in file:
                    apk_paths.append(os.path.join(kindle_x86_dir, file))

        if not apk_paths:
            logger.error("No Kindle APK files found", exc_info=True)
            return None

        # If only one APK is found, return it
        if len(apk_paths) == 1:
            return apk_paths[0]

        # Compare versions to find the newest
        newest_apk = None
        highest_version_code = -1

        # First try using version codes for comparison
        for apk_path in apk_paths:
            version_name, version_code = self._get_apk_version(apk_path)
            if version_code and version_code > highest_version_code:
                highest_version_code = version_code
                newest_apk = apk_path

        # If we couldn't determine version codes reliably, use lexicographical sorting of filenames
        if not newest_apk:
            # Sort filenames lexicographically (the last one alphabetically is typically newest with version in name)
            apk_paths.sort(key=lambda x: os.path.basename(x))
            newest_apk = apk_paths[-1]  # Get the last one lexicographically

        return newest_apk

    def _install_kindle(self) -> bool:
        """Install the Kindle app on the device."""
        try:
            logger.info(f"Installing Kindle on device {self.device_id}")

            # Find the newest APK
            apk_path = self._find_newest_kindle_apk()
            if not apk_path:
                logger.error("No Kindle APK found to install", exc_info=True)
                return False

            # Get version info from APK before installing
            apk_version_name, apk_version_code = self._get_apk_version(apk_path)
            if apk_version_name and apk_version_code:
                logger.info(f"Installing Kindle version: {apk_version_name} (code: {apk_version_code})")

            # Check APK supported ABIs using aapt
            try:
                aapt_check = subprocess.run(
                    ["/opt/android-sdk/build-tools/35.0.0/aapt", "dump", "badging", apk_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if aapt_check.returncode == 0:
                    for line in aapt_check.stdout.splitlines():
                        if "native-code:" in line:
                            logger.info(f"APK {line}")
                            break
                else:
                    logger.warning("Could not check APK ABIs with aapt")
            except Exception as e:
                logger.warning(f"Error checking APK ABIs: {e}")

            # Check device architecture before install
            try:
                arch_check = subprocess.run(
                    ["adb", "-s", self.device_id, "shell", "getprop", "ro.product.cpu.abi"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if arch_check.returncode == 0:
                    device_arch = arch_check.stdout.strip()
                    logger.info(f"Device architecture: {device_arch}")

                    # Check all supported ABIs
                    all_abis = subprocess.run(
                        ["adb", "-s", self.device_id, "shell", "getprop", "ro.product.cpu.abilist"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if all_abis.returncode == 0:
                        logger.info(f"Device supports ABIs: {all_abis.stdout.strip()}")

                    # Check if libhoudini is present
                    houdini_check = subprocess.run(
                        [
                            "adb",
                            "-s",
                            self.device_id,
                            "shell",
                            "ls",
                            "/system/lib/libhoudini.so",
                            "2>/dev/null",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if houdini_check.returncode == 0:
                        logger.info("ARM translation (libhoudini) is available")
                    else:
                        logger.warning("ARM translation (libhoudini) NOT found - ARM apps won't run!")

                # Also check available storage
                storage_check = subprocess.run(
                    ["adb", "-s", self.device_id, "shell", "df", "/data"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if storage_check.returncode == 0:
                    logger.info(f"Device storage status:\n{storage_check.stdout}")
            except Exception as e:
                logger.warning(f"Could not check device info: {e}")

            # Retry logic for APK installation
            max_retries = 3
            retry_delay = 2  # seconds

            for attempt in range(max_retries):
                try:
                    result = subprocess.run(
                        ["adb", "-s", self.device_id, "install", "-r", apk_path],
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    if result.returncode == 0:
                        logger.info("Kindle app installed successfully")
                        break
                    else:
                        error_msg = result.stderr.strip() or result.stdout.strip()

                        # Log the full error for debugging
                        logger.warning(f"Install failed (attempt {attempt + 1}/{max_retries}): {error_msg}")

                        # Check if the error is related to device not ready
                        if any(
                            keyword in error_msg.lower()
                            for keyword in [
                                "offline",
                                "unauthorized",
                                "device not found",
                                "error: closed",
                                "cannot connect",
                                "daemon not running",
                            ]
                        ):
                            if attempt < max_retries - 1:
                                logger.info(
                                    f"Device connectivity issue, waiting {retry_delay} seconds before retry..."
                                )
                                time.sleep(retry_delay)
                                continue

                        # For other errors or last attempt, log full details
                        if attempt == max_retries - 1:
                            logger.error(
                                f"Final install attempt failed. Full error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
                                exc_info=True,
                            )

                        # Fail immediately for non-connectivity errors
                        raise subprocess.CalledProcessError(
                            result.returncode, result.args, result.stdout, result.stderr
                        )

                except subprocess.CalledProcessError as e:
                    if attempt == max_retries - 1:
                        raise
                    else:
                        logger.warning(f"Install attempt {attempt + 1} failed, retrying...")
                        time.sleep(retry_delay)
            else:
                # All retries exhausted
                raise Exception(f"Failed to install APK after {max_retries} attempts")

            # Store version information in profile
            if apk_version_name and apk_version_code:
                self._update_kindle_version_in_profile(apk_version_name, apk_version_code)
            else:
                # If we couldn't get version from APK, get it from the installed app
                installed_version_name, installed_version_code = self._get_installed_kindle_version()
                if installed_version_name and installed_version_code:
                    self._update_kindle_version_in_profile(installed_version_name, installed_version_code)

            return True
        except Exception as e:
            logger.error(f"Error installing Kindle: {e}", exc_info=True)
            return False

    def _get_kindle_launch_activity(self) -> Optional[str]:
        """Get the main launch activity for the Kindle app."""
        try:
            result = subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "cmd package resolve-activity -c android.intent.category.LAUNCHER com.amazon.kindle",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            # Parse output to find main activity
            for line in result.stdout.splitlines():
                if "name=" in line and "com.amazon.kindle" in line:
                    activity = line.split("name=")[1].strip()
                    return activity

            logger.error("Could not find Kindle launch activity", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error getting Kindle launch activity: {e}", exc_info=True)
            return None

    def check_connection(self):
        if self.driver:
            # Test if driver is still connected
            try:
                self.driver.current_activity
                logger.info(
                    f"Driver already initialized and connected, id: {self.device_id}, instance: {self.driver} {self}"
                )
                return True  # Return early if driver is already connected
            except Exception as e:
                logger.info(f"Driver not connected - reinitializing {self}")
                self.driver = None

    def initialize(self):
        """Initialize Appium driver with retry logic. Safe to call multiple times."""
        if self.check_connection():
            return True

        email = get_sindarin_email()

        # CRITICAL: Check if this profile has a VNC instance before proceeding
        # This prevents initializing drivers for profiles without running emulators
        try:
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            vnc_instance = vnc_manager.get_instance_for_profile(email)
            if not vnc_instance:
                logger.error(
                    f"No VNC instance found for {email}. "
                    f"Cannot initialize driver without a running emulator.",
                    exc_info=True,
                )
                return False
            logger.info(f"Found VNC instance for {email}: {vnc_instance}")
        except Exception as e:
            logger.warning(f"Error checking VNC instance: {e}")

        # Get device ID first, using specific device ID from profile if available
        target_device_id = None

        # Check if we have a profile manager with a preferred device ID
        # Get the current profile for device ID info
        profile = self.automator.profile_manager.get_current_profile()

        if profile and "avd_name" in profile:
            # Try to get device ID from AVD name mapping
            avd_name = profile.get("avd_name")
            device_id = self.automator.profile_manager.get_emulator_id_for_avd(avd_name)
            if device_id:
                target_device_id = device_id

        # Get device ID, preferring the specific one if provided
        self.device_id = self._get_emulator_device_id(target_device_id)

        if not self.device_id:
            logger.error("Failed to get device ID", exc_info=True)
            return False

        # Update profile with device ID
        profile = self.automator.profile_manager.get_current_profile()
        if not profile:
            logger.error("Cannot update profile: get_current_profile returned None", exc_info=True)
        else:
            avd_name = profile.get("avd_name")

            if not email or not avd_name:
                logger.error(
                    f"Missing required profile fields: email={email}, avd_name={avd_name}, profile={profile}",
                    exc_info=True,
                )

            else:
                # Use the appropriate method based on what's available
                self.automator.profile_manager._save_profile_status(email, avd_name, self.device_id)

        # Check if app is installed
        if not self._is_kindle_installed():
            logger.info("Kindle app not installed - attempting to install")
            if not self._install_kindle():
                logger.error("Failed to install Kindle app", exc_info=True)
                return False
            logger.info("Successfully installed Kindle app")
        else:
            # App is installed - check if an update is available
            profile_version_name = None
            profile_version_code = None
            profile = None

            # Try to get version from profile first (faster)
            profile_manager = self.automator.profile_manager

            profile_version_name = profile_manager.get_user_field(email, "kindle_version_name")
            profile_version_code_str = profile_manager.get_user_field(email, "kindle_version_code")

            if profile_version_code_str:
                try:
                    profile_version_code = int(profile_version_code_str)
                except ValueError:
                    profile_version_code = None

            # If we have profile version info, use it; otherwise query the device
            if profile_version_name and profile_version_code:
                installed_version_name = profile_version_name
                installed_version_code = profile_version_code
            else:
                # Get version from device
                installed_version_name, installed_version_code = self._get_installed_kindle_version()

                # Store version in profile for future reference if we got valid version info
                if installed_version_name and installed_version_code and profile:
                    self._update_kindle_version_in_profile(installed_version_name, installed_version_code)

            if installed_version_code:
                # Find newest available APK
                newest_apk = self._find_newest_kindle_apk()
                if newest_apk:
                    apk_version_name, apk_version_code = self._get_apk_version(newest_apk)

                    if apk_version_code and apk_version_code > installed_version_code:
                        logger.info(
                            f"Upgrading Kindle from version {installed_version_name} to {apk_version_name}"
                        )

                        subprocess.run(
                            ["adb", "-s", self.device_id, "install", "-r", newest_apk],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        logger.info("Kindle app upgraded successfully")

                        # Update stored version info after successful upgrade
                        # Store version info at top level with generic setter
                        self.automator.profile_manager.set_user_field(
                            email, "kindle_version_name", apk_version_name
                        )
                        self.automator.profile_manager.set_user_field(
                            email, "kindle_version_code", str(apk_version_code)
                        )
                        # Clean up any version info that might be in preferences
                        self._clean_old_version_info(email)

        # Clean up any existing sessions
        # self._cleanup_old_sessions()

        # Check and disable hardware overlays
        self._disable_hw_overlays()

        # Disable all system animations
        self._disable_animations()

        # Disable sleep and app standby to prevent device and app from sleeping
        self._disable_sleep()

        # Hide the status bar
        self._disable_status_bar()

        # Disable automatic app updates to prevent crashes
        self._disable_auto_updates()

        # Get Kindle launch activity
        app_activity = self._get_kindle_launch_activity()
        if not app_activity:
            return False

        # Check if Appium is already running for this profile
        appium_driver = AppiumDriver.get_instance()
        appium_info = appium_driver.get_appium_process_info(email)
        if not appium_info or not appium_info.get("running"):
            # Start the Appium server for this profile
            max_attempts = 3
            for attempt in range(max_attempts):
                appium_started = appium_driver.start_appium_for_profile(email)
                if appium_started:
                    break

                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Failed to start Appium server for {email}, attempt {attempt + 1}/{max_attempts}"
                    )
                    time.sleep(2)  # Wait before retry

            if not appium_started:
                logger.error(
                    f"Failed to start Appium server for {email} after {max_attempts} attempts", exc_info=True
                )
                return False
        elif self.driver:
            logger.info(f"Appium already running for {email} on port {appium_info['port']}")
            self.appium_port = appium_info["port"]
            return True

        # Initialize driver with retry logic
        for attempt in range(1, 2):
            logger.info(f"Attempting to initialize driver to {self.device_id} (attempt {attempt}/2)...")

            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.automation_name = "UiAutomator2"

            # Set the device ID as both udid and deviceName for proper device targeting
            options.set_capability("deviceName", self.device_id)
            options.set_capability("udid", self.device_id)

            # # Get Android ID for the device for more reliable identification
            # try:
            #     android_id = subprocess.run(
            #         ["adb", "-s", self.device_id, "shell", "settings", "get", "secure", "android_id"],
            #         capture_output=True,
            #         text=True,
            #         check=True,
            #     ).stdout.strip()
            #     if android_id:
            #         logger.debug(f"Setting Android ID in appium: {android_id}")
            #         options.set_capability("appium:androidId", android_id)
            #     else:
            #         logger.warning("Could not retrieve Android ID")
            # except Exception as e:
            #     logger.warning(f"Could not retrieve Android ID: {e}")

            # Tell UiAutomator2 to strictly use this device and not fall back to others
            options.set_capability("appium:ensureWebviewsHavePages", True)  # Helps with stability

            options.app_package = "com.amazon.kindle"
            options.app_activity = app_activity
            options.app_wait_activity = "com.amazon.*"
            options.no_reset = True
            options.auto_grant_permissions = True
            options.enable_multi_windows = True
            options.ignore_unimportant_views = False
            options.allow_invisible_elements = True
            options.new_command_timeout = 1800  # 30 minutes (1800 seconds)

            # Prevent app relaunch on Appium session start
            options.set_capability("appium:autoLaunch", False)  # Disable app relaunch on session start
            options.set_capability("appium:noReset", True)
            options.set_capability(
                "appium:dontStopAppOnReset", True
            )  # Prevent closing app when session stops

            # Set longer timeouts to avoid connection issues
            options.set_capability(
                "appium:uiautomator2ServerLaunchTimeout", 60000
            )  # 60 seconds timeout for UiAutomator2 server launch - increased for parallel
            # Leave this higher since we need time for ADB commands during actual operations
            options.set_capability("appium:adbExecTimeout", 180000)  # 180 seconds timeout for ADB commands
            options.set_capability("appium:udid", self.device_id)

            # Keep UiAutomator2 server alive for 30 minutes after last command
            options.set_capability(
                "appium:uiautomator2ServerReadTimeout", 1800000
            )  # 30 minutes in milliseconds
            options.set_capability("appium:uiautomator2ServerInstallTimeout", 90000)  # 90 seconds for install

            # Add parallel execution capabilities
            instance_id = None
            profile = self.automator.profile_manager.get_current_profile()
            if profile:
                email = profile.get("email") or profile.get("assigned_profile")
                if email:
                    # Create instance-specific ID
                    instance_id = email.split("@")[0].replace(".", "_")

            # If we have instance_id, add unique ports for parallel execution
            if instance_id and email:
                # Get allocated ports from VNCInstanceManager via AppiumDriver
                allocated_ports = appium_driver.get_appium_ports_for_profile(email)

                if allocated_ports:
                    # Use the allocated ports
                    # Using proper UiAutomator2 capability names
                    options.set_capability("appium:systemPort", allocated_ports["systemPort"])
                    # options.set_capability("appium:chromedriverPort", allocated_ports["chromedriverPort"])
                    # options.set_capability("appium:mjpegServerPort", allocated_ports["mjpegServerPort"])
                    self.appium_port = allocated_ports["appiumPort"]

                    # Clean up any existing port forwards for this device to avoid conflicts
                    logger.info(
                        f"Cleaning up port forwards for {self.device_id} before initialization, using ports {allocated_ports}"
                    )
                    try:
                        subprocess.run(
                            f"adb -s {self.device_id} forward --remove-all",
                            shell=True,
                            check=False,
                            timeout=5,
                        )
                    except Exception as e:
                        logger.warning(f"Error cleaning port forwards: {e}")
                else:
                    logger.error(f"No allocated ports found for {email}", exc_info=True)
                    return False

            # Check if Appium device has been initialized before for this user
            profile = self.automator.profile_manager.get_current_profile()
            email = get_sindarin_email()

            if (
                profile
                and email
                and self.automator.profile_manager.get_user_field(
                    email, "appium_device_initialized", False, section="emulator_settings"
                )
            ):
                # Skip device initialization for faster startup on subsequent connections
                options.set_capability("appium:skipDeviceInitialization", True)
                logger.info(f"Skipping Appium device initialization for {email} (already initialized)")
            else:
                logger.info(f"Will perform full Appium device initialization for {email}")

            # Clean up system files to avoid conflicts
            options.set_capability("appium:clearSystemFiles", True)
            options.set_capability("appium:skipServerInstallation", False)

            # Force server shutdown on disconnect to prevent port conflicts
            options.set_capability("appium:disableWindowAnimation", True)

            # Ensure clean session management
            options.set_capability("appium:skipUnlock", True)
            options.set_capability("appium:dontStopAppOnReset", True)  # Keep app running when session ends

            # First verify the Appium server is actually responding
            # This prevents attempting to connect to a non-responsive server

            max_retries = 3
            retry_delay = 1

            for attempt in range(max_retries):
                logger.info(
                    f"Checking Appium server (127.0.0.1:{self.appium_port}) status (attempt {attempt+1}/{max_retries})..."
                )
                status_response = requests.get(f"http://127.0.0.1:{self.appium_port}/status", timeout=5)
                # Handle both Appium 1.x and 2.x response formats
                response_json = status_response.json()

                # Check for Appium 1.x format: {"status": 0, ...}
                appium1_format = "status" in response_json and response_json["status"] == 0

                # Check for Appium 2.x format: {"value": {"ready": true, ...}}
                appium2_format = (
                    "value" in response_json
                    and isinstance(response_json["value"], dict)
                    and response_json["value"].get("ready") == True
                )

                if status_response.status_code == 200 and (appium1_format or appium2_format):
                    break
                else:
                    logger.warning(
                        f"Appium server not ready on port {self.appium_port} (attempt {attempt+1}/{max_retries})"
                    )

                    # If this is the last retry, raise an exception
                    if attempt == max_retries - 1:
                        raise Exception(
                            f"Appium server not ready on port {self.appium_port} after {max_retries} attempts"
                        )

                    # Wait before retrying
                    time.sleep(retry_delay)
                    retry_delay *= 2

            # Initialize driver with the options using the specific port
            # Ensure we have a valid appium port - use centralized default as fallback
            logger.info(f"Connecting to Appium on port {self.appium_port} for device {self.device_id}")

            try:
                self.driver = webdriver.Remote(f"http://127.0.0.1:{self.appium_port}", options=options)
            except MaxRetryError as e:
                logger.error(
                    f"Failed to connect to Appium server on port {self.appium_port}: {e}", exc_info=True
                )
                return False

            # Force a state check after driver initialization with a timeout
            import concurrent.futures

            # Run the check with a timeout
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self.check_connection)
                try:
                    logger.debug("Checking connection to Appium server...")
                    result = future.result(timeout=5)
                    logger.debug(f"Connection check result: {result}")

                    # Mark Appium device as initialized for this user if not already done
                    if email and not self.automator.profile_manager.get_user_field(
                        email, "appium_device_initialized", False, section="emulator_settings"
                    ):
                        self._update_profile_setting("appium_device_initialized", True)
                        logger.info(f"Marked Appium device as initialized for {email}")

                    return True
                except concurrent.futures.TimeoutError:
                    logger.error("Connection check timed out after 15 seconds", exc_info=True)

                    try:
                        # Try to quit the driver that may be in a bad state
                        if self.driver:
                            self.driver.quit()
                    except:
                        pass
                    self.driver = None
                    raise TimeoutError("Connection check timed out")

    def _is_session_active(self) -> bool:
        """Check if the current driver session is active and healthy."""
        if not self.driver:
            return False

        try:
            # Use window_handles as the lightest check that doesn't interact with UI
            _ = self.driver.window_handles
            return True
        except Exception as e:
            error_message = str(e)
            # Check for specific session termination indicators
            if any(
                indicator in error_message
                for indicator in [
                    "session is either terminated",
                    "no active session",
                    "invalid session id",
                    "session not started",
                    "NoSuchDriverError",
                    "ECONNREFUSED",
                ]
            ):
                logger.warning(f"Session no longer active: {error_message}")
                return False
            # For other errors, assume session might still be valid
            return True

    def _ensure_session_active(self):
        """Ensure the driver session is active, reconnecting if necessary."""
        if self._is_session_active():
            return True

        logger.warning("Driver session is no longer active, attempting to reconnect...")

        # Clean up old session
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

        self.driver = None

        # Check if we're already in a reconnection attempt
        if hasattr(self, "_reconnecting") and self._reconnecting:
            logger.error("Already in reconnection attempt, avoiding infinite loop", exc_info=True)
            return False

        # Reinitialize through automator if available
        if self.automator:
            self._reconnecting = True
            try:
                if self.automator.initialize_driver():
                    logger.info("Successfully reconnected driver session")
                    self._session_retries = 0
                    return True
                else:
                    logger.error("Failed to reinitialize driver through automator", exc_info=True)
            finally:
                self._reconnecting = False
        else:
            logger.error("No automator reference available for reconnection", exc_info=True)

        logger.error("Failed to reconnect driver session after all attempts", exc_info=True)
        return False

    def get_appium_driver_instance(self):
        """Get the Appium driver instance, ensuring session is active"""
        if not self._ensure_session_active():
            logger.error("Failed to ensure active session", exc_info=True)
            return None
        return self.driver

    def get_device_id(self):
        """Get the current device ID"""
        return self.device_id

    def quit(self):
        """Quit the Appium driver"""
        logger.info(f"Quitting driver: {self.driver}")

        # Clean up port forwards before quitting driver
        if self.device_id:
            logger.info(f"Cleaning up port forwards for device {self.device_id}")
            try:
                subprocess.run(
                    f"adb -s {self.device_id} forward --remove-all",
                    shell=True,
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                logger.info(f"Successfully removed all port forwards for {self.device_id}")
            except Exception as e:
                logger.warning(f"Error removing port forwards during driver quit: {e}")

            # Also kill any UiAutomator2 processes
            try:
                subprocess.run(
                    [f"adb -s {self.device_id} shell pkill -f uiautomator"],
                    shell=True,
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            except Exception as e:
                logger.warning(f"Error killing UiAutomator2 processes during driver quit: {e}")

        if self.driver:
            import concurrent.futures

            def _quit_driver():
                self.driver.quit()

            # Use ThreadPoolExecutor to add a timeout to driver.quit()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_quit_driver)
                try:
                    # Give it 3 seconds to quit gracefully
                    future.result(timeout=3)
                    logger.info("Successfully quit Appium driver session")
                except concurrent.futures.TimeoutError:
                    logger.warning("Driver.quit() timed out after 3 seconds - likely device already offline")
                except Exception as e:
                    error_msg = str(e).lower()
                    # Check if this is an expected error during shutdown
                    if "adb: device offline" in error_msg or "device offline" in error_msg:
                        logger.info(
                            "Device already offline during driver.quit() - this is expected during shutdown"
                        )
                    elif "a session is either terminated or not started" in error_msg:
                        # This is expected when the session was already terminated
                        logger.debug("Session already terminated during driver.quit() - this is expected")
                    else:
                        logger.error(f"Error during driver.quit(, exc_info=True): {e}")
                finally:
                    self.driver = None
                    self.device_id = None
