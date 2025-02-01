import logging
import os
import subprocess
import time
import traceback

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from server.logging_config import store_page_source
from views.auth.interaction_strategies import (
    EMAIL_FIELD_STRATEGIES,
    PASSWORD_FIELD_STRATEGIES,
    SIGN_IN_RADIO_BUTTON_STRATEGIES,
)
from views.auth.view_strategies import (
    AUTH_RESTART_MESSAGES,
    CAPTCHA_REQUIRED_INDICATORS,
    EMAIL_VIEW_IDENTIFIERS,
    PASSWORD_VIEW_IDENTIFIERS,
)
from views.core.app_state import AppState, AppView
from views.core.tab_strategies import get_tab_selection_strategies
from views.home.view_strategies import HOME_TAB_IDENTIFIERS, HOME_VIEW_IDENTIFIERS
from views.library.view_strategies import (
    EMPTY_LIBRARY_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_STRATEGIES,
    LIBRARY_VIEW_IDENTIFIERS,
)
from views.notifications.view_strategies import NOTIFICATION_DIALOG_IDENTIFIERS
from views.reading.view_strategies import (
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
)
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES

logger = logging.getLogger(__name__)


class ViewInspector:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.app_package = "com.amazon.kindle"
        self.app_activity = "com.amazon.kindle.UpgradePage"

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
        """Check if a specific tab is currently selected."""
        logger.info(f"   Checking if {tab_name} tab is selected...")

        for strategy in get_tab_selection_strategies(tab_name):
            try:
                by, value = strategy
                element = self.driver.find_element(by, value)
                if element.is_displayed():
                    logger.info(f"   Found {tab_name} tab with strategy: {by}, value: {value}")
                    return True
            except NoSuchElementException:
                continue

        return False

    def _dump_page_source(self):
        """Dump the page source for debugging"""
        try:
            source = self.driver.page_source

            # Store the page source
            filepath = store_page_source(source, "unknown_view")
            logger.info(f"Stored unknown view page source at: {filepath}")
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
        """Determine the current view based on visible elements."""
        try:
            # Check for auth errors that require restart
            for strategy, locator in AUTH_RESTART_MESSAGES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element:
                        text = element.get_attribute("text")
                        logger.info(f"Found auth error text: '{text}'")
                        logger.info("Found auth error requiring restart - storing page source")
                        source = self.driver.page_source
                        store_page_source(source, "auth_timeout")

                        # Restart the app
                        logger.info("Restarting app due to auth verification error")
                        self.driver.terminate_app(self.app_package)
                        time.sleep(1)
                        self.driver.activate_app(self.app_package)
                        time.sleep(2)

                        return AppView.UNKNOWN
                except NoSuchElementException:
                    logger.debug("No auth error text found - continuing")
                    continue

            logger.info("Determining current view...")

            # Check for reading view or full screen dialog
            for strategy, locator in READING_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info("   Found reading view element")
                    return AppView.READING
                except NoSuchElementException:
                    continue

            # Also check for full screen dialog which indicates reading view
            for strategy, locator in READING_VIEW_FULL_SCREEN_DIALOG:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info("   Found reading view full screen dialog")
                    return AppView.READING
                except NoSuchElementException:
                    continue

            # Check for auth-related views first
            if self._is_auth_view():
                # Store auth page source for debugging
                logger.info("   Found auth view - storing page source for debugging")
                source = self.driver.page_source
                store_page_source(source, "auth_view")
                return AppView.SIGN_IN

            # Check for notification permission dialog first
            if self._try_find_element(
                NOTIFICATION_DIALOG_IDENTIFIERS, "   Found notification permission dialog"
            ):
                logger.info("   Found notification permission dialog")
                return AppView.NOTIFICATION_PERMISSION

            # Check for captcha screen
            indicators_found = 0
            for strategy, locator in CAPTCHA_REQUIRED_INDICATORS:
                try:
                    self.driver.find_element(strategy, locator)
                    indicators_found += 1
                except:
                    continue
            if indicators_found >= 3:
                logger.info("   Found captcha screen")
                return AppView.CAPTCHA

            # Check for empty library with sign-in button first
            logger.info("   Checking for empty library with sign-in button...")
            if self._try_find_element(
                EMPTY_LIBRARY_IDENTIFIERS, "   Found empty library with sign-in button"
            ):
                logger.info("   Found empty library with sign-in button")
                return AppView.LIBRARY_SIGN_IN

            # Check for library view indicators
            logger.info("   Checking for library view indicators...")
            has_library_root = False
            has_library_tab = False

            if self._is_tab_selected("LIBRARY"):
                logger.info("Detected LIBRARY view")
                return AppView.LIBRARY

            # Check for view options menu (part of library view)
            if self._is_view_options_menu_open():
                logger.info("   Found view options menu - this is part of library view")
                return AppView.LIBRARY

            # Check tab selection for HOME view
            logger.info("   Checking tab selection...")
            if self._is_tab_selected("HOME"):
                logger.info("HOME tab is selected")
                return AppView.HOME

            # Check for password view
            logger.info("   Checking for password view...")
            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"   Found password view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN_PASSWORD
                except NoSuchElementException:
                    continue

            # Check for sign in view
            logger.info("   Checking for sign in view...")
            for strategy, locator in EMAIL_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"   Found sign in view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN
                except NoSuchElementException:
                    continue

            # Check for general app indicators
            logger.info("   Checking for general app indicators...")
            if self._try_find_element(
                LIBRARY_VIEW_IDENTIFIERS,
                "   Found library root view - in app but can't determine exact view",
            ):
                return AppView.UNKNOWN

            # If we get here, we couldn't determine the view
            logger.warning("Could not determine current view - dumping page source for debugging")
            self._dump_page_source()

            # Also save a screenshot for visual debugging
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "unknown_view.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot of unknown view to {screenshot_path}")
            except Exception as e:
                logger.error(f"Failed to save screenshot: {e}")

            logger.debug("Not in main app view")
            return AppView.UNKNOWN

        except Exception as e:
            logger.error(f"Error determining current view: {e}")
            logger.warning("Dumping page source due to error")
            traceback.print_exc()
            self._dump_page_source()
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "error_view.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot of error state to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save error screenshot: {screenshot_error}")
            return AppView.UNKNOWN

    def _is_auth_view(self):
        """Check if we're on any authentication-related view."""
        try:
            # Check for email input field
            for strategy in EMAIL_FIELD_STRATEGIES:
                try:
                    if self.driver.find_element(*strategy):
                        logger.info("   Found email input field - on auth view")
                        return True
                except NoSuchElementException:
                    continue

            # Check for password input field
            for strategy in PASSWORD_FIELD_STRATEGIES:
                try:
                    if self.driver.find_element(*strategy):
                        logger.info("   Found password input field - on auth view")
                        return True
                except NoSuchElementException:
                    continue

            # Check for sign-in button
            for strategy in SIGN_IN_RADIO_BUTTON_STRATEGIES:
                try:
                    if self.driver.find_element(*strategy):
                        logger.info("   Found sign-in radio button - on auth view")
                        return True
                except NoSuchElementException:
                    continue

            return False

        except Exception as e:
            logger.error(f"Error checking for auth view: {e}")
            return False
