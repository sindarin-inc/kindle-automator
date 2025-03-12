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
            Driver._initialized = True

    def _get_emulator_device_id(self) -> Optional[str]:
        """Get the emulator device ID from adb devices."""
        try:
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
                return True

            logger.info(f"Disabling HW overlays on device {self.device_id}")
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", "settings", "put", "global", "debug.hw.overlay", "1"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to handle HW overlays: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error handling HW overlays: {e}")
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

            # Get device ID first
            self.device_id = self._get_emulator_device_id()
            if not self.device_id:
                return False

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

            # Get Kindle launch activity
            app_activity = self._get_kindle_launch_activity()
            if not app_activity:
                return False

            # Initialize driver with retry logic
            for attempt in range(1, 4):
                try:
                    logger.info(f"Attempting to initialize driver (attempt {attempt}/3)...")

                    options = UiAutomator2Options()
                    options.platform_name = "Android"
                    options.automation_name = "UiAutomator2"
                    options.device_name = self.device_id
                    options.app_package = "com.amazon.kindle"
                    options.app_activity = app_activity
                    options.app_wait_activity = "com.amazon.kindle.*"
                    options.no_reset = True
                    options.auto_grant_permissions = True
                    options.enable_multi_windows = True
                    options.ignore_unimportant_views = False
                    options.allow_invisible_elements = True
                    options.enable_multi_windows = True
                    options.new_command_timeout = 60 * 60 * 24 * 7  # 7 days
                    options.set_capability("adbExecTimeout", 120000)  # 120 seconds timeout for ADB commands

                    self.driver = webdriver.Remote("http://127.0.0.1:4723", options=options)
                    logger.info("Driver initialized successfully")

                    # Force a state check after driver initialization
                    self.driver.current_activity  # This will force Appium to check connection

                    return True

                except Exception as e:
                    logger.info(f"Failed to initialize driver (attempt {attempt}/3): {e}")
                    if attempt < 3:
                        logger.info("Waiting 1 second before retrying...")
                        time.sleep(1)
                    else:
                        logger.error("Failed to initialize driver after 3 attempts")
                        logger.error(f"Last error: {e}")
                        logger.info("\nPlease ensure:")
                        logger.info("1. Appium server is running (start with 'appium')")
                        logger.info("2. Android SDK is installed at ~/Library/Android/sdk")
                        logger.info("3. Android device/emulator is connected (check with 'adb devices')")
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
