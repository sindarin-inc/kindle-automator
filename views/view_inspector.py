import subprocess
import time
from appium.webdriver.common.appiumby import AppiumBy
from views.core.logger import logger
from views.core.app_state import AppState, AppView
from views.library.view_strategies import LIBRARY_VIEW_IDENTIFIERS
from views.home.view_strategies import HOME_VIEW_IDENTIFIERS, HOME_TAB_IDENTIFIERS
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES
from views.notifications.view_strategies import NOTIFICATION_DIALOG_IDENTIFIERS
from views.auth.view_strategies import (
    EMAIL_VIEW_IDENTIFIERS,
    PASSWORD_VIEW_IDENTIFIERS,
)
from views.reading.view_strategies import READING_VIEW_IDENTIFIERS
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES


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

    def _get_tab_selection_strategies(self, tab_name):
        """Generate strategies for detecting tab selection state.

        Args:
            tab_name (str): Name of the tab to check (e.g. 'LIBRARY', 'HOME')

        Returns:
            list: List of tuples containing strategies to detect if the tab is selected
        """
        return [
            (
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().descriptionContains("{tab_name}, Tab selected")',
            ),
            (
                AppiumBy.ID,
                f"com.amazon.kindle:id/{tab_name.lower()}_tab",
                {
                    "icon": (
                        AppiumBy.ID,
                        "com.amazon.kindle:id/icon",
                        "selected",
                        "true",
                    ),
                    "label": (
                        AppiumBy.ID,
                        "com.amazon.kindle:id/label",
                        "selected",
                        "true",
                    ),
                },
            ),
        ]

    def _is_tab_selected(self, tab_name):
        """Check if a specific tab is currently selected."""
        logger.info(f"Checking if {tab_name} tab is selected...")

        for strategy in self._get_tab_selection_strategies(tab_name):
            try:
                if len(strategy) == 3:  # Complex strategy with child elements
                    by, value, child_checks = strategy
                    tab = self.driver.find_element(by, value)

                    # Check child elements
                    for child_by, child_value, attr, expected in child_checks.values():
                        child = tab.find_element(child_by, child_value)
                        if child.get_attribute(attr) == expected:
                            logger.info(f"Found {tab_name} tab with '{attr}' in {child_by}")
                            return True
                else:  # Simple strategy
                    by, value = strategy
                    self.driver.find_element(by, value)
                    logger.info(f"Found {tab_name} tab with strategy: {by}")
                    return True
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue

        logger.info(f"{tab_name} tab is not selected")
        return False

    def _dump_page_source(self):
        """Dump the page source for debugging"""
        try:
            logger.info("\n=== PAGE SOURCE START ===")
            source = self.driver.page_source
            logger.info(source)
            logger.info("=== PAGE SOURCE END ===\n")
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

    def _is_view_options_menu_open(self):
        """Check if the view options menu is currently open."""
        try:
            for strategy, locator in VIEW_OPTIONS_MENU_STATE_STRATEGIES:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"View options menu detected via {strategy}: {locator}")
                    return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Error checking view options menu state: {e}")
            return False

    def get_current_view(self):
        """Get the current view in the Kindle app."""
        try:
            # Check for notification permission dialog first
            if self._try_find_element(
                NOTIFICATION_DIALOG_IDENTIFIERS, "Found notification permission dialog"
            ):
                logger.info("Found notification permission dialog")
                return AppView.NOTIFICATION_PERMISSION

            # Check for library view indicators
            logger.info("Checking for library view indicators...")
            if self._is_view_options_menu_open():
                logger.info("Found view options menu - this is part of library view")
                return AppView.LIBRARY

            # Check tab selection
            logger.info("Checking tab selection...")
            if self._is_tab_selected("LIBRARY"):
                logger.info("LIBRARY tab is selected")
                return AppView.LIBRARY
            elif self._is_tab_selected("HOME"):
                logger.info("HOME tab is selected")
                return AppView.HOME

            # Check for password view
            logger.info("Checking for password view...")
            self._dump_page_source()
            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS:
                try:
                    logger.info(f"Trying to find password view with strategy: {strategy}, locator: {locator}")
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"Found password view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN_PASSWORD
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
                    continue

            # Check for sign in view
            logger.info("Checking for sign in view...")
            for strategy, locator in EMAIL_VIEW_IDENTIFIERS:
                try:
                    logger.info(f"Trying to find sign in view with strategy: {strategy}, locator: {locator}")
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"Found sign in view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
                    continue

            # Check for reading view
            logger.info("Checking for reading view...")
            if self._try_find_element(READING_VIEW_IDENTIFIERS, "Found reading view"):
                return AppView.READING

            # Check for general app indicators
            logger.info("Checking for general app indicators...")
            if self._try_find_element(
                LIBRARY_VIEW_IDENTIFIERS,
                "Found library root view - in app but can't determine exact view",
            ):
                return AppView.UNKNOWN

            logger.debug("Not in main app view")
            return AppView.UNKNOWN

        except Exception as e:
            logger.error(f"Error getting current view: {e}")
            return AppView.UNKNOWN
