from views.core.logger import logger
from views.core.app_state import AppState, AppView
from views.view_inspector import ViewInspector
from handlers.auth_handler import AuthenticationHandler
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from handlers.permissions_handler import PermissionsHandler
from views.transitions import StateTransitions
import os


class KindleStateMachine:
    """State machine for managing Kindle app states and transitions."""

    def __init__(self, driver, email=None, password=None, captcha_solution=None):
        """Initialize the state machine with required handlers."""
        self.driver = driver
        self.view_inspector = ViewInspector(driver)
        self.auth_handler = AuthenticationHandler(driver, email, password, captcha_solution)
        self.library_handler = LibraryHandler(driver)
        self.reader_handler = ReaderHandler(driver)
        self.permissions_handler = PermissionsHandler(driver)
        self.transitions = StateTransitions(
            self.view_inspector,
            self.auth_handler,
            self.permissions_handler,
            self.library_handler,
            self.reader_handler,
        )
        self.transitions.set_driver(driver)
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.current_state = AppState.UNKNOWN

    def _get_current_state(self):
        """Get the current app state using the view inspector."""
        view = self.view_inspector.get_current_view()
        logger.info(f"View {view} maps to state {AppState[view.name]}")
        return AppState[view.name]

    def transition_to_library(self, max_transitions=5):
        """Attempt to transition to the library state.

        Args:
            max_transitions (int): Maximum number of transitions to attempt before giving up.
                                 This prevents infinite loops.

        Returns:
            bool: True if library state was reached, False otherwise.
        """
        transitions = 0
        while transitions < max_transitions:
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

            if self.current_state == AppState.LIBRARY:
                logger.info("Successfully reached library state")
                return True

            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                logger.error(f"No handler found for state {self.current_state}")
                return False

            if not handler():
                logger.error(f"Handler failed for state {self.current_state}")
                return False

            transitions += 1

        logger.error(f"Failed to reach library state after {max_transitions} transitions")
        logger.error(f"Final state: {self.current_state}")

        # Log the page source for debugging
        try:
            logger.info("\n=== PAGE SOURCE AFTER FAILED TRANSITIONS START ===")
            logger.info(self.view_inspector.driver.page_source)
            logger.info("=== PAGE SOURCE AFTER FAILED TRANSITIONS END ===\n")

            # Also save a screenshot for visual debugging
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "failed_transition.png")
                self.view_inspector.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved failed transition screenshot to {screenshot_path}")
            except Exception as e:
                logger.error(f"Failed to save transition error screenshot: {e}")
        except Exception as e:
            logger.error(f"Failed to get page source after failed transitions: {e}")

        return False

    def _handle_failed_transition(self, from_state, to_state, error):
        """Handle a failed state transition by logging details and saving screenshot"""
        logger.error(f"Failed to transition from {from_state} to {to_state}: {error}")
        try:
            screenshot_path = os.path.join(self.screenshots_dir, "failed_transition.png")
            self.view_inspector.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved failed transition screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save transition error screenshot: {e}")
