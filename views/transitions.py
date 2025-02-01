import logging
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from views.auth.interaction_strategies import (
    CAPTCHA_CONTINUE_BUTTON,
    CAPTCHA_INPUT_FIELD,
    LIBRARY_SIGN_IN_STRATEGIES,
)
from views.auth.view_strategies import CAPTCHA_ERROR_MESSAGES, EMAIL_VIEW_IDENTIFIERS
from views.core.app_state import AppState, AppView

logger = logging.getLogger(__name__)


class StateTransitions:
    """Handles transitions between different app states."""

    def __init__(self, view_inspector, auth_handler, permissions_handler, library_handler, reader_handler):
        """Initialize with required handlers."""
        logger.info("Initializing State Transitions...")
        self.view_inspector = view_inspector
        self.auth_handler = auth_handler
        self.permissions_handler = permissions_handler
        self.library_handler = library_handler
        self.reader_handler = reader_handler
        self.driver = None
        self.used_captcha_solutions = set()  # Track used solutions

    def set_driver(self, driver):
        """Sets the Appium driver instance"""
        self.driver = driver

    def handle_unknown(self):
        """Handle UNKNOWN state by ensuring app is in foreground."""
        logger.info("Handling UNKNOWN state - bringing app to foreground...")
        return self.view_inspector.ensure_app_foreground()

    def handle_notifications(self):
        """Handle NOTIFICATIONS state by accepting permissions."""
        logger.info("Handling NOTIFICATIONS state - accepting permission...")
        result = self.permissions_handler.handle_notifications_permission()

        # Even if permission handling fails, we want to continue the flow
        # The dialog may have auto-dismissed, which is fine
        if not result:
            logger.info("Permission dialog may have auto-dismissed - continuing flow")

        return True

    def handle_home(self):
        """Handle HOME state by navigating to library."""
        logger.info("Handling HOME state - navigating to library...")
        return self.library_handler.navigate_to_library()

    def handle_sign_in(self):
        """Handle SIGN_IN state by attempting authentication."""
        logger.info("Handling SIGN_IN state - attempting authentication...")
        return self.auth_handler.sign_in()

    def handle_sign_in_password(self):
        """Handle SIGN_IN_PASSWORD state by entering password."""
        logger.info("Handling SIGN_IN_PASSWORD state - entering password...")
        return self.auth_handler.sign_in()

    def handle_library_sign_in(self):
        """Handle the library sign in state by clicking the sign in button."""
        logger.info("Handling LIBRARY_SIGN_IN state...")
        return self.library_handler.handle_library_sign_in()

    def handle_library(self):
        """Handle LIBRARY state - already in library."""
        logger.info("Handling LIBRARY state - already at destination")
        return True

    def handle_reading(self):
        """Handle READING state by navigating back to library."""
        logger.info("Handling READING state - navigating back to library...")
        return self.reader_handler.navigate_back_to_library()

    def handle_captcha(self):
        """Handle CAPTCHA state by attempting to solve captcha."""
        logger.info("Handling CAPTCHA state...")
        return self.auth_handler.sign_in()

    def get_handler_for_state(self, state):
        """Get the appropriate handler method for a given state.

        Args:
            state (AppState): The current app state.

        Returns:
            function: Handler method for the state, or None if no handler exists.
        """
        handlers = {
            AppState.UNKNOWN: self.handle_unknown,
            AppState.NOTIFICATION_PERMISSION: self.handle_notifications,
            AppState.HOME: self.handle_home,
            AppState.SIGN_IN: self.handle_sign_in,
            AppState.SIGN_IN_PASSWORD: self.handle_sign_in_password,
            AppState.LIBRARY_SIGN_IN: self.handle_library_sign_in,
            AppState.LIBRARY: self.handle_library,
            AppState.READING: self.handle_reading,
            AppState.CAPTCHA: self._handle_captcha,  # Add new CAPTCHA handler
        }

        handler = handlers.get(state)
        if handler:
            logger.info(f"Found handler for state {state}: {handler.__name__}")
        else:
            logger.error(f"No handler found for state {state}")
        return handler

    def _handle_captcha(self):
        """Handle CAPTCHA state by entering solution if available."""
        try:
            # If we have a captcha solution, enter it
            if self.auth_handler.captcha_solution:
                # Check if we've already tried this solution
                if self.auth_handler.captcha_solution in self.used_captcha_solutions:
                    logger.info("CAPTCHA solution already attempted - needs new solution")
                    return False

                logger.info("Entering CAPTCHA solution...")

                # Find and enter the CAPTCHA solution
                captcha_input = self.driver.find_element(*CAPTCHA_INPUT_FIELD)
                captcha_input.clear()
                captcha_input.send_keys(self.auth_handler.captcha_solution)

                # Find and click submit button
                submit_button = self.driver.find_element(*CAPTCHA_CONTINUE_BUTTON)
                submit_button.click()

                # Mark this solution as used
                self.used_captcha_solutions.add(self.auth_handler.captcha_solution)

                # Wait briefly for transition
                time.sleep(2)
                return True

            # No solution available, need client interaction
            logger.info("No CAPTCHA solution available")
            return False

        except Exception as e:
            logger.error(f"Error handling CAPTCHA: {e}")
            return False
