import logging
import os
import subprocess
import time
from typing import Optional

from appium import webdriver
from appium.options.android import UiAutomator2Options

logger = logging.getLogger(__name__)


class Driver:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            logger.info("Creating new Driver instance")
            cls._instance = super(Driver, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not Driver._initialized:
            logger.info("Initializing Driver")
            self.driver = None
            self.device_id = None
            self.automator = None  # Reference to the automator instance
            Driver._initialized = True

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
                logger.info(f"Checking for specific device ID: {specific_device_id}")
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
                        logger.info(
                            f"Specific device {specific_device_id} verified, model: {verify_result.stdout.strip()}"
                        )
                        return specific_device_id
                    except Exception as e:
                        logger.warning(f"Could not verify specific device {specific_device_id}: {e}")
                        # Continue to regular device search
                else:
                    logger.warning(f"Specified device ID {specific_device_id} not found or not ready")
                    # Continue to regular device search if the specific one isn't available

            # Regular device search logic
            result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if "emulator-" in line and "device" in line:
                    device_id = line.split()[0]
                    logger.info(f"Found device ID: {device_id}, attempting to verify...")
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
                    logger.info(f"Found device ID: {device_id}, attempting to verify...")
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
            if (self.automator and hasattr(self.automator, 'profile_manager') and 
                self.automator.profile_manager.current_profile):
                
                profile = self.automator.profile_manager.current_profile
                device_id = profile.get("emulator_id")
                
                # If this is the same device and we already set hw_overlays_disabled, skip
                if device_id == self.device_id and profile.get("hw_overlays_disabled", False):
                    logger.info(f"HW overlays already disabled for device {self.device_id}, skipping")
                    return True
                
            # Check current state
            logger.info(f"Checking HW overlays state on device {self.device_id}")
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", "settings", "get", "global", "debug.hw.overlay"],
                check=True,
                capture_output=True,
                text=True,
            )
            current_state = result.stdout.strip()

            if current_state == "1":
                logger.info("HW overlays are already disabled")
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
            if (self.automator and hasattr(self.automator, 'profile_manager') and 
                self.automator.profile_manager.current_profile):
                
                profile = self.automator.profile_manager.current_profile
                email = profile.get("email")
                avd_name = profile.get("avd_name")
                
                if email and avd_name:
                    # Update the setting in the current profile
                    profile[setting_name] = value
                    
                    # Update the profile in the profile manager
                    emulator_id = profile.get("emulator_id")
                    self.automator.profile_manager._save_current_profile(email, avd_name, emulator_id)
                    
                    # Also update user preferences for persistence
                    if email not in self.automator.profile_manager.user_preferences:
                        self.automator.profile_manager.user_preferences[email] = {}
                    
                    self.automator.profile_manager.user_preferences[email][setting_name] = value
                    self.automator.profile_manager._save_user_preferences()
                    
                    logger.info(f"Updated profile setting {setting_name}={value} for {email}")
        except Exception as e:
            logger.error(f"Error updating profile setting {setting_name}: {e}")
            # Continue execution even if we can't update the profile

    def _disable_animations(self) -> bool:
        """Disable all system animations to improve reliability."""
        try:
            # Check if we already applied this setting to the current emulator
            if (self.automator and hasattr(self.automator, 'profile_manager') and 
                self.automator.profile_manager.current_profile):
                
                profile = self.automator.profile_manager.current_profile
                device_id = profile.get("emulator_id")
                
                # If this is the same device and we already set animations_disabled, skip
                if device_id == self.device_id and profile.get("animations_disabled", False):
                    logger.info(f"System animations already disabled for device {self.device_id}, skipping")
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

            logger.info("System animations disabled successfully")
            
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
            if (self.automator and hasattr(self.automator, 'profile_manager') and 
                self.automator.profile_manager.current_profile):
                
                profile = self.automator.profile_manager.current_profile
                device_id = profile.get("emulator_id")
                
                # If this is the same device and we already set sleep_disabled, skip
                if device_id == self.device_id and profile.get("sleep_disabled", False):
                    logger.info(f"Sleep already disabled for device {self.device_id}, skipping")
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

            logger.info("Sleep and app standby modes disabled successfully")
            
            # Record this setting in the profile
            self._update_profile_setting("sleep_disabled", True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to disable sleep: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error disabling sleep: {e}")
            return False

    def _cleanup_old_sessions(self):
        """Clean up any existing UiAutomator2 sessions."""
        try:
            logger.info("Cleaning up old UiAutomator2 sessions...")
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
            logger.info(f"Checking Kindle installation on device {self.device_id}")
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

    def _install_kindle(self) -> bool:
        """Install the Kindle app on the device."""
        try:
            logger.info(f"Installing Kindle on device {self.device_id}")
            apk_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "android-sdk",
                "apk",
                "kindle.apk",
            )
            if not os.path.exists(apk_path):
                logger.error(f"Kindle APK not found at {apk_path}")
                # Try ../ansible/roles/kindle/files/com.amazon.kindle*.apk. Will have to find the full file name
                # from the list of files in the directory
                kindle_apk_dir = os.path.join(
                    os.path.dirname(__file__),
                    "ansible",
                    "roles",
                    "android_arm",
                    "files",
                )
                apk_files = os.listdir(kindle_apk_dir)
                for file in apk_files:
                    if "com.amazon.kindle" in file:
                        apk_path = os.path.join(kindle_apk_dir, file)
                        break
                if not os.path.exists(apk_path):
                    logger.error(f"Kindle APK not found at {apk_path}")
                    return False

            subprocess.run(
                ["adb", "-s", self.device_id, "install", "-r", apk_path],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Kindle app installed successfully")
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
        try:
            if self.driver:
                # Test if driver is still connected
                try:
                    self.driver.current_activity
                except Exception as e:
                    logger.info("Driver not connected - reinitializing")
                    self.driver = None
                else:
                    logger.info("Driver already initialized")
                    return True

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
                        logger.info(f"Using device ID {target_device_id} for AVD {avd_name}")

            # Get device ID, preferring the specific one if provided
            self.device_id = self._get_emulator_device_id(target_device_id)
            if not self.device_id:
                return False

            # If we found a device ID, update the current profile with it
            if self.automator and hasattr(self.automator, "profile_manager") and self.device_id:
                if self.automator.profile_manager.current_profile:
                    # Update the current profile with the actual device ID
                    email = self.automator.profile_manager.current_profile.get("email")
                    avd_name = self.automator.profile_manager.current_profile.get("avd_name")

                    if email and avd_name:
                        logger.info(f"Updating profile for {email} with device ID: {self.device_id}")
                        self.automator.profile_manager._save_current_profile(email, avd_name, self.device_id)

            # Check if app is installed
            if not self._is_kindle_installed():
                logger.error("Kindle app not installed - attempting to install")
                if not self._install_kindle():
                    logger.error("Failed to install Kindle app")
                    return False
                logger.info("Successfully installed Kindle app")

            # Clean up any existing sessions
            self._cleanup_old_sessions()

            # Check and disable hardware overlays
            self._disable_hw_overlays()

            # Disable all system animations
            self._disable_animations()

            # Disable sleep and app standby to prevent device and app from sleeping
            self._disable_sleep()

            # Get Kindle launch activity
            app_activity = self._get_kindle_launch_activity()
            if not app_activity:
                return False

            # First, dump the device state to help debug initialization issues
            try:
                # Check device status and dump XML
                logger.info("Checking device state before driver initialization...")
                import os

                from server.logging_config import store_page_source

                # Dump the current screen content via uiautomator
                try:
                    # Create dumps directory if it doesn't exist
                    os.makedirs("fixtures/dumps", exist_ok=True)

                    # Create a UI dump using uiautomator2
                    dump_cmd = [
                        "adb",
                        "-s",
                        self.device_id,
                        "shell",
                        "uiautomator dump /sdcard/window_dump.xml",
                    ]
                    result = subprocess.run(dump_cmd, check=True, capture_output=True, text=True)

                    # Pull the file
                    pull_cmd = [
                        "adb",
                        "-s",
                        self.device_id,
                        "pull",
                        "/sdcard/window_dump.xml",
                        "fixtures/dumps/pre_driver_init.xml",
                    ]
                    result = subprocess.run(pull_cmd, check=True, capture_output=True, text=True)
                    logger.info("Saved pre-initialization UI dump to fixtures/dumps/pre_driver_init.xml")

                    # Also take a screenshot
                    screenshot_cmd = ["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/screen.png"]
                    result = subprocess.run(screenshot_cmd, check=True, capture_output=True, text=True)

                    # Pull the screenshot
                    os.makedirs("screenshots", exist_ok=True)
                    pull_screenshot_cmd = [
                        "adb",
                        "-s",
                        self.device_id,
                        "pull",
                        "/sdcard/screen.png",
                        "screenshots/pre_driver_init.png",
                    ]
                    result = subprocess.run(pull_screenshot_cmd, check=True, capture_output=True, text=True)
                    logger.info("Saved pre-initialization screenshot to screenshots/pre_driver_init.png")
                except Exception as e:
                    logger.warning(f"Failed to dump device UI state: {e}")
            except Exception as e:
                logger.warning(f"Exception getting device state: {e}")

            # Initialize driver with retry logic
            for attempt in range(1, 6):  # Increase to 5 attempts
                try:
                    logger.info(f"Attempting to initialize driver (attempt {attempt}/5)...")

                    options = UiAutomator2Options()
                    options.platform_name = "Android"
                    options.automation_name = "UiAutomator2"
                    options.device_name = self.device_id
                    options.app_package = "com.amazon.kindle"
                    options.app_activity = app_activity
                    options.app_wait_activity = (
                        "com.amazon.kindle.*,com.amazon.kcp.*"  # Add com.amazon.kcp.* activities
                    )
                    options.no_reset = True
                    options.auto_grant_permissions = True
                    options.enable_multi_windows = True
                    options.ignore_unimportant_views = False
                    options.allow_invisible_elements = True
                    options.new_command_timeout = 60 * 60 * 24 * 7  # 7 days
                    # Set longer timeouts to avoid connection issues
                    options.set_capability(
                        "uiautomator2ServerLaunchTimeout", 20000
                    )  # 20 seconds timeout for UiAutomator2 server launch
                    # Leave this higher since we need time for ADB commands during actual operations
                    options.set_capability("adbExecTimeout", 120000)  # 120 seconds timeout for ADB commands
                    options.set_capability("connectionTimeout", 10000)  # 10 seconds for connection timeout

                    # Use longer timeout on webdriver initialization
                    import socket

                    original_timeout = socket.getdefaulttimeout()
                    socket.setdefaulttimeout(10)  # 10 second timeout - increased from 5
                    try:
                        self.driver = webdriver.Remote("http://127.0.0.1:4723", options=options)
                        logger.info("Driver initialized successfully")
                    finally:
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
                            logger.info("Connection check successful")
                            return True
                        except concurrent.futures.TimeoutError:
                            logger.error("Connection check timed out after 15 seconds")

                            # Try to dump device state again to diagnose the issue
                            try:
                                logger.info("Trying to capture device state after timeout...")
                                dump_cmd = [
                                    "adb",
                                    "-s",
                                    self.device_id,
                                    "shell",
                                    "uiautomator dump /sdcard/window_dump_after_timeout.xml",
                                ]
                                result = subprocess.run(dump_cmd, check=True, capture_output=True, text=True)

                                # Pull the file
                                pull_cmd = [
                                    "adb",
                                    "-s",
                                    self.device_id,
                                    "pull",
                                    "/sdcard/window_dump_after_timeout.xml",
                                    "fixtures/dumps/post_timeout.xml",
                                ]
                                result = subprocess.run(pull_cmd, check=True, capture_output=True, text=True)
                                logger.info("Saved post-timeout UI dump to fixtures/dumps/post_timeout.xml")

                                # Also take a screenshot
                                screenshot_cmd = [
                                    "adb",
                                    "-s",
                                    self.device_id,
                                    "shell",
                                    "screencap -p /sdcard/screen_after_timeout.png",
                                ]
                                result = subprocess.run(
                                    screenshot_cmd, check=True, capture_output=True, text=True
                                )

                                # Pull the screenshot
                                pull_screenshot_cmd = [
                                    "adb",
                                    "-s",
                                    self.device_id,
                                    "pull",
                                    "/sdcard/screen_after_timeout.png",
                                    "screenshots/post_timeout.png",
                                ]
                                result = subprocess.run(
                                    pull_screenshot_cmd, check=True, capture_output=True, text=True
                                )
                                logger.info("Saved post-timeout screenshot to screenshots/post_timeout.png")
                            except Exception as e:
                                logger.warning(f"Failed to capture post-timeout device state: {e}")

                            try:
                                # Try to quit the driver that may be in a bad state
                                if self.driver:
                                    self.driver.quit()
                            except:
                                pass
                            self.driver = None
                            raise TimeoutError("Connection check timed out")

                except Exception as e:
                    logger.info(f"Failed to initialize driver (attempt {attempt}/5): {e}")
                    if attempt < 5:
                        # Increase the retry delay progressively to give more time for app initialization
                        retry_delay = attempt * 2  # 2, 4, 6, 8 seconds
                        logger.info(f"Waiting {retry_delay} seconds before retrying...")
                        time.sleep(retry_delay)

                        # Dump device state between retries to see what's happening
                        try:
                            logger.info(f"Dumping device state before retry {attempt+1}...")
                            dump_cmd = [
                                "adb",
                                "-s",
                                self.device_id,
                                "shell",
                                "uiautomator dump /sdcard/retry_dump.xml",
                            ]
                            result = subprocess.run(dump_cmd, check=True, capture_output=True, text=True)

                            pull_cmd = [
                                "adb",
                                "-s",
                                self.device_id,
                                "pull",
                                "/sdcard/retry_dump.xml",
                                f"fixtures/dumps/retry_{attempt}_dump.xml",
                            ]
                            result = subprocess.run(pull_cmd, check=True, capture_output=True, text=True)
                            logger.info(f"Saved retry dump to fixtures/dumps/retry_{attempt}_dump.xml")

                            # Also take a screenshot
                            screenshot_cmd = [
                                "adb",
                                "-s",
                                self.device_id,
                                "shell",
                                "screencap -p /sdcard/retry_screen.png",
                            ]
                            result = subprocess.run(
                                screenshot_cmd, check=True, capture_output=True, text=True
                            )

                            pull_screenshot_cmd = [
                                "adb",
                                "-s",
                                self.device_id,
                                "pull",
                                "/sdcard/retry_screen.png",
                                f"screenshots/retry_{attempt}_screen.png",
                            ]
                            result = subprocess.run(
                                pull_screenshot_cmd, check=True, capture_output=True, text=True
                            )
                            logger.info(f"Saved retry screenshot to screenshots/retry_{attempt}_screen.png")

                            # Try to launch Kindle app directly before the next retry
                            if attempt > 1:  # Only do this after the first retry fails
                                launch_cmd = [
                                    "adb",
                                    "-s",
                                    self.device_id,
                                    "shell",
                                    f"am start -n com.amazon.kindle/{app_activity}",
                                ]
                                result = subprocess.run(
                                    launch_cmd, check=True, capture_output=True, text=True
                                )
                                logger.info(
                                    f"Explicitly launched Kindle app before retry: {result.stdout.strip()}"
                                )
                                time.sleep(2)  # Give the app a moment to start
                        except Exception as dump_error:
                            logger.warning(f"Failed to dump device state before retry: {dump_error}")
                    else:
                        logger.error("Failed to initialize driver after 5 attempts")
                        logger.error(f"Last error: {e}")
                        logger.info("\nPlease ensure:")
                        logger.info("1. Appium server is running (start with 'appium')")
                        logger.info("2. Android SDK is installed at ~/Library/Android/sdk")
                        logger.info("3. Android device/emulator is connected (check with 'adb devices')")
                        logger.info(
                            "4. Check the XML dumps and screenshots in fixtures/dumps/ and screenshots/ for debugging"
                        )
                        return False

        except Exception as e:
            logger.error(f"Error initializing driver: {e}")
            return False

    def get_driver(self):
        """Get the Appium driver instance"""
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
