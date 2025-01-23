from appium.webdriver.common.appiumby import AppiumBy
import subprocess
import time
from .core.logger import logger
from .core.states import AppState as View
from .core.strategies import (
    SIGN_IN_BUTTON_STRATEGIES,
    get_tab_selection_strategies,
    NOTIFICATION_DIALOG_STRATEGIES,
    READING_VIEW_STRATEGIES,
    LIBRARY_ROOT_STRATEGIES,
)


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

        for strategy in get_tab_selection_strategies(tab_name):
            try:
                if len(strategy) == 3:  # Strategy with child element checks
                    by, value, child_checks = strategy
                    tab = self.driver.find_element(by, value)
                    # Check all child elements have expected attributes
                    all_checks_passed = True
                    for child_name, (
                        child_by,
                        child_value,
                        attr,
                        expected,
                    ) in child_checks.items():
                        try:
                            child = tab.find_element(child_by, child_value)
                            if child.get_attribute(attr) != expected:
                                all_checks_passed = False
                                break
                        except:
                            all_checks_passed = False
                            break
                    if all_checks_passed:
                        logger.info(
                            f"Found {tab_name} tab with selected icon and label"
                        )
                        return True
                else:  # Simple strategy
                    by, value = strategy
                    self.driver.find_element(by, value)
                    logger.info(f"Found {tab_name} tab with 'selected' in content-desc")
                    return True
            except:
                continue

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

    def _try_find_element(self, strategies, success_message=None):
        """Try to find an element using multiple strategies"""
        for strategy in strategies:
            try:
                element = self.driver.find_element(strategy[0], strategy[1])
                if success_message:
                    logger.info(success_message)
                return element
            except:
                continue
        return None

    def get_current_view(self):
        """Determine the current view in the Kindle app."""
        logger.info("Starting view detection...")

        # Check for notification permission dialog
        logger.info("Checking for notification permission dialog...")
        if self._try_find_element(
            NOTIFICATION_DIALOG_STRATEGIES, "Found notification permission dialog"
        ):
            return View.NOTIFICATION_PERMISSION

        # Check tab selection first
        logger.info("Checking tab selection...")
        if self._is_tab_selected("LIBRARY"):
            logger.info("Library tab is selected, checking for sign in button...")
            # Dump page source before checking for sign in button
            self._dump_page_source()

            # Try each sign in button strategy and log the attempts
            for strategy, locator in SIGN_IN_BUTTON_STRATEGIES:
                try:
                    logger.info(
                        f"Trying to find sign in button with strategy: {strategy}, locator: {locator}"
                    )
                    element = self.driver.find_element(strategy, locator)
                    logger.info("Found sign in button on Library tab")
                    return View.LIBRARY_SIGN_IN
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
                    continue

            logger.info("No sign in button found, assuming library view")
            return View.LIBRARY
        elif self._is_tab_selected("HOME"):
            logger.info("Found home view (HOME tab selected)")
            return View.HOME

        # Check for sign in view (when not on Library tab)
        logger.info("Checking for sign in view...")
        if self._try_find_element(SIGN_IN_BUTTON_STRATEGIES, "Found sign in view"):
            return View.SIGN_IN

        # Check for reading view
        logger.info("Checking for reading view...")
        if self._try_find_element(READING_VIEW_STRATEGIES, "Found reading view"):
            return View.READING

        # Check for general app indicators
        logger.info("Checking for general app indicators...")
        if self._try_find_element(
            LIBRARY_ROOT_STRATEGIES,
            "Found library root view - in app but can't determine exact view",
        ):
            return View.UNKNOWN

        logger.debug("Not in main app view")
        return View.UNKNOWN
