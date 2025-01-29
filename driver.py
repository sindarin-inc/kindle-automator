from appium import webdriver
from appium.options.android import UiAutomator2Options
from views.core.logger import logger
import time
import os
import subprocess
from typing import Optional


class Driver:
    def __init__(self):
        self.driver = None
        self.device_id = None

    def _get_emulator_device_id(self) -> Optional[str]:
        """Get the emulator device ID from adb devices."""
        try:
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

    def initialize(self) -> bool:
        """Initialize Appium driver with retry logic. Safe to call multiple times."""
        # If we already have a driver, check if it's healthy
        if self.driver:
            try:
                # Basic health check - try to get current activity
                self.driver.current_activity
                logger.info("Existing driver is healthy, reusing it")
                return True
            except Exception as e:
                logger.info("Existing driver is unhealthy, will reinitialize")
                self.quit()  # Clean up unhealthy driver

        # Set up Android SDK environment variables
        android_home = os.path.expanduser("~/Library/Android/sdk")
        os.environ["ANDROID_HOME"] = android_home
        os.environ["ANDROID_SDK_ROOT"] = android_home
        os.environ["PATH"] = f"{os.environ.get('PATH')}:{android_home}/tools:{android_home}/platform-tools"

        # Get the emulator device ID
        self.device_id = self._get_emulator_device_id()
        if not self.device_id:
            logger.error("No emulator found. Please start an Android emulator first.")
            return False

        # Force ADB to use emulator
        os.environ["ANDROID_SERIAL"] = self.device_id
        logger.info(f"Using emulator device: {self.device_id}")

        # Disable HW overlays for better WebView visibility
        if not self._disable_hw_overlays():
            logger.warning("Failed to disable HW overlays, continuing anyway...")

        # Set up Appium options
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.device_name = self.device_id
        options.app_package = "com.amazon.kindle"
        options.app_activity = "com.amazon.kindle.UpgradePage"
        options.app_wait_activity = "com.amazon.kindle.*"
        options.automation_name = "UiAutomator2"
        options.no_reset = True

        # Add additional capabilities
        options.set_capability("appium:automationName", "UiAutomator2")
        options.set_capability("appium:platformName", "Android")
        options.set_capability("appium:deviceName", self.device_id)
        options.set_capability("appium:avd", "Sol_Reader_0.68_Prototype_API_35")
        options.set_capability("appium:isEmulator", True)
        options.set_capability("appium:avdLaunchTimeout", 180000)
        options.set_capability("appium:avdReadyTimeout", 180000)
        options.set_capability("appium:noReset", True)
        options.set_capability("appium:newCommandTimeout", 300)
        options.set_capability("appium:autoGrantPermissions", True)
        options.set_capability("appium:waitForIdleTimeout", 5000)
        options.set_capability("appium:systemPort", 8202)
        options.set_capability("appium:enforceXPath1", True)
        options.set_capability("appium:skipServerInstallation", False)
        options.set_capability("appium:skipDeviceInitialization", False)

        max_attempts = 3
        attempt = 1
        last_error = None

        while attempt <= max_attempts:
            try:
                logger.info(f"Attempting to initialize driver (attempt {attempt}/{max_attempts})...")
                self.driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=options)
                logger.info("Driver initialized successfully")
                return True
            except Exception as e:
                last_error = str(e)
                logger.error(f"Failed to initialize driver (attempt {attempt}/{max_attempts}): {e}")
                if attempt < max_attempts:
                    logger.info("Waiting 1 second before retrying...")
                    time.sleep(1)
                attempt += 1

        logger.error(f"Failed to initialize driver after {max_attempts} attempts")
        logger.error(f"Last error: {last_error}")
        logger.info("\nPlease ensure:")
        logger.info("1. Appium server is running (start with 'appium')")
        logger.info("2. Android SDK is installed at ~/Library/Android/sdk")
        logger.info("3. Android device/emulator is connected (check with 'adb devices')")
        return False

    def get_driver(self):
        """Get the Appium driver instance"""
        return self.driver

    def get_device_id(self):
        """Get the current device ID"""
        return self.device_id

    def quit(self):
        """Quit the Appium driver"""
        if self.driver:
            self.driver.quit()
