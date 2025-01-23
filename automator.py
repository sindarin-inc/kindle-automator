import time
import os
from appium import webdriver
from appium.options.android import UiAutomator2Options

from views.view_inspector import ViewInspector
from views.state_machine import KindleStateMachine
from handlers.auth_handler import AuthenticationHandler
from handlers.permissions_handler import PermissionsHandler
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.core.logger import logger


class KindleAutomator:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.driver = None
        self.view_inspector = ViewInspector()
        self.auth_handler = None
        self.permissions_handler = None
        self.library_handler = None
        self.reader_handler = None
        self.state_machine = None

    def initialize_driver(self):
        # Set up Android SDK environment variables
        android_home = os.path.expanduser("~/Library/Android/sdk")
        os.environ["ANDROID_HOME"] = android_home
        os.environ["ANDROID_SDK_ROOT"] = android_home
        os.environ["PATH"] = f"{os.environ.get('PATH')}:{android_home}/tools:{android_home}/platform-tools"

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.device_name = "emulator-5554"
        options.app_package = "com.amazon.kindle"
        options.app_activity = "com.amazon.kindle.UpgradePage"
        options.app_wait_activity = "com.amazon.kindle.*"
        options.automation_name = "UiAutomator2"
        options.no_reset = True

        # Add additional capabilities
        options.set_capability("appium:automationName", "UiAutomator2")
        options.set_capability("appium:platformName", "Android")
        options.set_capability("appium:deviceName", "emulator-5554")
        options.set_capability("appium:noReset", True)
        options.set_capability("appium:newCommandTimeout", 300)
        options.set_capability("appium:autoGrantPermissions", True)
        options.set_capability("appium:waitForIdleTimeout", 5000)
        options.set_capability("appium:systemPort", 8202)

        max_attempts = 3
        attempt = 1
        last_error = None

        while attempt <= max_attempts:
            try:
                logger.info(f"Attempting to initialize driver (attempt {attempt}/{max_attempts})...")
                self.driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=options)

                # Initialize all handlers with the driver
                self.view_inspector.set_driver(self.driver)
                self.auth_handler = AuthenticationHandler(self.driver, self.email, self.password)
                self.permissions_handler = PermissionsHandler(self.driver)
                self.library_handler = LibraryHandler(self.driver)
                self.reader_handler = ReaderHandler(self.driver)

                # Initialize state machine
                self.state_machine = KindleStateMachine(
                    self.view_inspector,
                    self.auth_handler,
                    self.permissions_handler,
                    self.library_handler,
                )

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

    def handle_initial_setup(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()

    def run(self):
        """Main automation flow"""
        try:
            # Initialize the driver
            if not self.initialize_driver():
                print("Failed to initialize driver")
                return False

            # Handle initial setup and ensure we reach library
            if not self.handle_initial_setup():
                print("Failed to reach library view")
                return False

            return True

        except Exception as e:
            print(f"Automation failed: {e}")
            return False


def main():
    try:
        from config import AMAZON_EMAIL, AMAZON_PASSWORD
    except ImportError:
        logger.warning("No config.py found. Using default credentials from config.template.py")
        from config_template import AMAZON_EMAIL, AMAZON_PASSWORD

    automator = KindleAutomator(AMAZON_EMAIL, AMAZON_PASSWORD)
    automator.run()


if __name__ == "__main__":
    main()
