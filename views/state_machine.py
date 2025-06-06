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
        # Flag to indicate we're preparing a seed clone (skip sign-in)
        self.preparing_seed_clone = False

    def _get_current_state(self):
        """Get the current app state using the view inspector."""
        view = self.view_inspector.get_current_view()
        return AppState[view.name]

    def transition_to_library(self, max_transitions=5, server=None):
        """Attempt to transition to the library state."""
        transitions = 0
        unknown_retries = 0
        MAX_UNKNOWN_RETRIES = 2  # Maximum times to try recovering from UNKNOWN state

        logger.info(f"Attempting to transition to library from {self.current_state}")

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

            # Special handling for LIBRARY_SIGN_IN when preparing seed clone
            if self.current_state == AppState.LIBRARY_SIGN_IN and self.preparing_seed_clone:
                logger.info("In LIBRARY_SIGN_IN state and preparing_seed_clone=True - stopping here")
                # We've reached the library view with sign-in button, which is what we want for seed clone
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
                    logger.info("Still in UNKNOWN state, checking for dialogs...")
                    # Check for common dialogs that might be causing the UNKNOWN state
                    from views.common.dialog_handler import DialogHandler

                    dialog_handler = DialogHandler(self.driver)

                    # Get the current activity name
                    current_activity = None
                    try:
                        current_activity = self.driver.current_activity
                        logger.info(f"Current activity: {current_activity}")
                    except Exception as e:
                        logger.debug(f"Error getting current activity: {e}")

                    # Check specifically for AlertActivity which often contains dialogs
                    if current_activity and "AlertActivity" in current_activity:
                        logger.info(f"Detected AlertActivity, checking for known dialogs...")

                        # Check for dialogs without requiring book title
                        handled, dialog_type = dialog_handler.check_all_dialogs(None, "in UNKNOWN state")
                        if handled:
                            logger.info(f"Successfully handled {dialog_type} dialog in UNKNOWN state")
                            # Try to update state after handling dialog
                            self.current_state = self._get_current_state()
                            # If still unknown, try to re-enter the app
                            if self.current_state == AppState.UNKNOWN:
                                if self.view_inspector.ensure_app_foreground():
                                    logger.info("Brought app to foreground after handling dialog")
                                    time.sleep(1)
                                    self.current_state = self._get_current_state()
                            return True

                    # If dialog handling didn't work, try checking for library-specific elements
                    logger.info("Checking for library-specific elements...")
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
                logger.info("In CAPTCHA state - manual intervention required")
                # Return True to indicate we're in a valid state but can't proceed
                return True
            # Special handling for TWO_FACTOR state
            elif self.current_state == AppState.TWO_FACTOR:
                logger.info("In TWO_FACTOR state - manual intervention required")
                # Return True to indicate we're in a valid state but can't proceed
                return True
            # Check if sign-in is in sign-in state without credentials
            elif not result and self.current_state == AppState.SIGN_IN:
                new_state = self._get_current_state()
                if new_state == AppState.CAPTCHA:
                    logger.info("Sign-in resulted in CAPTCHA state - waiting for manual intervention")
                    self.current_state = new_state
                    return True
                elif new_state == AppState.TWO_FACTOR:
                    logger.info("Sign-in resulted in TWO_FACTOR state - waiting for manual intervention")
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

    def handle_state(self) -> bool:
        """Handle the current state using the appropriate state handler.

        This method is called when we want to execute the handler for the current state
        without forcing a transition to a specific target state.

        Returns:
            bool: True if state was handled successfully, False otherwise
        """
        # Make sure we have the latest state
        self.update_current_state()

        # Get the handler for the current state
        handler = self.transitions.get_handler_for_state(self.current_state)
        if not handler:
            logger.error(f"No handler found for state {self.current_state}")
            return False

        # Execute the handler
        logger.info(f"Handling current state: {self.current_state}")
        result = handler()

        # Log the result
        if result:
            logger.info(f"Successfully handled state {self.current_state}")
        else:
            logger.error(f"Failed to handle state {self.current_state}")

        return result

    def is_reading_view(self) -> bool:
        """Lightweight check to determine if we're in the reading view.

        This is a cheaper check than the full state detection, specifically for
        determining if we're currently reading a book.

        Returns:
            bool: True if we're in the reading view, False otherwise
        """
        try:
            from selenium.common.exceptions import NoSuchElementException

            # Priority elements that are most commonly present in reading view
            PRIORITY_READING_ELEMENTS = [
                ("id", "com.amazon.kindle:id/reader_drawer_layout"),
                ("id", "com.amazon.kindle:id/reader_content_fragment_container"),
                ("id", "com.amazon.kindle:id/reader_page_fragment_container"),
                ("id", "com.amazon.kindle:id/reader_content_container"),
                ("id", "com.amazon.kindle:id/reader_menu_container"),
            ]

            # Check priority elements first
            reading_elements_count = 0
            elements_found = []

            for strategy, locator in PRIORITY_READING_ELEMENTS:
                try:
                    from appium.webdriver.common.appiumby import AppiumBy

                    element = self.driver.find_element(AppiumBy.ID if strategy == "id" else strategy, locator)
                    # Just check if element exists, don't require is_displayed() for quick check
                    reading_elements_count += 1
                    elements_found.append(locator)
                    if reading_elements_count >= 2:
                        logger.debug(
                            f"Quick reading view check: confirmed reading view with {elements_found}"
                        )
                        return True
                except NoSuchElementException:
                    # Element not found, continue checking
                    continue
                except Exception as e:
                    # Log unexpected errors but continue
                    logger.debug(f"Unexpected error checking {locator}: {type(e).__name__}")
                    continue

            # If we didn't find enough priority elements, check the full list
            if reading_elements_count < 2:
                from views.reading.view_strategies import READING_VIEW_IDENTIFIERS

                for strategy, locator in READING_VIEW_IDENTIFIERS:
                    # Skip ones we already checked
                    if locator in [loc for _, loc in PRIORITY_READING_ELEMENTS]:
                        continue

                    try:
                        element = self.driver.find_element(strategy, locator)
                        reading_elements_count += 1
                        elements_found.append(locator)
                        if reading_elements_count >= 2:
                            logger.debug(
                                f"Quick reading view check: confirmed reading view with {elements_found}"
                            )
                            return True
                    except NoSuchElementException:
                        continue
                    except Exception as e:
                        logger.debug(f"Unexpected error checking {locator}: {type(e).__name__}")
                        continue

            # Also check for RemoteLicenseReleaseActivity which indicates we're in reading view
            try:
                current_activity = self.driver.current_activity
                if "RemoteLicenseReleaseActivity" in current_activity:
                    logger.debug("Quick reading view check: RemoteLicenseReleaseActivity detected")
                    return True
            except Exception:
                pass

            logger.debug(
                f"Quick reading view check: found {reading_elements_count} reading elements {elements_found} - not in reading view"
            )
            return False

        except Exception as e:
            logger.error(f"Error in is_reading_view check: {e}")
            return False

    def update_current_state(self) -> AppState:
        """Update and return the current state of the app.

        Returns:
            AppState: The current state of the app
        """
        try:
            # If we're currently in an AUTH state (SIGN_IN, SIGN_IN_PASSWORD, CAPTCHA, TWO_FACTOR),
            # check if keyboard hiding is active and hide the keyboard if visible
            if hasattr(self, "current_state") and self.current_state in [
                AppState.SIGN_IN,
                AppState.SIGN_IN_PASSWORD,
                AppState.CAPTCHA,
                AppState.TWO_FACTOR,
            ]:
                if (
                    hasattr(self.auth_handler, "is_keyboard_check_active")
                    and self.auth_handler.is_keyboard_check_active()
                ):
                    # Just hide the keyboard continuously without tapping fields
                    # (tapping is now handled by view_inspector during view detection)
                    self.auth_handler.hide_keyboard_if_visible()

            # Check if we have a current state we already know about
            # For HOME, LIBRARY, and SEARCH_RESULTS states that were recently detected, avoid redundant checks
            # within a short timeframe
            if hasattr(self, "_last_state_check_time") and hasattr(self, "_last_state_value"):
                time_since_last_check = time.time() - self._last_state_check_time
                # If we've checked state within the last second and it was HOME, LIBRARY, or SEARCH_RESULTS, just return the cached value
                if time_since_last_check < 1.0 and self._last_state_value in [
                    AppState.HOME,
                    AppState.LIBRARY,
                    AppState.SEARCH_RESULTS,
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

            # Track authentication state changes
            if self.current_state in [AppState.LIBRARY, AppState.LIBRARY_SIGN_IN]:
                try:
                    from datetime import datetime

                    profile_manager = self.driver.automator.profile_manager
                    profile = profile_manager.get_current_profile()
                    email = profile.get("email")

                    current_date = datetime.now().isoformat()

                    if self.current_state == AppState.LIBRARY:
                        # User is authenticated - set auth_date if not already set
                        auth_date = profile_manager.get_user_field(email, "auth_date")
                        if not auth_date:
                            logger.info(f"Setting auth_date for {email} as user is in LIBRARY state")
                            profile_manager.set_user_field(email, "auth_date", current_date)

                        # Clear auth_failed_date if it exists
                        auth_failed_date = profile_manager.get_user_field(email, "auth_failed_date")
                        if auth_failed_date:
                            logger.info(
                                f"Clearing auth_failed_date for {email} as user is back in LIBRARY state"
                            )
                            profile_manager.set_user_field(email, "auth_failed_date", None)

                    elif self.current_state == AppState.LIBRARY_SIGN_IN:
                        # User lost authentication - set auth_failed_date
                        logger.info(
                            f"Setting auth_failed_date for {email} as user is in LIBRARY_SIGN_IN state"
                        )
                        profile_manager.set_user_field(email, "auth_failed_date", current_date)

                except Exception as e:
                    logger.warning(f"Error tracking auth state: {e}")

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

            # For HOME, LIBRARY, and SEARCH_RESULTS states, trust the detection and return immediately
            # These are the most common states and we're confident in our detection
            if self.current_state in [AppState.HOME, AppState.LIBRARY, AppState.SEARCH_RESULTS]:
                return self.current_state

            # If we detect READING but we've just clicked close book, make a special check
            if self.current_state == AppState.READING:
                # Check for download limit dialog first, which is a special case within reading state
                from views.common.dialog_strategies import (
                    DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
                )
                from views.reading.interaction_strategies import (
                    handle_item_removed_dialog,
                )
                from views.reading.view_strategies import (
                    ITEM_REMOVED_DIALOG_IDENTIFIERS,
                    is_item_removed_dialog_visible,
                )

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
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error updating current state: {e}")
            self.current_state = AppState.UNKNOWN
            return self.current_state
