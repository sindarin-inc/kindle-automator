from appium import webdriver
from appium.options.android import UiAutomator2Options
from views.logger import logger
import time


class Driver:
    def __init__(self):
        self.driver = None

    def initialize(self):
        """Initialize Appium driver with retry logic"""
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.device_name = "emulator-5554"
        options.app_package = "com.amazon.kindle"
        options.app_activity = "com.amazon.kindle.UpgradePage"
        options.no_reset = True
        options.set_capability("appium:systemPort", 8202)
        options.set_capability("appium:udid", "emulator-5554")

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

    def quit(self):
        """Quit the Appium driver"""
        if self.driver:
            self.driver.quit()
