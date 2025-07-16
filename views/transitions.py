import logging
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from handlers.auth_handler import LoginVerificationState
from server.logging_config import store_page_source
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS
from views.common.dialog_strategies import APP_NOT_RESPONDING_CLOSE_APP_BUTTON
from views.core.app_state import AppState, AppView
from views.library.view_strategies import LIBRARY_VIEW_DETECTION_STRATEGIES

logger = logging.getLogger(__name__)


class StateTransitions:
    """Handles transitions between different app states."""

    def __init__(self, view_inspector, auth_handler, permissions_handler, library_handler, reader_handler):
        """Initialize with required handlers."""
        # logger.info("Initializing State Transitions...")
        self.view_inspector = view_inspector
        self.auth_handler = auth_handler
        self.permissions_handler = permissions_handler
        self.library_handler = library_handler
        self.reader_handler = reader_handler
        self.driver = None

    def set_driver(self, driver):
        """Sets the Appium driver instance"""
        self.driver = driver

    def handle_unknown(self):
        """Handle UNKNOWN state by ensuring app is in foreground."""
        logger.info("Handling UNKNOWN state - bringing app to foreground...")
        return self.view_inspector.ensure_app_foreground()

    def handle_notifications(self):
        """Handle NOTIFICATIONS state by accepting or denying permissions as appropriate."""
        # Check if this is a Magisk notification dialog
        try:
            notification_text = self.driver.find_element(
                AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"
            ).text
            if "Magisk" in notification_text:
                logger.info("Handling Magisk notification dialog - denying permission...")
                result = self.permissions_handler.handle_notifications_permission(should_allow=False)
            else:
                # For Kindle or other app permissions, we usually want to allow
                logger.info("Handling notification permission dialog - accepting permission...")
                result = self.permissions_handler.handle_notifications_permission(should_allow=True)
        except Exception as e:
            # If we can't determine the app, default to accepting the permission
            logger.info(f"Could not determine notification app, defaulting to accept: {e}")
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
        result = self.auth_handler.sign_in()

        # Check if result is a tuple with LoginVerificationState.ERROR
        if isinstance(result, tuple) and len(result) == 2:
            state, message = result
            if state == LoginVerificationState.ERROR:
                if "No credentials provided" in message:
                    logger.warning("Authentication requires credentials that haven't been set")
                    # Return False to stop the state transition loop
                    # This prevents infinite retries when no credentials are available
                    return False
                elif "Authentication must be done manually via VNC" in message:
                    logger.info("Manual VNC authentication required - this is expected")
                    # Return True to indicate we've reached a valid state (SIGN_IN requiring VNC)
                    # This prevents the transition loop from treating manual auth as a failure
                    return True

        return result

    def handle_sign_in_password(self):
        """Handle SIGN_IN_PASSWORD state by entering password."""
        logger.info("Handling SIGN_IN_PASSWORD state - entering password...")
        return self.auth_handler.sign_in()

    def handle_library_sign_in(self):
        """Handle the library sign in state by clicking the sign in button."""
        logger.info("Handling LIBRARY_SIGN_IN state...")
        # Use the new method to handle sign-in
        return self.library_handler.handle_library_sign_in()

    def handle_library(self):
        """Handle LIBRARY state - already in library."""
        logger.info("Handling LIBRARY state - already at destination")
        return True

    def handle_reading(self, server=None):
        """Handle READING state by navigating back to library."""
        logger.info("Handling READING state - navigating back to library...")

        # Add debug page source capture before transitioning
        filepath = store_page_source(self.driver.page_source, "reading_before_transition")
        logger.info(f"Stored page source before navigating from reading state at: {filepath}")

        result = self.reader_handler.navigate_back_to_library()

        # If the navigation was successful and we have a server reference, clear the current book
        if result and server:
            # Get the email from the driver's automator if available
            email = None
            if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "profile_manager"):
                profile = self.driver.automator.profile_manager.get_current_profile()
                if profile and "email" in profile:
                    email = profile.get("email")

            if email:
                server.clear_current_book(email)
                logger.info(f"Cleared current book for {email} after returning to library")
            else:
                logger.warning("Could not get email to clear current book after returning to library")

        # If the navigation failed, capture the state to help with debugging
        if not result:
            filepath = store_page_source(self.driver.page_source, "reading_transition_failed")
            logger.info(f"Stored page source after failed navigation attempt at: {filepath}")

        return result

    def handle_search_results(self):
        """Handle SEARCH_RESULTS state - attempt to open a book from search results.

        This method:
        1. Checks if the search input already contains the query we're looking for
        2. Checks if the book is in the "In your library" section
        3. Opens the book if found, otherwise navigates back to library
        """
        logger.info("Handling SEARCH_RESULTS state...")

        # Check for book_to_open first (set by server.py for this specific purpose)
        # This is the most reliable source of what book we're trying to open
        book_title = None
        if (
            hasattr(self.driver, "automator")
            and hasattr(self.driver.automator, "book_to_open")
            and self.driver.automator.book_to_open
        ):
            book_title = self.driver.automator.book_to_open
            logger.info(f"Found book_to_open in context: '{book_title}', checking if it's in search results")
        # Fall back to current_book_title if book_to_open isn't set
        elif (
            hasattr(self.driver, "automator")
            and hasattr(self.driver.automator, "current_book_title")
            and self.driver.automator.current_book_title
        ):
            book_title = self.driver.automator.current_book_title
            logger.info(
                f"Using current_book_title as fallback: '{book_title}', checking if it's in search results"
            )

        if book_title:
            # Check current search input to see if it matches our desired search
            current_search_query = ""
            try:
                search_query_element = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/search_query"
                )
                if search_query_element and search_query_element.is_displayed():
                    current_search_query = search_query_element.text
                    logger.info(f"Current search query: '{current_search_query}'")

                    # If search query contains our book title (partial match is fine)
                    # or book title contains the search query, likely a match
                    if (
                        current_search_query.lower() in book_title.lower()
                        or book_title.lower() in current_search_query.lower()
                    ):
                        logger.info(
                            f"Search query matches book title: '{current_search_query}' ~ '{book_title}'"
                        )
                    else:
                        logger.info(f"Search query doesn't match book title, but will still check")
            except Exception as e:
                logger.debug(f"Error checking search query: {e}")

            # Try to open the book directly from search results
            # library_handler.open_book already has the logic to look for books on screen
            result = self.library_handler.open_book(book_title)

            if result.get("success"):
                logger.info(f"Successfully opened book '{book_title}' from search results")
                # Clear book_to_open since we successfully handled it
                if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "book_to_open"):
                    self.driver.automator.book_to_open = None
                    logger.info("Cleared book_to_open after successful handling")
                return True

            logger.info(f"Book '{book_title}' not found in search results, navigating back to library")
        else:
            logger.info("No book title found in context, navigating back to library")

        # If we couldn't open the book or there's no book title, navigate back to library
        # Navigate back to library by clicking the back button
        try:
            back_button = self.driver.find_element(
                AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Navigate up']"
            )
            if back_button and back_button.is_displayed():
                logger.info("Clicking back button to exit search results")
                back_button.click()
                time.sleep(1)  # Give time for transition
                return True
        except Exception as e:
            logger.warning(f"Error clicking back button: {e}", exc_info=True)

        # If back button wasn't found or clicked, try a different approach
        return self.view_inspector.ensure_app_foreground()

    def handle_app_not_responding(self):
        """Handle APP_NOT_RESPONDING state by clicking 'Close app' button and waiting for app restart."""
        logger.info("Handling APP_NOT_RESPONDING state - closing and restarting app...")

        try:
            # Store screenshot and page source for debugging
            filepath = store_page_source(self.driver.page_source, "app_not_responding_handling")
            logger.info(f"Stored page source for app not responding at: {filepath}")

            # Click the "Close app" button
            logger.info("Clicking 'Close app' button")
            close_button = self.driver.find_element(*APP_NOT_RESPONDING_CLOSE_APP_BUTTON)
            close_button.click()

            # Wait for app to close
            time.sleep(2)

            # Restart the app
            logger.info("App closed, restarting Kindle app...")

            # Get the automator instance if we can
            automator = getattr(self.driver, "_driver", None)
            if automator:
                automator = getattr(automator, "automator", None)

            if automator and hasattr(automator, "restart_app"):
                # Use the automator's restart_app method
                logger.info("Using automator.restart_app() to restart app...")
                if automator.restart_app():
                    logger.info("App restarted successfully")
                    time.sleep(3)  # Wait for app to initialize
                    return True
                else:
                    logger.error("Failed to restart app with automator.restart_app()", exc_info=True)
                    return False
            else:
                # Fallback to using the view inspector's ensure_app_foreground
                logger.info("No automator reference found, using ensure_app_foreground...")
                if self.view_inspector.ensure_app_foreground():
                    logger.info("App brought to foreground")
                    time.sleep(3)  # Wait for app to initialize
                    return True
                else:
                    logger.error("Failed to restart app with ensure_app_foreground", exc_info=True)
                    return False

        except Exception as e:
            logger.error(f"Error handling app not responding: {e}", exc_info=True)
            # Try restarting the app anyway as a last resort
            try:
                if self.view_inspector.ensure_app_foreground():
                    logger.info("Recovered from error by bringing app to foreground")
                    return True
            except Exception as e2:
                logger.error(f"Failed to recover: {e2}", exc_info=True)
            return False

    def handle_more_settings(self):
        """Handle MORE_SETTINGS state - navigate back to library."""
        logger.info("Handling MORE_SETTINGS state - navigating back to library...")
        return self.library_handler.navigate_to_library()

    def handle_captcha(self):
        """Handle CAPTCHA state - just acknowledge it exists, no automated handling."""
        logger.info("CAPTCHA detected - manual intervention required via VNC")
        # Return False to indicate we can't proceed automatically
        return False

    def handle_two_factor(self):
        """Handle TWO_FACTOR state - just acknowledge it exists, no automated handling."""
        logger.info("Two-Step Verification detected - manual intervention required via VNC")
        # Store page source for debugging
        try:
            filepath = store_page_source(self.driver.page_source, "two_factor_auth")
            logger.info(f"Stored Two-Step Verification page source at: {filepath}")
        except Exception as e:
            logger.warning(f"Error storing 2FA page source: {e}", exc_info=True)
        # Return False to indicate we can't proceed automatically
        return False

    def handle_puzzle(self):
        """Handle PUZZLE state - just acknowledge it exists, no automated handling."""
        logger.info("Puzzle authentication detected - manual intervention required via VNC")
        # Store page source for debugging
        try:
            filepath = store_page_source(self.driver.page_source, "puzzle_auth")
            logger.info(f"Stored puzzle authentication page source at: {filepath}")
        except Exception as e:
            logger.warning(f"Error storing puzzle page source: {e}", exc_info=True)
        # Return False to indicate we can't proceed automatically
        return False

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
            AppState.SEARCH_RESULTS: self.handle_search_results,  # Add new SEARCH_RESULTS handler
            AppState.READING: self.handle_reading,
            AppState.CAPTCHA: self.handle_captcha,  # CAPTCHA handler for detection only
            AppState.TWO_FACTOR: self.handle_two_factor,  # TWO_FACTOR handler for detection only
            AppState.PUZZLE: self.handle_puzzle,  # PUZZLE handler for detection only
            AppState.APP_NOT_RESPONDING: self.handle_app_not_responding,  # Add app not responding handler
            AppState.MORE_SETTINGS: self.handle_more_settings,  # Add more settings handler
        }

        handler = handlers.get(state)
        if not handler:
            logger.error(f"No handler found for state {state}", exc_info=True)
        return handler
