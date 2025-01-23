from views.core.logger import logger
from views.core.app_state import AppState
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS
from selenium.webdriver.support.ui import WebDriverWait


class StateTransitions:
    """Handles transitions between different app states."""

    def __init__(self, view_inspector, auth_handler, permissions_handler, library_handler):
        """Initialize with required handlers."""
        logger.info("Initializing State Transitions...")
        self.view_inspector = view_inspector
        self.auth_handler = auth_handler
        self.permissions_handler = permissions_handler
        self.library_handler = library_handler

    def handle_unknown(self):
        """Handle UNKNOWN state by ensuring app is in foreground."""
        logger.info("Handling UNKNOWN state - bringing app to foreground...")
        return self.view_inspector.ensure_app_foreground()

    def handle_notifications(self):
        """Handle NOTIFICATIONS state by accepting permissions."""
        logger.info("Handling NOTIFICATIONS state - accepting permission...")
        return self.permissions_handler.handle_notifications_permission()

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
        """Handle LIBRARY_SIGN_IN state by clicking sign in button."""
        logger.info("Handling LIBRARY_SIGN_IN state - clicking sign in button...")

        # Try each strategy to find and click the sign in button
        for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
            try:
                sign_in_button = self.view_inspector.driver.find_element(strategy, locator)
                logger.info(f"Found sign in button using strategy: {strategy}")
                sign_in_button.click()
                logger.info("Successfully clicked sign in button")

                # Wait for sign in view to appear
                logger.info("Waiting for sign in view to appear...")
                WebDriverWait(self.view_inspector.driver, 10).until(
                    lambda x: any(
                        x.find_elements(strategy[0], strategy[1]) for strategy in EMAIL_VIEW_IDENTIFIERS
                    )
                )
                logger.info("Sign in view appeared")
                return True
            except Exception as e:
                logger.debug(f"Strategy {strategy} failed: {e}")
                continue

        logger.error("Failed to find or click sign in button with any strategy")
        return False

    def handle_library(self):
        """Handle LIBRARY state - already in library."""
        logger.info("Handling LIBRARY state - already at destination")
        return True

    def handle_reading(self):
        """Handle READING state by navigating back to library."""
        logger.info("Handling READING state - navigating back to library...")
        return self.library_handler.navigate_to_library()

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
        }
        handler = handlers.get(state)
        if handler:
            logger.info(f"Found handler for state {state}: {handler.__name__}")
        else:
            logger.error(f"No handler found for state {state}")
        return handler
