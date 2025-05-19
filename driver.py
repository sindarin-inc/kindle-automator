import logging
import os
import subprocess
import time
from functools import wraps
from typing import Optional

from appium import webdriver
from appium.options.android import UiAutomator2Options
from flask import current_app

from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


def ensure_session_active(func):
    """Decorator to ensure driver session is active before executing a method."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Only apply to instance methods of Driver class
        if hasattr(self, "_ensure_session_active"):
            self._ensure_session_active()
        return func(self, *args, **kwargs)

    return wrapper


class Driver:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Driver, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.driver = None
        self.device_id = None
        self.automator = None  # Reference to the automator instance
        self.appium_port = None  # Default port, can be overridden
        self._session_retries = 0
        self._max_session_retries = 2

    def _get_emulator_device_id(self, specific_device_id: Optional[str] = None) -> Optional[str]:
        """
        Get the emulator device ID from adb devices, optionally targeting a specific device.

        Args:
            specific_device_id: Optional device ID to specifically connect to (e.g., 'emulator-5554')

        Returns:
            Optional[str]: The device ID if found, None otherwise
        """
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
                        logger.info(f"Verified specific device {specific_device_id}")
                        return specific_device_id
                    except Exception as e:
                        logger.warning(f"Could not verify specific device {specific_device_id}: {e}")
                        # Failed to verify specific device - return None instead of falling back to any device
                        logger.error(f"Requested specific device {specific_device_id} could not be verified")
                        return None
                else:
                    logger.warning(f"Specified device ID {specific_device_id} not found or not ready")
                    # Do not continue to regular device search if a specific device was requested
                    # but is not available. This prevents using the wrong device.
                    logger.error(
                        f"Requested specific device {specific_device_id} was not found or is not ready"
                    )
                    return None

            # Only proceed with regular device search if NO specific device was requested
            result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if "emulator-" in line and "device" in line:
                    device_id = line.split()[0]
                    # Verify this is actually an emulator
                    verify_result = subprocess.run(
                        ["adb", "-s", device_id, "shell", "getprop", "ro.product.model"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    if "sdk" in verify_result.stdout.lower() or "emulator" in verify_result.stdout.lower():
                        return device_id
                elif "127.0.0.1:" in line:
                    device_id = line.split()[0]
                    verify_result = subprocess.run(
                        ["adb", "-s", device_id, "shell", "getprop", "ro.product.model"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    logger.info(f"Verify result: {verify_result.stdout}")
                    if "pixel" in verify_result.stdout.lower():
                        return device_id
            return None
        except Exception as e:
            logger.error(f"Error getting emulator device ID: {e}")
            return None

    def _disable_hw_overlays(self) -> bool:
        """Disable hardware overlays to improve WebView visibility."""
        try:
            # Check if we already applied this setting to the current emulator
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                device_id = profile.get("emulator_id") if profile else None

                # If this is the same device and we already set hw_overlays_disabled, skip
                if (
                    device_id
                    and device_id == self.device_id
                    and profile
                    and profile.get("hw_overlays_disabled", False)
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
            logger.error(f"Failed to handle HW overlays: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error handling HW overlays: {e}")
            return False

    def _update_profile_setting(self, setting_name: str, value: bool) -> None:
        """Update a setting in the current profile.

        Args:
            setting_name: The name of the setting to update
            value: The value to set
        """
        try:
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                if not profile:
                    logger.warning("Cannot update profile setting: no current profile")
                    return

                email = get_sindarin_email()
                avd_name = profile.get("avd_name")

                if email and avd_name:
                    # Update the setting in the current profile
                    profile[setting_name] = value

                    # Update the profile in the profile manager
                    emulator_id = profile.get("emulator_id")

                    # Check which method is available in profile_manager
                    if hasattr(self.automator.profile_manager, "_save_profile_status"):
                        self.automator.profile_manager._save_profile_status(email, avd_name, emulator_id)
                    elif hasattr(self.automator.profile_manager, "_save_current_profile"):
                        self.automator.profile_manager._save_current_profile(email, avd_name, emulator_id)

                    # Also update user preferences for persistence
                    if email not in self.automator.profile_manager.user_preferences:
                        self.automator.profile_manager.user_preferences[email] = {}

                    self.automator.profile_manager.user_preferences[email][setting_name] = value
                    self.automator.profile_manager._save_user_preferences()

                    logger.info(f"Updated profile setting {setting_name}={value} for {email}")
                else:
                    logger.error(f"Failed to update profile setting: {setting_name}={value} for {email}")
        except Exception as e:
            logger.error(f"Error updating profile setting {setting_name}: {e}")
            # Continue execution even if we can't update the profile

    def _clean_old_version_info(self, email: str) -> None:
        """Remove Kindle version information from preferences if present.

        Args:
            email: Email address of the profile
        """
        try:
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "profiles_index")
            ):
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
                    if cleaned and hasattr(self.automator.profile_manager, "_save_profiles_index"):
                        self.automator.profile_manager._save_profiles_index()
        except Exception as e:
            logger.error(f"Error cleaning old version info for {email}: {e}")

    def _update_kindle_version_in_profile(self, version_name: str, version_code: int) -> None:
        """Update Kindle version information in the current profile.

        Args:
            version_name: The version name (e.g. "8.121.0.100")
            version_code: The version code (e.g. 1286055411)
        """
        try:
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                if not profile:
                    logger.warning("Cannot update Kindle version in profile: no current profile")
                    return

                email = profile.get("email") or profile.get("assigned_profile")
                avd_name = profile.get("avd_name")

                if email and avd_name:
                    # Update version info at top level using generic field setter if available
                    if hasattr(self.automator.profile_manager, "set_user_field"):
                        self.automator.profile_manager.set_user_field(
                            email, "kindle_version_name", version_name
                        )
                        self.automator.profile_manager.set_user_field(
                            email, "kindle_version_code", str(version_code)
                        )
                    else:
                        # Fall back to direct profile update
                        profile["kindle_version_name"] = version_name
                        profile["kindle_version_code"] = str(version_code)

                        # Update the profile in the profile manager
                        emulator_id = profile.get("emulator_id")

                        # Check which method is available in profile_manager
                        if hasattr(self.automator.profile_manager, "_save_profile_status"):
                            self.automator.profile_manager._save_profile_status(email, avd_name, emulator_id)
                        elif hasattr(self.automator.profile_manager, "_save_current_profile"):
                            self.automator.profile_manager._save_current_profile(email, avd_name, emulator_id)

                    logger.info(
                        f"Updated Kindle version in profile to {version_name} (code: {version_code}) for {email}"
                    )
        except Exception as e:
            logger.error(f"Error updating Kindle version in profile: {e}")
            # Continue execution even if we can't update the profile

    def _disable_animations(self) -> bool:
        """Disable all system animations to improve reliability."""
        try:
            # Check if we already applied this setting to the current emulator
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                device_id = profile.get("emulator_id") if profile else None

                # If this is the same device and we already set animations_disabled, skip
                if (
                    device_id
                    and device_id == self.device_id
                    and profile
                    and profile.get("animations_disabled", False)
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
            logger.error(f"Failed to disable animations: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error disabling animations: {e}")
            return False

    def _disable_sleep(self) -> bool:
        """Disable sleep and app standby modes to prevent the device and app from sleeping."""
        try:
            # Check if we already applied this setting to the current emulator
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                device_id = profile.get("emulator_id") if profile else None

                # If this is the same device and we already set sleep_disabled, skip
                if (
                    device_id
                    and device_id == self.device_id
                    and profile
                    and profile.get("sleep_disabled", False)
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
            logger.error(f"Failed to disable sleep: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error disabling sleep: {e}")
            return False

    def _disable_status_bar(self) -> bool:
        """Hide the status bar at runtime using ADB."""
        try:
            # Check if we already applied this setting to the current emulator
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                profile = self.automator.profile_manager.get_current_profile()
                device_id = profile.get("emulator_id") if profile else None

                # If this is the same device and we already set status_bar_disabled, skip
                if (
                    device_id
                    and device_id == self.device_id
                    and profile
                    and profile.get("status_bar_disabled", False)
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
            logger.error(f"Failed to hide status bar: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error hiding status bar: {e}")
            return False

    def _cleanup_old_sessions(self):
        """Clean up any existing UiAutomator2 sessions."""
        try:
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", "pm", "clear", "io.appium.uiautomator2.server"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", "pm", "clear", "io.appium.uiautomator2.server.test"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except Exception as e:
            logger.error(f"Error cleaning up old sessions: {e}")
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
            logger.error(f"Error checking Kindle installation: {e}")
            return False

    def _get_installed_kindle_version(self) -> tuple:
        """Get the version of the installed Kindle app.

        Returns:
            tuple: (version_name, version_code) or (None, None) if failed
        """
        try:
            logger.info(f"Getting installed Kindle version on device {self.device_id}")
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
                        logger.error(f"Could not parse version code: {version_code_str}")

            return (version_name, version_code)
        except Exception as e:
            logger.error(f"Error getting installed Kindle version: {e}")
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
                logger.info(f"Using ADB to get version info from {apk_path}")
                # Upload APK to device temporarily
                temp_path = "/sdcard/temp_kindle.apk"
                subprocess.run(
                    ["adb", "-s", self.device_id, "push", apk_path, temp_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )

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
            logger.error(f"Error getting APK version: {e}")
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
            logger.error("No Kindle APK files found")
            return None

        # If only one APK is found, return it
        if len(apk_paths) == 1:
            logger.info(f"Only one APK found: {os.path.basename(apk_paths[0])}")
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
            logger.info(
                f"Using {os.path.basename(newest_apk)} as newest APK based on filename lexicographical ordering"
            )

        return newest_apk

    def _install_kindle(self) -> bool:
        """Install the Kindle app on the device."""
        try:
            logger.info(f"Installing Kindle on device {self.device_id}")

            # Find the newest APK
            apk_path = self._find_newest_kindle_apk()
            if not apk_path:
                logger.error("No Kindle APK found to install")
                return False

            # Get version info from APK before installing
            apk_version_name, apk_version_code = self._get_apk_version(apk_path)
            if apk_version_name and apk_version_code:
                logger.info(f"Installing Kindle version: {apk_version_name} (code: {apk_version_code})")

            subprocess.run(
                ["adb", "-s", self.device_id, "install", "-r", apk_path],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Kindle app installed successfully")

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
            logger.error(f"Error installing Kindle: {e}")
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
                    logger.info(f"Found Kindle launch activity: {activity}")
                    return activity

            logger.error("Could not find Kindle launch activity")
            return None
        except Exception as e:
            logger.error(f"Error getting Kindle launch activity: {e}")
            return None

    def initialize(self):
        """Initialize Appium driver with retry logic. Safe to call multiple times."""
        if self.driver:
            # Test if driver is still connected
            try:
                self.driver.current_activity
            except Exception as e:
                logger.info("Driver not connected - reinitializing")
                self.driver = None
            else:
                logger.info("Driver already initialized, reinitializing")
                self.driver = None

        # Get device ID first, using specific device ID from profile if available
        target_device_id = None

        # Check if we have a profile manager with a preferred device ID
        if self.automator and hasattr(self.automator, "profile_manager"):
            # Get the current profile for device ID info
            profile = self.automator.profile_manager.get_current_profile()
            if profile and "emulator_id" in profile:
                # Use the device ID from the profile
                target_device_id = profile.get("emulator_id")
                logger.info(f"Using target device ID from profile: {target_device_id}")
            elif profile and "avd_name" in profile:
                # Try to get device ID from AVD name mapping
                avd_name = profile.get("avd_name")
                device_id = self.automator.profile_manager.get_emulator_id_for_avd(avd_name)
                if device_id:
                    target_device_id = device_id

        # Get device ID, preferring the specific one if provided
        self.device_id = self._get_emulator_device_id(target_device_id)
        if not self.device_id:
            logger.error("Failed to get device ID")
            return False

        # Update profile with device ID
        if not self.automator:
            logger.error("Cannot update profile: automator not initialized")

        elif not hasattr(self.automator, "profile_manager"):
            logger.error("Cannot update profile: profile_manager not found")

        elif not hasattr(self.automator.profile_manager, "get_current_profile"):
            logger.error("Cannot update profile: get_current_profile method not found")

        else:
            profile = self.automator.profile_manager.get_current_profile()
            if not profile:
                logger.error("Cannot update profile: get_current_profile returned None")
            else:
                email = get_sindarin_email()
                avd_name = profile.get("avd_name")

                if not email or not avd_name:
                    logger.error(
                        f"Missing required profile fields: email={email}, avd_name={avd_name}, profile={profile}"
                    )

                else:
                    # Use the appropriate method based on what's available
                    if hasattr(self.automator.profile_manager, "_save_profile_status"):
                        self.automator.profile_manager._save_profile_status(email, avd_name, self.device_id)
                    elif hasattr(self.automator.profile_manager, "_save_current_profile"):
                        self.automator.profile_manager._save_current_profile(email, avd_name, self.device_id)
                    else:
                        logger.error("No method found to save profile status")

        # Check if app is installed
        if not self._is_kindle_installed():
            logger.info("Kindle app not installed - attempting to install")
            if not self._install_kindle():
                logger.error("Failed to install Kindle app")
                return False
            logger.info("Successfully installed Kindle app")
        else:
            # App is installed - check if an update is available
            profile_version_name = None
            profile_version_code = None
            profile = None

            # Try to get version from profile first (faster)
            if self.automator and hasattr(self.automator, "profile_manager"):
                profile_manager = self.automator.profile_manager

                # Get current profile email
                email = None
                if hasattr(profile_manager, "get_current_profile"):
                    profile = profile_manager.get_current_profile()
                    if profile:
                        email = profile.get("email") or profile.get("assigned_profile")

                if email and hasattr(profile_manager, "get_user_field"):
                    # Use the new get_user_field method
                    profile_version_name = profile_manager.get_user_field(email, "kindle_version_name")
                    profile_version_code_str = profile_manager.get_user_field(email, "kindle_version_code")

                    if profile_version_code_str:
                        try:
                            profile_version_code = int(profile_version_code_str)
                        except ValueError:
                            profile_version_code = None
                elif hasattr(profile_manager, "get_current_profile"):
                    # Fall back to direct profile access
                    profile = profile_manager.get_current_profile()
                    if profile:
                        # Check for version info at top level first
                        profile_version_name = profile.get("kindle_version_name")
                        profile_version_code_str = profile.get("kindle_version_code")

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
                logger.info(
                    f"Current Kindle version: {installed_version_name} (code: {installed_version_code})"
                )

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
                        if self.automator and hasattr(self.automator.profile_manager, "set_user_field"):
                            email = profile.get("email") or profile.get("assigned_profile")
                            if email:
                                # Store version info at top level with generic setter
                                self.automator.profile_manager.set_user_field(
                                    email, "kindle_version_name", apk_version_name
                                )
                                self.automator.profile_manager.set_user_field(
                                    email, "kindle_version_code", str(apk_version_code)
                                )
                                # Clean up any version info that might be in preferences
                                self._clean_old_version_info(email)
                        elif profile:
                            self._update_kindle_version_in_profile(apk_version_name, apk_version_code)
                    else:
                        logger.info("Kindle app is already at the latest version")

        # Clean up any existing sessions
        self._cleanup_old_sessions()

        # Check and disable hardware overlays
        self._disable_hw_overlays()

        # Disable all system animations
        self._disable_animations()

        # Disable sleep and app standby to prevent device and app from sleeping
        self._disable_sleep()

        # Hide the status bar
        self._disable_status_bar()

        # Get Kindle launch activity
        app_activity = self._get_kindle_launch_activity()
        if not app_activity:
            return False

        # Initialize driver with retry logic
        for attempt in range(1, 2):  # Increase to 5 attempts
            logger.info(f"Attempting to initialize driver to {self.device_id} (attempt {attempt}/5)...")

            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.automation_name = "UiAutomator2"

            # Set the device ID as both udid and deviceName for proper device targeting
            options.set_capability("deviceName", self.device_id)
            options.set_capability("udid", self.device_id)

            # Get Android ID for the device for more reliable identification
            try:
                android_id = subprocess.run(
                    ["adb", "-s", self.device_id, "shell", "settings", "get", "secure", "android_id"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                if android_id:
                    logger.debug(f"Setting Android ID in appium: {android_id}")
                    options.set_capability("udid", android_id)
                else:
                    logger.warning("Could not retrieve Android ID")
            except Exception as e:
                logger.warning(f"Could not retrieve Android ID: {e}")

            # Tell UiAutomator2 to strictly use this device and not fall back to others
            options.set_capability("enforceAppiumPrefixes", True)  # Ensure strict capability naming
            options.set_capability("ensureWebviewsHavePages", True)  # Helps with stability

            options.app_package = "com.amazon.kindle"
            options.app_activity = app_activity
            options.app_wait_activity = "com.amazon.*"
            options.no_reset = True
            options.auto_grant_permissions = True
            options.enable_multi_windows = True
            options.ignore_unimportant_views = False
            options.allow_invisible_elements = True
            options.new_command_timeout = 60 * 60 * 24 * 7  # 7 days

            # Set shorter waitForIdleTimeout to make Appium faster
            options.set_capability("waitForIdleTimeout", 1000)  # 1 second wait for idle state

            # Set longer timeouts to avoid connection issues
            options.set_capability(
                "uiautomator2ServerLaunchTimeout", 60000
            )  # 60 seconds timeout for UiAutomator2 server launch - increased for parallel
            # Leave this higher since we need time for ADB commands during actual operations
            options.set_capability("adbExecTimeout", 180000)  # 180 seconds timeout for ADB commands
            options.set_capability("connectionTimeout", 10000)  # 10 seconds for connection timeout

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
                # Get allocated ports from server - pass device ID for proper allocation
                allocated_ports = None
                server = current_app.config.get("server_instance")
                if server and hasattr(server, "get_unique_ports_for_email"):
                    # First update the profile with the device ID we're using
                    if hasattr(server, "profile_manager") and self.device_id:
                        profile = server.profile_manager.get_profile_for_email(email)
                        if profile and profile.get("emulator_id") != self.device_id:
                            logger.info(
                                f"Updating profile device ID to {self.device_id} before port allocation"
                            )
                            if hasattr(server.profile_manager, "_save_profile_status"):
                                server.profile_manager._save_profile_status(
                                    email, profile.get("avd_name"), self.device_id
                                )

                    allocated_ports = server.get_unique_ports_for_email(email)

                if allocated_ports:
                    # Use the allocated ports
                    options.set_capability("systemPort", allocated_ports["systemPort"])
                    options.set_capability("bootstrapPort", allocated_ports["bootstrapPort"])
                    options.set_capability("chromedriverPort", allocated_ports["chromedriverPort"])
                    options.set_capability("mjpegServerPort", allocated_ports["mjpegServerPort"])
                    logger.info(f"Using allocated ports for {email}: {allocated_ports}")
                else:
                    # Fallback to hash-based approach using centralized port utilities
                    from server.utils.port_utils import PortConfig

                    instance_num = hash(instance_id) % 50  # Limit to 50 instances
                    options.set_capability("systemPort", PortConfig.SYSTEM_BASE_PORT + instance_num)
                    options.set_capability("bootstrapPort", PortConfig.BOOTSTRAP_BASE_PORT + instance_num)
                    options.set_capability(
                        "chromedriverPort", PortConfig.CHROMEDRIVER_BASE_PORT + instance_num
                    )
                    options.set_capability("mjpegServerPort", PortConfig.MJPEG_BASE_PORT + instance_num)
                    logger.warning(f"Using hash-based ports for {email} (fallback)")

                # Temporary directory for this instance
                import tempfile

                temp_dir = os.path.join(tempfile.gettempdir(), f"appium_{instance_id}")
                os.makedirs(temp_dir, exist_ok=True)
                options.set_capability("tmpDir", temp_dir)

            # Clean up system files to avoid conflicts
            options.set_capability("clearSystemFiles", True)
            options.set_capability("skipServerInstallation", False)

            # Use longer timeout on webdriver initialization
            import socket

            original_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(10)  # 10 second timeout - increased from 5
            # Determine Appium port
            # If automator has a profile manager with a specific port for this email, use that
            if (
                self.automator
                and hasattr(self.automator, "profile_manager")
                and hasattr(self.automator.profile_manager, "get_current_profile")
            ):
                current_profile = self.automator.profile_manager.get_current_profile()
                if current_profile and "email" in current_profile:
                    email = current_profile["email"]
                    # Try to get appium_port from server's allocated ports or appium_processes
                    try:
                        server = current_app.config.get("server_instance")
                        if server:
                            # First try to get from allocated ports
                            if hasattr(server, "get_unique_ports_for_email"):
                                allocated_ports = server.get_unique_ports_for_email(email)
                                if allocated_ports and "appiumPort" in allocated_ports:
                                    self.appium_port = allocated_ports["appiumPort"]
                                    logger.info(f"Using allocated appium port {self.appium_port} for {email}")
                            # Fall back to appium_processes if available
                            elif hasattr(server, "appium_processes") and email in server.appium_processes:
                                self.appium_port = server.appium_processes[email]["port"]
                    except (ImportError, RuntimeError) as e:
                        logger.debug(f"Could not access server for Appium port: {e}")

            # First verify the Appium server is actually responding
            # This prevents attempting to connect to a non-responsive server
            import time

            import requests

            max_retries = 3
            retry_delay = 1

            # Ensure we have a valid appium port - use centralized default as fallback
            from server.utils.port_utils import PortConfig

            appium_port = self.appium_port if self.appium_port is not None else PortConfig.APPIUM_BASE_PORT

            for attempt in range(max_retries):
                try:
                    logger.info(
                        f"Checking Appium server (127.0.0.1:{appium_port}) status (attempt {attempt+1}/{max_retries})..."
                    )
                    status_response = requests.get(f"http://127.0.0.1:{appium_port}/status", timeout=5)
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
                except requests.RequestException as e:
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Failed to connect to Appium server on port {appium_port} after {max_retries} attempts: {e}"
                        )

                        # Check if we need to start Appium ourselves
                        try:
                            server = current_app.config.get("server_instance")
                            if server:
                                logger.info(f"Attempting to start Appium server directly from driver...")
                                email = (
                                    current_profile["email"]
                                    if current_profile and "email" in current_profile
                                    else None
                                )
                                if email:
                                    started = server.start_appium(port=appium_port, email=email)
                                    if not started:
                                        logger.error("Failed to start Appium server from driver")
                                    else:
                                        time.sleep(0.2)  # Give it time to start
                                        continue  # Retry the check
                        except Exception as start_error:
                            logger.error(f"Error starting Appium from driver: {start_error}")

                        raise Exception(f"Cannot connect to Appium server on port {appium_port}: {e}")

                    logger.warning(f"Appium connection error (attempt {attempt+1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2

            # Initialize driver with the options using the specific port
            # Ensure we have a valid appium port - use centralized default as fallback
            from server.utils.port_utils import PortConfig

            appium_port = self.appium_port if self.appium_port is not None else PortConfig.APPIUM_BASE_PORT

            logger.info(f"Connecting to Appium on port {appium_port} for device {self.device_id}")

            # Add retry logic for driver creation to handle socket hang-ups
            driver_creation_retries = 3
            driver_retry_delay = 5

            for driver_attempt in range(driver_creation_retries):
                self.driver = webdriver.Remote(f"http://127.0.0.1:{appium_port}", options=options)
                logger.info(
                    f"Driver initialized successfully on port {appium_port} for device {self.device_id}"
                )
                break
            socket.setdefaulttimeout(original_timeout)  # Restore original timeout

            # Force a state check after driver initialization with a timeout
            import concurrent.futures
            import threading

            def check_connection():
                self.driver.current_activity  # This will force Appium to check connection
                return True

            # Run the check with a timeout
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(check_connection)
                try:
                    result = future.result(timeout=15)  # 15 second timeout - increased from 5
                    return True
                except concurrent.futures.TimeoutError:
                    logger.error("Connection check timed out after 15 seconds")

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

        # Try to reconnect up to max retries
        for attempt in range(self._max_session_retries):
            try:
                logger.info(f"Reconnection attempt {attempt + 1}/{self._max_session_retries}")

                # Clean up old session
                try:
                    if self.driver:
                        self.driver.quit()
                except Exception:
                    pass

                self.driver = None
                Driver._initialized = False

                # Reinitialize through automator if available
                if self.automator:
                    if self.automator.initialize_driver():
                        logger.info("Successfully reconnected driver session")
                        self._session_retries = 0
                        return True
                    else:
                        logger.error("Failed to reinitialize driver through automator")
                else:
                    logger.error("No automator reference available for reconnection")

            except Exception as e:
                logger.error(f"Error during reconnection attempt {attempt + 1}: {e}")

        logger.error("Failed to reconnect driver session after all attempts")
        return False

    def get_appium_driver_instance(self):
        """Get the Appium driver instance, ensuring session is active"""
        self._ensure_session_active()
        return self.driver

    def get_device_id(self):
        """Get the current device ID"""
        return self.device_id

    def quit(self):
        """Quit the Appium driver"""
        logger.info(f"Quitting driver: {self.driver}")
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.device_id = None
            Driver._initialized = False  # Allow reinitialization

    @classmethod
    def reset(cls):
        """Reset the singleton instance"""
        logger.info("Resetting Driver")
        if cls._instance:
            try:
                cls._instance.quit()
            except Exception as e:
                logger.error(f"Error quitting driver: {e}")
            cls._instance = None
            cls._initialized = False
