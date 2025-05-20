import logging
import os
import time

from handlers.auth_handler import AuthenticationHandler
from handlers.library_handler import LibraryHandler
from handlers.permissions_handler import PermissionsHandler
from handlers.reader_handler import ReaderHandler
from handlers.style_handler import StyleHandler
from server.logging_config import store_page_source
from views.core.app_state import AppState, AppView
from views.library.view_strategies import LIBRARY_ELEMENT_DETECTION_STRATEGIES
from views.transitions import StateTransitions
from views.view_inspector import ViewInspector

logger = logging.getLogger(__name__)


class KindleStateMachine:
    """State machine for managing Kindle app states and transitions."""

    def __init__(self, driver):
        """Initialize the state machine with required handlers."""
        self.driver = driver
        self.view_inspector = ViewInspector(driver)
        # Initialize auth handler without captcha solution - it'll be set later if needed
        self.auth_handler = AuthenticationHandler(driver)
        self.library_handler = LibraryHandler(driver)
        self.style_handler = StyleHandler(driver)
        self.reader_handler = ReaderHandler(driver)
        # Set library_handler reference in reader_handler
        self.reader_handler.library_handler = self.library_handler
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
        # Track the last captcha screenshot for use in responses
        self.last_captcha_screenshot_id = None

    def get_captcha_screenshot_id(self):
        """Get the ID of the last captcha screenshot taken.

        This is used by the response handler to include the correct image URL.
        If auth_handler has a more recent screenshot, use that.

        Returns:
            str: The ID of the last captcha screenshot, or None if no screenshot available
        """
        # Check if auth handler has a more recent screenshot
        if (
            hasattr(self.auth_handler, "last_captcha_screenshot")
            and self.auth_handler.last_captcha_screenshot
        ):
            logger.info(
                f"Using auth handler's captcha screenshot ID: {self.auth_handler.last_captcha_screenshot}"
            )
            return self.auth_handler.last_captcha_screenshot

        # Otherwise use our tracked screenshot ID
        return self.last_captcha_screenshot_id

    def _get_current_state(self):
        """Get the current app state using the view inspector."""
        view = self.view_inspector.get_current_view()
        return AppState[view.name]

    def transition_to_library(self, max_transitions=5, server=None):
        """Attempt to transition to the library state."""
        transitions = 0
        unknown_retries = 0
        MAX_UNKNOWN_RETRIES = 2  # Maximum times to try recovering from UNKNOWN state

        while transitions < max_transitions:
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

            # Special handling for RemoteLicenseReleaseActivity dialog
            try:
                current_activity = self.driver.current_activity
                if "RemoteLicenseReleaseActivity" in current_activity:
                    logger.info("Detected Download Limit dialog during transition - treating as READING")
                    self.current_state = AppState.READING
            except Exception as e:
                logger.debug(f"Error checking for RemoteLicenseReleaseActivity: {e}")

            # If we have a server reference and we're not in reading state but have a current book
            # Clear the current book to ensure state consistency
            if server and self.current_state != AppState.READING:
                # Get the email from our driver instance if possible
                email = None
                if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "profile_manager"):
                    profile = self.driver.automator.profile_manager.get_current_profile()
                    if profile and "email" in profile:
                        email = profile.get("email")

                # Check if there's a current book for this email
                if email and email in server.current_books:
                    logger.info(
                        f"Not in reading state ({self.current_state}) but have current book tracked for {email} - clearing it"
                    )
                    server.clear_current_book(email)

            if self.current_state == AppState.LIBRARY:
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
                    # Check if we're in search interface (which is part of library)
                    if self.library_handler._is_in_search_interface():
                        logger.info("Library handler detected search interface - treating as library view")
                        self.current_state = AppState.LIBRARY  # Update the state
                        # Exit search mode to get to main library view
                        if self.library_handler.search_handler._exit_search_mode():
                            logger.info("Exited search mode, now in library view")
                            return True
                        else:
                            logger.warning("Failed to exit search mode")

                continue

            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                logger.error(f"No handler found for state {self.current_state}")
                return False

            # Handle current state
            # For reading state, pass the server instance
            if self.current_state == AppState.READING and server:
                result = handler(server)
            else:
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
            # Check if sign-in resulted in CAPTCHA or is in sign-in state without credentials
            elif not result and self.current_state == AppState.SIGN_IN:
                new_state = self._get_current_state()
                if new_state == AppState.CAPTCHA:
                    logger.info("Sign-in resulted in CAPTCHA state - waiting for client interaction")
                    self.current_state = new_state
                    return True
                elif new_state == AppState.SIGN_IN and not self.auth_handler.email:
                    logger.info("Sign-in view detected but no credentials provided")
                    self.current_state = AppState.SIGN_IN
                    return True  # Return true for special handling in BooksResource

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
            # If we're currently in an AUTH state (SIGN_IN, SIGN_IN_PASSWORD, CAPTCHA),
            # check if keyboard hiding is active and hide the keyboard if visible
            if hasattr(self, "current_state") and self.current_state in [
                AppState.SIGN_IN,
                AppState.SIGN_IN_PASSWORD,
                AppState.CAPTCHA,
            ]:
                if (
                    hasattr(self.auth_handler, "is_keyboard_check_active")
                    and self.auth_handler.is_keyboard_check_active()
                ):
                    # Just hide the keyboard continuously without tapping fields
                    # (tapping is now handled by view_inspector during view detection)
                    self.auth_handler.hide_keyboard_if_visible()

            # Check if we have a current state we already know about
            # For HOME and LIBRARY states that were recently detected, avoid redundant checks
            # within a short timeframe
            if hasattr(self, "_last_state_check_time") and hasattr(self, "_last_state_value"):
                time_since_last_check = time.time() - self._last_state_check_time
                # If we've checked state within the last second and it was HOME or LIBRARY, just return the cached value
                if time_since_last_check < 1.0 and self._last_state_value in [
                    AppState.HOME,
                    AppState.LIBRARY,
                ]:
                    logger.info(
                        f"Using cached state from {time_since_last_check:.2f}s ago: {self._last_state_value}"
                    )
                    self.current_state = self._last_state_value
                    return self.current_state

            # Get current state from view inspector without storing page source first
            # Only store page source for unknown or ambiguous states
            self.current_state = self._get_current_state()
            logger.info(f"Updated current state to: {self.current_state}")

            # Simple check for RemoteLicenseReleaseActivity if state is UNKNOWN
            if self.current_state == AppState.UNKNOWN:
                try:
                    current_activity = self.driver.current_activity
                    if "RemoteLicenseReleaseActivity" in current_activity:
                        logger.info("Detected RemoteLicenseReleaseActivity - setting state to READING")
                        self.current_state = AppState.READING
                except Exception as e:
                    logger.debug(f"Error checking for RemoteLicenseReleaseActivity: {e}")

            # Cache the state detection time and value
            self._last_state_check_time = time.time()
            self._last_state_value = self.current_state

            # For HOME and LIBRARY states, trust the detection and return immediately
            # These are the most common states and we're confident in our detection
            if self.current_state in [AppState.HOME, AppState.LIBRARY]:
                return self.current_state

            # If we detect READING but we've just clicked close book, make a special check
            if self.current_state == AppState.READING:
                # Check for download limit dialog first, which is a special case within reading state
                from views.common.dialog_strategies import (
                    DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
                )
                from views.reading.view_strategies import (
                    ITEM_REMOVED_DIALOG_IDENTIFIERS,
                    is_item_removed_dialog_visible,
                )
                from views.reading.interaction_strategies import handle_item_removed_dialog

                # Check for Item Removed dialog
                if is_item_removed_dialog_visible(self.driver):
                    logger.info("Item Removed dialog detected in reading view")
                    # Handle the dialog - this will close it and take us back to library
                    handle_item_removed_dialog(self.driver)
                    # We'll need to transition back to library
                    self.current_state = AppState.LIBRARY
                    return self.current_state

                download_limit_elements = 0
                for strategy, locator in DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS:
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element.is_displayed():
                            download_limit_elements += 1
                            logger.info(f"Found download limit dialog element: {strategy}={locator}")
                    except Exception:
                        continue

                # Also check for specific activity name
                try:
                    current_activity = self.driver.current_activity
                    if "RemoteLicenseReleaseActivity" in current_activity:
                        download_limit_elements += 1
                        logger.info(f"Found RemoteLicenseReleaseActivity: {current_activity}")
                except Exception as e:
                    logger.debug(f"Error checking current activity: {e}")

                # If we found at least 2 elements of the download limit dialog, we're confident we need
                # to handle this dialog via reader_handler before continuing
                if download_limit_elements >= 2:
                    logger.info("Download limit reached dialog detected within READING state")
                    # Don't override the state as it's correctly detected as READING already
                    return self.current_state

                # Double check for library elements
                library_elements_found = False
                logger.info("State detected as READING - double checking for library elements...")

                # First verify that we have strong reading view indicators
                from views.reading.view_strategies import READING_VIEW_IDENTIFIERS

                reading_elements_count = 0
                for strategy, locator in READING_VIEW_IDENTIFIERS:
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element.is_displayed():
                            reading_elements_count += 1
                    except Exception:
                        continue

                # Only check for library elements if we don't have strong reading indicators
                if reading_elements_count < 2:
                    for strategy, locator in LIBRARY_ELEMENT_DETECTION_STRATEGIES:
                        try:
                            element = self.driver.find_element(strategy, locator)
                            if element.is_displayed():
                                logger.info(
                                    f"Found library element {strategy}={locator} despite READING state detection"
                                )
                                library_elements_found = True
                                break
                        except Exception:
                            continue

                    if library_elements_found:
                        logger.info("Overriding state from READING to LIBRARY based on element detection")
                        self.current_state = AppState.LIBRARY
                else:
                    logger.info(f"Confirmed READING state with {reading_elements_count} strong indicators")

            # If unknown, try to detect specific states, but only store debug info for unknown state
            if self.current_state == AppState.UNKNOWN:
                # Check if we're even in the Kindle app by checking current activity
                try:
                    current_activity = self.driver.current_activity
                    logger.info(f"Current activity: {current_activity}")

                    # If the current activity is not Kindle (e.g. NexusLauncherActivity), the app has quit
                    # Check for both com.amazon.kindle and com.amazon.kcp activities (both are valid Kindle app activities)
                    # Also accept the Google Play review dialog which can appear over the Kindle app
                    # Explicitly handle the RemoteLicenseReleaseActivity (Download Limit dialog) as a known activity
                    if not (
                        current_activity.startswith("com.amazon.kindle")
                        or current_activity.startswith("com.amazon.kcp")
                        or "RemoteLicenseReleaseActivity" in current_activity
                        or current_activity
                        == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
                    ):
                        logger.warning("App has quit or was not launched - current activity is not Kindle")

                        # Try to relaunch the app
                        if self.view_inspector.ensure_app_foreground():
                            logger.info("Successfully relaunched Kindle app, waiting for it to initialize...")
                            time.sleep(2)  # Wait for app to fully initialize

                            # Update the state again after relaunch
                            self.current_state = self._get_current_state()
                            logger.info(f"After app relaunch, state is: {self.current_state}")

                            # If we're now in a known state, return it
                            if self.current_state != AppState.UNKNOWN:
                                return self.current_state

                except Exception as e:
                    logger.error(f"Error checking current activity: {e}")

                # Store page source for debugging if still unknown
                source = self.driver.page_source
                filepath = store_page_source(source, "unknown_state")
                logger.info(f"Stored unknown state page source at: {filepath}")

                # Try to detect library state specifically
                if self.library_handler._is_library_tab_selected():
                    self.current_state = AppState.LIBRARY
                    logger.info("Detected LIBRARY state from library handler")

                # Check for reading view dialog elements (simplified)
                try:
                    from views.reading.view_strategies import (
                        GO_TO_LOCATION_DIALOG_IDENTIFIERS,
                    )

                    # Check for "Go to that location?" dialog
                    for strategy, locator in GO_TO_LOCATION_DIALOG_IDENTIFIERS:
                        try:
                            element = self.driver.find_element(strategy, locator)
                            if element.is_displayed() and "Go to that location?" in element.text:
                                self.current_state = AppState.READING
                                logger.info("Detected READING state from 'Go to that location?' dialog")
                                break
                        except:
                            continue
                except Exception as e:
                    logger.error(f"Error checking for reading state: {e}")

            return self.current_state

        except Exception as e:
            logger.error(f"Error updating current state: {e}")
            self.current_state = AppState.UNKNOWN
            return self.current_state
