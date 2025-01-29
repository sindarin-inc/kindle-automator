import argparse
import os
import socket
import subprocess
import time
from typing import Tuple, Union

from appium import webdriver
from appium.options.android import UiAutomator2Options
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.core.logger import logger
from views.state_machine import AppState, KindleStateMachine
from driver import Driver


class KindleAutomator:
    def __init__(self, email, password, captcha_solution):
        self.email = email
        self.password = password
        self.captcha_solution = captcha_solution
        self.driver = None
        self.state_machine = None
        self.appium_process = None
        self.device_id = None  # Will be set during initialization
        self.library_handler = None
        self.reader_handler = None
        self.apk_path = os.path.join(
            "ansible",
            "roles",
            "android",
            "files",
            "com.amazon.kindle_8.113.0.100(2.0.29451.0)-1285953011_minAPI28(arm64-v8a)(nodpi).com.apk",
        )

    def _is_port_in_use(self, port):
        """Check if a port is in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", port)) == 0

    def ensure_appium_running(self):
        """Ensure Appium server is running, start it if not."""
        # Check if Appium is already running on port 4723
        if self._is_port_in_use(4723):
            logger.info("Appium server is already running")
            return True

        try:
            logger.info("Starting Appium server...")
            # Start Appium server in the background
            self.appium_process = subprocess.Popen(
                ["appium"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

            # Wait for server to start (max 10 seconds)
            start_time = time.time()
            while time.time() - start_time < 10:
                if self._is_port_in_use(4723):
                    logger.info("Appium server started successfully")
                    return True
                time.sleep(0.5)

            logger.error("Timeout waiting for Appium server to start")
            return False

        except Exception as e:
            logger.error(f"Failed to start Appium server: {e}")
            return False

    def cleanup(self):
        """Cleanup resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

        if self.appium_process:
            try:
                self.appium_process.terminate()
                self.appium_process.wait(timeout=5)
            except:
                pass

    def _is_kindle_installed(self):
        """Check if the Kindle app is installed on the device."""
        try:
            logger.info(f"Checking Kindle installation on device {self.device_id}")
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", "pm", "list", "packages", "com.amazon.kindle"],
                capture_output=True,
                text=True,
            )
            return "com.amazon.kindle" in result.stdout
        except Exception as e:
            logger.error(f"Error checking Kindle installation: {e}")
            return False

    def install_kindle(self):
        """Install the Kindle APK using Appium."""
        try:
            logger.info(f"Installing Kindle APK on device {self.device_id}...")
            if not os.path.exists(self.apk_path):
                logger.error(f"APK file not found at {self.apk_path}")
                return False

            # Set up Appium options for installation
            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.device_name = self.device_id
            options.app = os.path.abspath(self.apk_path)
            options.automation_name = "UiAutomator2"

            # Create a temporary driver just for installation
            temp_driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=options)
            temp_driver.quit()

            logger.info("Kindle APK installed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to install Kindle APK: {e}")
            return False

    def uninstall_kindle(self):
        """Uninstall the Kindle app."""
        try:
            logger.info(f"Uninstalling Kindle app from device {self.device_id}...")
            subprocess.run(
                ["adb", "-s", self.device_id, "uninstall", "com.amazon.kindle"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Kindle app uninstalled successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to uninstall Kindle app: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error uninstalling Kindle app: {e}")
            return False

    def _disable_hw_overlays(self):
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

    def _is_driver_healthy(self):
        """Check if the Appium driver is connected and responsive."""
        try:
            if not self.driver:
                return False
            # Try to get the current activity - a lightweight operation
            self.driver.current_activity
            return True
        except Exception as e:
            logger.debug(f"Driver health check failed: {e}")
            return False

    def _is_kindle_responsive(self):
        """Check if the Kindle app is responsive."""
        try:
            if not self.driver:
                return False
            # Try to get the current package - a lightweight operation
            current_package = self.driver.current_package
            return current_package == "com.amazon.kindle"
        except Exception as e:
            logger.debug(f"Kindle responsiveness check failed: {e}")
            return False

    def ensure_driver_running(self):
        """Ensure the driver is running and healthy, initialize if needed."""
        # Quick health check first
        if self._is_driver_healthy() and self._is_kindle_responsive():
            logger.debug("Driver is healthy and Kindle is responsive")
            return True

        # If not healthy, try to initialize
        return self.initialize_driver()

    def _get_emulator_device_id(self):
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

    def initialize_driver(self):
        """Initialize the Appium driver and Kindle app. Safe to call multiple times."""
        try:
            # If we already have a driver, check if it's healthy
            if self.driver:
                try:
                    # Basic health check
                    self.driver.current_activity
                    logger.info("Existing driver is healthy")
                    return True
                except Exception as e:
                    logger.info("Existing driver is unhealthy, reinitializing...")
                    self.cleanup()  # Clean up properly

            # Create and initialize driver
            driver = Driver()
            if not driver.initialize():
                return False

            self.driver = driver.get_driver()
            self.device_id = driver.get_device_id()

            # Initialize state machine with credentials
            self.state_machine = KindleStateMachine(
                self.driver,
                email=self.email,
                password=self.password,
                captcha_solution=self.captcha_solution,
            )

            # Initialize handlers
            self.library_handler = LibraryHandler(self.driver)
            self.reader_handler = ReaderHandler(self.driver)

            logger.info("Driver initialization completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error during driver initialization: {e}")
            self.cleanup()  # Clean up on any error
            return False

    def handle_initial_setup(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()

    def run(self, reading_book_title=None):
        """Main automation flow.

        Args:
            reading_book_title (str, optional): If provided, will attempt to open and read this book.
                                              If None, will just list available books.

        Returns:
            Union[bool, Tuple[bool, str]]: If reading_book_title is None, returns success boolean.
                                         If reading_book_title is provided, returns (success, page_number).
        """
        try:
            # Initialize the driver
            if not self.initialize_driver():
                logger.error("Failed to initialize driver")
                return (False, None) if reading_book_title else False

            # Handle initial setup and ensure we reach library
            if not self.handle_initial_setup():
                logger.error("Failed to reach library view")
                return (False, None) if reading_book_title else False

            # Check if we're on a captcha screen
            if self.state_machine.current_state == AppState.CAPTCHA:
                logger.info("Automation stopped at captcha screen. Please solve the captcha in captcha.png")
                logger.info("Then update CAPTCHA_SOLUTION in config.py and run again")
                return (False, None) if reading_book_title else False

            # Always get book titles first for debugging
            logger.info("Getting book titles...")
            book_titles = self.library_handler.get_book_titles()

            if not book_titles:
                logger.warning("No books found in library")
                return (False, None) if reading_book_title else True

            # If we're reading a specific book
            if reading_book_title:
                return self.reader_handler.handle_reading_flow(reading_book_title)

            return True

        except Exception as e:
            logger.error(f"Automation failed: {e}")
            import traceback

            traceback.print_exc()
            return (False, None) if reading_book_title else False
        finally:
            self.cleanup()


def main():
    parser = argparse.ArgumentParser(description="Kindle Automation Tool")
    parser.add_argument("--reinstall", action="store_true", help="Reinstall the Kindle app")
    args = parser.parse_args()

    try:
        # Try to import from config.py, fall back to template if not found
        try:
            import config

            AMAZON_EMAIL = config.AMAZON_EMAIL
            AMAZON_PASSWORD = config.AMAZON_PASSWORD
            CAPTCHA_SOLUTION = getattr(config, "CAPTCHA_SOLUTION", None)
            READING_BOOK_TITLE = getattr(config, "READING_BOOK_TITLE", None)
        except ImportError:
            logger.warning("No config.py found. Using default credentials from config.template.py")
            import config_template

            AMAZON_EMAIL = config_template.AMAZON_EMAIL
            AMAZON_PASSWORD = config_template.AMAZON_PASSWORD
            CAPTCHA_SOLUTION = getattr(config_template, "CAPTCHA_SOLUTION", None)
            READING_BOOK_TITLE = None

        # Initialize automator
        automator = KindleAutomator(AMAZON_EMAIL, AMAZON_PASSWORD, CAPTCHA_SOLUTION)

        # Handle reinstall command
        if args.reinstall:
            logger.info("Reinstalling Kindle app...")
            if automator.uninstall_kindle() and automator.install_kindle():
                logger.info("Kindle app reinstalled successfully")
                return 0
            return 1

        # Check credentials for normal operation
        if not AMAZON_EMAIL or not AMAZON_PASSWORD:
            logger.error("Email and password are required in config.py")
            return 1

        # Run the automation
        result = automator.run(READING_BOOK_TITLE)

        # Handle results
        if isinstance(result, tuple):
            success, page_number = result
            if success:
                logger.info(f"Successfully opened book. Current page: {page_number}")
                return 0
        else:
            if result:
                return 0

        return 1

    except Exception as e:
        logger.error(f"Automation failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
