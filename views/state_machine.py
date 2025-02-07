import logging
import os
import time

from handlers.auth_handler import AuthenticationHandler
from handlers.library_handler import LibraryHandler
from handlers.permissions_handler import PermissionsHandler
from handlers.reader_handler import ReaderHandler
from server.logging_config import store_page_source
from views.core.app_state import AppState, AppView
from views.library.view_strategies import LIBRARY_ELEMENT_DETECTION_STRATEGIES
from views.transitions import StateTransitions
from views.view_inspector import ViewInspector

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
        """Attempt to transition to the library state."""
        transitions = 0
        unknown_retries = 0
        MAX_UNKNOWN_RETRIES = 3  # Maximum times to try recovering from UNKNOWN state

        while transitions < max_transitions:
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

            if self.current_state == AppState.LIBRARY:
                logger.info("Successfully reached library state")
                # Switch to list view if needed
                if not self.library_handler.switch_to_list_view():
                    logger.warning("Failed to switch to list view, but we're still in library")
                return True

            # If we're in UNKNOWN state, try to bring app to foreground
            if self.current_state == AppState.UNKNOWN:
                unknown_retries += 1
                if unknown_retries > MAX_UNKNOWN_RETRIES:
                    logger.error(
                        f"Failed to recover from UNKNOWN state after {MAX_UNKNOWN_RETRIES} attempts. "
                        "Please check screenshots/unknown_view.png and fixtures/dumps/unknown_view.xml "
                        "to determine why the view cannot be recognized."
                    )
                    return False

                logger.info(
                    f"In UNKNOWN state (attempt {unknown_retries}/{MAX_UNKNOWN_RETRIES}) - bringing app to foreground..."
                )
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

            # Handle current state
            result = handler()

            # Special handling for CAPTCHA state
            if self.current_state == AppState.CAPTCHA:
                logger.info(
                    "In CAPTCHA state with solution: %s",
                    self.auth_handler.captcha_solution,
                )
                if not result:
                    # If handler returns False, we need client interaction
                    logger.info("CAPTCHA handler needs client interaction")
                    return True
                # If handler succeeds, continue with transitions
                continue
            # Check if sign-in resulted in CAPTCHA
            elif not result and self.current_state == AppState.SIGN_IN:
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

    def update_current_state(self) -> AppState:
        """Update and return the current state of the app.

        Returns:
            AppState: The current state of the app
        """
        try:
            # Get current state from view inspector
            self.current_state = self._get_current_state()
            logger.info(f"Updated current state to: {self.current_state}")

            # If unknown, try to detect specific states
            if self.current_state == AppState.UNKNOWN:
                # Store page source for debugging
                source = self.driver.page_source
                filepath = store_page_source(source, "unknown_state")
                logger.info(f"Stored unknown state page source at: {filepath}")

                # Try to detect library state specifically
                if self.library_handler._is_library_tab_selected():
                    self.current_state = AppState.LIBRARY
                    logger.info("Detected LIBRARY state from library handler")
                # Add other specific state checks here as needed
                # e.g. check for reading view elements to detect READING state

            return self.current_state

        except Exception as e:
            logger.error(f"Error updating current state: {e}")
            self.current_state = AppState.UNKNOWN
            return self.current_state
