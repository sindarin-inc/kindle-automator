import time
from views.states import AppState
from .logger import logger
from appium.webdriver.common.mobile_by import MobileBy as AppiumBy


class StateTransitions:
    def __init__(
        self, view_inspector, auth_handler, permissions_handler, library_handler
    ):
        logger.info("Initializing State Transitions...")
        self.view_inspector = view_inspector
        self.auth_handler = auth_handler
        self.permissions_handler = permissions_handler
        self.library_handler = library_handler

    def handle_unknown(self):
        """Handle unknown state by ensuring app is in foreground and rechecking"""
        logger.info("Handling UNKNOWN state - bringing app to foreground...")
        return self.view_inspector.ensure_app_foreground()

    def handle_notifications(self):
        """Handle notifications permission dialog"""
        logger.info("Handling NOTIFICATIONS state - accepting permission...")
        return self.permissions_handler.handle_notifications_permission()

    def handle_home(self):
        """Handle home screen by navigating to library"""
        logger.info("Handling HOME state - navigating to library...")
        return self.library_handler.navigate_to_library()

    def handle_sign_in(self):
        """Handle sign in screen"""
        logger.info("Handling SIGN_IN state - attempting authentication...")
        return self.auth_handler.sign_in()

    def handle_library_sign_in(self):
        """Handle sign in button on library tab"""
        logger.info("Handling LIBRARY_SIGN_IN state - clicking sign in button...")
        try:
            sign_in_button = self.view_inspector.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"
            )
            sign_in_button.click()
            logger.info("Successfully clicked sign in button")
            return True
        except Exception as e:
            logger.error(f"Failed to click sign in button: {e}")
            return False

    def handle_library(self):
        """Already in library, nothing to do"""
        logger.info("Handling LIBRARY state - already at destination")
        return True

    def handle_reading(self):
        """Handle reading view by navigating back to library"""
        logger.info("Handling READING state - navigating back to library...")
        return self.library_handler.navigate_to_library()

    def get_handler_for_state(self, state):
        """Get the appropriate handler for a given state"""
        handlers = {
            AppState.UNKNOWN: self.handle_unknown,
            AppState.NOTIFICATIONS: self.handle_notifications,
            AppState.HOME: self.handle_home,
            AppState.SIGN_IN: self.handle_sign_in,
            AppState.LIBRARY_SIGN_IN: self.handle_library_sign_in,
            AppState.LIBRARY: self.handle_library,
            AppState.READING: self.handle_reading,
        }
        handler = handlers.get(state)
        if handler:
            logger.info(f"Found handler for state {state}: {handler.__name__}")
        else:
            logger.error(f"No handler found for state {state}")
        return handler
