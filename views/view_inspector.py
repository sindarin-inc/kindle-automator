from appium.webdriver.common.appiumby import AppiumBy
import subprocess
import time
from .logger import logger
from .states import AppState as View  # Import AppState as View for compatibility


class ViewInspector:
    def __init__(self):
        self.app_package = "com.amazon.kindle"
        self.app_activity = "com.amazon.kindle.UpgradePage"
        self.driver = None

    def set_driver(self, driver):
        """Sets the Appium driver instance"""
        self.driver = driver

    def ensure_app_foreground(self):
        """Ensures the Kindle app is in the foreground"""
        try:
            logger.info(f"Bringing {self.app_package} to foreground...")
            subprocess.run(
                ["adb", "shell", f"am start -n {self.app_package}/{self.app_activity}"],
                check=True,
                capture_output=True,
                text=True,
            )
            time.sleep(0.5)  # Reduced from 2s to 0.5s
            logger.info("App brought to foreground")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error bringing app to foreground: {e}")
            return False

    def _is_tab_selected(self, tab_name):
        """Check if a specific tab is currently selected using multiple strategies."""
        logger.info(f"Checking if {tab_name} tab is selected...")

        # Strategy 1: Check content-desc attribute
        try:
            tab = self.driver.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().descriptionContains("{tab_name}, Tab selected")',
            )
            logger.info(f"Found {tab_name} tab with 'selected' in content-desc")
            return True
        except:
            logger.debug(
                f"Strategy 1 failed: No tab found with content-desc containing '{tab_name}, Tab selected'"
            )

        # Strategy 2: Check if the tab's icon and label are selected
        try:
            tab = self.driver.find_element(
                AppiumBy.ID, f"com.amazon.kindle:id/{tab_name.lower()}_tab"
            )
            icon = tab.find_element(AppiumBy.ID, "com.amazon.kindle:id/icon")
            label = tab.find_element(AppiumBy.ID, "com.amazon.kindle:id/label")
            if (
                icon.get_attribute("selected") == "true"
                and label.get_attribute("selected") == "true"
            ):
                logger.info(f"Found {tab_name} tab with selected icon and label")
                return True
        except:
            logger.debug(
                f"Strategy 2 failed: Could not verify icon and label selection state for {tab_name} tab"
            )

        logger.info(f"{tab_name} tab is not selected")
        return False

    def _dump_page_source(self):
        """Dump the page source for debugging"""
        try:
            logger.debug("\n=== Page Source ===")
            source = self.driver.page_source
            logger.debug(source)
            logger.debug("=== End Page Source ===\n")
        except Exception as e:
            logger.error(f"Failed to get page source: {e}")

    def get_current_view(self):
        """Determine the current view in the Kindle app."""
        logger.info("Starting view detection...")

        # Check for notification permission dialog
        logger.info("Checking for notification permission dialog...")
        try:
            self.driver.find_element(
                AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"
            )
            logger.info("Found notification permission dialog")
            return View.NOTIFICATION_PERMISSION
        except Exception as e:
            logger.debug(f"No notification dialog found: {str(e)}")

        # Check tab selection first
        logger.info("Checking tab selection...")
        if self._is_tab_selected("LIBRARY"):
            logger.info("Library tab is selected, checking for sign in button...")
            try:
                sign_in_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"
                )
                logger.info("Found sign in button while on Library tab")
                return View.LIBRARY_SIGN_IN
            except Exception as e:
                logger.debug("No sign in button found on Library tab")
                logger.info("Found library view (LIBRARY tab selected)")
                return View.LIBRARY
        elif self._is_tab_selected("HOME"):
            logger.info("Found home view (HOME tab selected)")
            return View.HOME

        # Check for sign in view (when not on Library tab)
        logger.info("Checking for sign in view...")
        try:
            self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/sign_in_button")
            logger.info("Found sign in view")
            return View.SIGN_IN
        except Exception as e:
            logger.debug(f"No sign in view found: {str(e)}")

        # Check for reading view
        logger.info("Checking for reading view...")
        try:
            self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"
            )
            logger.info("Found reading view")
            return View.READING
        except Exception as e:
            logger.debug(f"No reading view found: {str(e)}")

        # Check for general app indicators
        logger.info("Checking for general app indicators...")
        try:
            self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
            )
            logger.info(
                "Found library root view - in app but can't determine exact view"
            )
            return View.UNKNOWN
        except:
            logger.debug("Not in main app view")
            return View.UNKNOWN
