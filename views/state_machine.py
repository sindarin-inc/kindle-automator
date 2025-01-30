import logging
import os
import time

from handlers.auth_handler import AuthenticationHandler
from handlers.library_handler import LibraryHandler
from handlers.permissions_handler import PermissionsHandler
from handlers.reader_handler import ReaderHandler
from views.core.app_state import AppState, AppView
from server.logging_config import store_page_source
from views.transitions import StateTransitions
from views.view_inspector import ViewInspector
from views.library.view_strategies import LIBRARY_ELEMENT_DETECTION_STRATEGIES

logger = logging.getLogger(__name__)


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
            bool: True if library state was reached or CAPTCHA needs solving, False otherwise.
        """
        transitions = 0
        while transitions < max_transitions:
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

            if self.current_state == AppState.LIBRARY:
                logger.info("Successfully reached library state")
                # Switch to list view if needed
                if not self.library_handler.switch_to_list_view():
                    logger.warning("Failed to switch to list view, but we're still in library")
                return True

            # Special handling for CAPTCHA state
            if self.current_state == AppState.CAPTCHA:
                # Return True to indicate we're in a valid state that needs client interaction
                logger.info("Reached CAPTCHA state - waiting for client interaction")
                return True

            # If we're in UNKNOWN state, try to bring app to foreground
            if self.current_state == AppState.UNKNOWN:
                logger.info("In UNKNOWN state - bringing app to foreground...")
                if not self.view_inspector.ensure_app_foreground():
                    logger.error("Failed to bring app to foreground")
                    return False
                time.sleep(1)  # Wait for app to come to foreground
                # Try to get the current state again
                self.current_state = self._get_current_state()
                logger.info(f"After bringing app to foreground, state is: {self.current_state}")
                if self.current_state == AppState.LIBRARY:
                    logger.info("Successfully reached library state after bringing app to foreground")
                    return True

                # If still unknown, try checking for library-specific elements
                if self.current_state == AppState.UNKNOWN:
                    logger.info("Still in UNKNOWN state, checking for library-specific elements...")
                    # Use library handler's existing view detection logic
                    if self.library_handler._is_library_tab_selected():
                        logger.info("Library handler detected library view")
                        return True

                continue

            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                logger.error(f"No handler found for state {self.current_state}")
                return False

            # Special handling for CAPTCHA during sign-in
            result = handler()
            if not result and self.current_state == AppState.SIGN_IN:
                # Check if we're actually in CAPTCHA state now
                new_state = self._get_current_state()
                if new_state == AppState.CAPTCHA:
                    logger.info("Sign-in resulted in CAPTCHA state - waiting for client interaction")
                    self.current_state = new_state
                    return True

            if not result:
                logger.error(f"Handler failed for state {self.current_state}")
                return False

            transitions += 1

        logger.error(f"Failed to reach library state after {max_transitions} transitions")
        logger.error(f"Final state: {self.current_state}")

        # Log the page source for debugging and store it
        try:
            source = self.view_inspector.driver.page_source

            # Store the page source
            filepath = store_page_source(source, "failed_transition")
            logger.info(f"Stored failed transition page source at: {filepath}")

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
            # Store page source
            source = self.view_inspector.driver.page_source
            filepath = store_page_source(source, f"failed_transition_{from_state}_to_{to_state}")
            logger.info(f"Stored failed transition page source at: {filepath}")

            # Save screenshot
            screenshot_path = os.path.join(self.screenshots_dir, "failed_transition.png")
            self.view_inspector.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved failed transition screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save transition error data: {e}")
