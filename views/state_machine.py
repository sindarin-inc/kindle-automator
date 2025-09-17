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
        # Give transitions a reference to state machine for cancellation checks
        self.transitions.state_machine = self
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.current_state = AppState.UNKNOWN
        # Flag to indicate we're preparing a seed clone (skip sign-in)
        self.preparing_seed_clone = False
        # Optional cancellation check function for interruptible operations
        self._cancellation_check = None

    def set_cancellation_check(self, check_func):
        """Set a function to check for cancellation during long operations.

        Args:
            check_func: A callable that returns True if operation should be cancelled
        """
        self._cancellation_check = check_func

    def _get_current_state(self):
        """Get the current app state using the view inspector."""
        view = self.view_inspector.get_current_view()
        return AppState[view.name]

    def transition_to_library(self, max_transitions=5, server=None):
        """Attempt to transition to the library state.

        Returns:
            AppState: The final state after transition attempt
        """
        transitions = 0
        unknown_retries = 0
        MAX_UNKNOWN_RETRIES = 2  # Maximum times to try recovering from UNKNOWN state

        logger.info(f"Attempting to transition to library from {self.current_state}")

        while transitions < max_transitions:
            # Skip expensive state check if we already know we're in library
            # (e.g., when set directly by handle_reading after successful navigation)
            if self.current_state != AppState.LIBRARY:
                self.current_state = self._get_current_state()
                logger.info(f"Current state: {self.current_state}")
            else:
                logger.info(f"Current state already set to: {self.current_state}")

            # Special handling for RemoteLicenseReleaseActivity dialog
            try:
                current_activity = self.driver.current_activity
                if "RemoteLicenseReleaseActivity" in current_activity:
                    logger.debug("Detected Download Limit dialog during transition - treating as READING")
                    self.current_state = AppState.READING
            except Exception as e:
                logger.debug(f"Error checking for RemoteLicenseReleaseActivity: {e}")

            # If we have a server reference and we're not in reading state but have a current book
            # Clear the current book to ensure state consistency
            if server and self.current_state != AppState.READING:
                # Get the email from our driver instance
                profile = self.driver.automator.profile_manager.get_current_profile()
                email = profile.get("email") if profile else None

                # Check if there's a current book for this email
                if email and server.get_current_book(email):
                    logger.debug(
                        f"Not in reading state ({self.current_state}) but have current book tracked for {email} - clearing it"
                    )
                    server.clear_current_book(email)

            # Handle TABLE_OF_CONTENTS state - exit it to go to reading or library
            if self.current_state == AppState.TABLE_OF_CONTENTS:
                logger.info("In TABLE_OF_CONTENTS state, attempting to exit to reading/library view")
                self.exit_table_of_contents()
                # Update state and continue the loop
                self.current_state = self._get_current_state()
                continue

            if self.current_state == AppState.LIBRARY:
                # Update auth tracking when we reach library
                try:
                    from datetime import datetime

                    profile_manager = self.driver.automator.profile_manager
                    profile = profile_manager.get_current_profile()
                    email = profile.get("email")

                    # User is authenticated
                    profile_manager.update_auth_state(email, authenticated=True)
                except Exception as e:
                    logger.warning(f"Error updating auth tracking during transition: {e}")

                # Switch to list view if needed
                if not self.library_handler.switch_to_list_view():
                    logger.warning("Failed to switch to list view, but we're still in library")
                return self.current_state

            # Special handling for LIBRARY_SIGN_IN when preparing seed clone
            if self.current_state == AppState.LIBRARY_SIGN_IN and self.preparing_seed_clone:
                logger.info("In LIBRARY_SIGN_IN state and preparing_seed_clone=True - stopping here")
                # We've reached the library view with sign-in button, which is what we want for seed clone
                return self.current_state

            # If we're in UNKNOWN state, try to bring app to foreground
            if self.current_state == AppState.UNKNOWN:
                unknown_retries += 1
                if unknown_retries > MAX_UNKNOWN_RETRIES:
                    logger.error(
                        f"Failed to recover from UNKNOWN state after {MAX_UNKNOWN_RETRIES} attempts. "
                        "Please check screenshots/unknown_view.png and fixtures/dumps/unknown_view.xml "
                        "to determine why the view cannot be recognized.",
                        exc_info=True,
                    )
                    return self.current_state

                logger.info(
                    f"In UNKNOWN state (attempt {unknown_retries}/{MAX_UNKNOWN_RETRIES}) - bringing app to foreground..."
                )
                if not self.view_inspector.ensure_app_foreground():
                    logger.error("Failed to bring app to foreground", exc_info=True)
                    return self.current_state
                # Sleep and check for cancellation
                time.sleep(1)
                if self._cancellation_check and self._cancellation_check():
                    logger.info(f"[{time.time():.3f}] Transition cancelled during app foreground wait")
                    return self.current_state

                # Try to get the current state again
                self.current_state = self._get_current_state()
                logger.info(f"After bringing app to foreground, state is: {self.current_state}")
                if self.current_state == AppState.LIBRARY:
                    logger.debug("Successfully reached library state after bringing app to foreground")
                    # Update auth tracking when we reach library
                    try:
                        from datetime import datetime

                        profile_manager = self.driver.automator.profile_manager
                        profile = profile_manager.get_current_profile()
                        email = profile.get("email")

                        # User is authenticated
                        profile_manager.update_auth_state(email, authenticated=True)
                    except Exception as e:
                        logger.warning(f"Error updating auth tracking after app foreground: {e}")
                    return self.current_state

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

                    # Check for dialogs in both AlertActivity and StandAloneBookReaderActivity
                    if current_activity and (
                        "AlertActivity" in current_activity
                        or "StandAloneBookReaderActivity" in current_activity
                    ):
                        logger.debug(f"Detected {current_activity}, checking for known dialogs...")

                        # Check for dialogs without requiring book title
                        handled, dialog_type = dialog_handler.check_all_dialogs(None, "in UNKNOWN state")
                        if handled:
                            logger.debug(f"Successfully handled {dialog_type} dialog in UNKNOWN state")
                            # Try to update state after handling dialog
                            self.current_state = self._get_current_state()

                            # If we're now in READING state after handling the dialog, we're done
                            if self.current_state == AppState.READING:
                                logger.debug("Now in READING state after handling dialog")
                                return self.current_state

                            # If still unknown, try to re-enter the app
                            if self.current_state == AppState.UNKNOWN:
                                if self.view_inspector.ensure_app_foreground():
                                    logger.debug("Brought app to foreground after handling dialog")
                                    # Sleep and check for cancellation
                                    time.sleep(1)
                                    if self._cancellation_check and self._cancellation_check():
                                        logger.info(
                                            f"[{time.time():.3f}] Transition cancelled during dialog handling wait"
                                        )
                                        return self.current_state
                                    self.current_state = self._get_current_state()
                            continue  # Continue the loop to re-check state

                    # If dialog handling didn't work, try checking for library-specific elements
                    logger.debug("Checking for library-specific elements...")
                    if self.library_handler._is_library_tab_selected():
                        logger.debug("Library handler detected library view")
                        return self.current_state
                    # Check if we're in search interface (which is part of library)
                    if self.library_handler._is_in_search_interface():
                        logger.debug("Library handler detected search interface - treating as library view")
                        self.current_state = AppState.LIBRARY  # Update the state
                        # Exit search mode to get to main library view
                        if self.library_handler.search_handler._exit_search_mode():
                            logger.debug("Exited search mode, now in library view")
                            return self.current_state
                        else:
                            logger.warning("Failed to exit search mode")

                continue

            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                logger.error(f"No handler found for state {self.current_state}", exc_info=True)
                return self.current_state

            # Handle current state
            # For reading state, pass the server instance
            if self.current_state == AppState.READING and server:
                result = handler(server)
            else:
                result = handler()

            # Special handling for CAPTCHA state
            if self.current_state == AppState.CAPTCHA:
                logger.info("In CAPTCHA state - manual intervention required")
                # Return current state to indicate we're in a valid state but can't proceed
                return self.current_state
            # Special handling for TWO_FACTOR state
            elif self.current_state == AppState.TWO_FACTOR:
                logger.info("In TWO_FACTOR state - manual intervention required")
                # Return current state to indicate we're in a valid state but can't proceed
                return self.current_state
            # Special handling for PUZZLE state
            elif self.current_state == AppState.PUZZLE:
                logger.info("In PUZZLE state - manual intervention required")
                # Return current state to indicate we're in a valid state but can't proceed
                return self.current_state
            # Special handling for SIGN_IN state
            elif self.current_state == AppState.SIGN_IN:
                if result:
                    # If handler returned True, we're in a valid SIGN_IN state requiring VNC
                    logger.info("SIGN_IN state requires manual VNC authentication")
                    return self.current_state
                else:
                    # Check what state we're in after failed sign-in attempt
                    new_state = self._get_current_state()
                    if new_state == AppState.CAPTCHA:
                        logger.info("Sign-in resulted in CAPTCHA state - waiting for manual intervention")
                        self.current_state = new_state
                        return self.current_state
                    elif new_state == AppState.TWO_FACTOR:
                        logger.info("Sign-in resulted in TWO_FACTOR state - waiting for manual intervention")
                        self.current_state = new_state
                        return self.current_state
                    elif new_state == AppState.PUZZLE:
                        logger.info("Sign-in resulted in PUZZLE state - waiting for manual intervention")
                        self.current_state = new_state
                        return self.current_state
                    elif new_state == AppState.SIGN_IN and not self.auth_handler.email:
                        logger.info("Sign-in view detected but no credentials provided")
                        self.current_state = AppState.SIGN_IN
                        return self.current_state

            if not result:
                logger.error(f"Handler failed for state {self.current_state}", exc_info=True)
                return self.current_state

            transitions += 1

        logger.error(f"Failed to reach library state after {max_transitions} transitions", exc_info=True)
        logger.error(f"Final state: {self.current_state}", exc_info=True)

        # Log the page source for debugging and store it
        try:
            source = self.view_inspector.driver.page_source

            # Store the page source
            store_page_source(source, "failed_transition")

            # Also save a screenshot for visual debugging
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "failed_transition.png")
                self.view_inspector.driver.save_screenshot(screenshot_path)
            except Exception as e:
                logger.warning(f"Failed to save transition error screenshot: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"Failed to get page source after failed transitions: {e}", exc_info=True)

        return self.current_state

    def _handle_failed_transition(self, from_state, to_state, error):
        """Handle a failed state transition by logging details and saving screenshot"""
        logger.error(f"Failed to transition from {from_state} to {to_state}: {error}", exc_info=True)
        try:
            # Store page source
            source = self.view_inspector.driver.page_source
            store_page_source(source, f"failed_transition_{from_state}_to_{to_state}")

            # Save screenshot
            screenshot_path = os.path.join(self.screenshots_dir, "failed_transition.png")
            self.view_inspector.driver.save_screenshot(screenshot_path)
        except Exception as e:
            logger.warning(f"Failed to save transition error data: {e}", exc_info=True)

    def exit_table_of_contents(self) -> AppState:
        """Exit the Table of Contents view and return to the reading view.

        Returns:
            AppState: The state after exiting ToC (should be READING or LIBRARY)
        """
        # First check if we're actually in ToC state
        self.update_current_state()

        if self.current_state != AppState.TABLE_OF_CONTENTS:
            logger.debug(f"Not in TABLE_OF_CONTENTS state (current: {self.current_state})")
            return self.current_state

        logger.info("Attempting to exit Table of Contents view")

        try:
            # Try to close the ToC dialog using the close button
            from appium.webdriver.common.appiumby import AppiumBy

            from views.reading.view_strategies import (
                TABLE_OF_CONTENTS_CLOSE_BUTTON_IDENTIFIERS,
            )

            for strategy, locator in TABLE_OF_CONTENTS_CLOSE_BUTTON_IDENTIFIERS:
                try:
                    close_button = self.driver.find_element(strategy, locator)
                    if close_button.is_displayed():
                        close_button.click()
                        logger.info(f"Closed ToC using close button: {locator}")
                        time.sleep(1)
                        self.update_current_state()
                        return self.current_state
                except:
                    continue

            # If close button doesn't work, try tapping back
            logger.info("Close button not found, trying back navigation")
            self.driver.back()
            time.sleep(1)
            self.update_current_state()

        except Exception as e:
            logger.error(f"Failed to exit Table of Contents: {e}", exc_info=True)

        return self.current_state

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
            logger.error(f"No handler found for state {self.current_state}", exc_info=True)
            return False

        # Execute the handler
        logger.info(f"Handling current state: {self.current_state}")
        result = handler()

        # Log the result
        if result:
            logger.debug(f"Successfully handled state {self.current_state}")
        else:
            logger.error(f"Failed to handle state {self.current_state}", exc_info=True)

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
            logger.warning(f"Error in is_reading_view check: {e}", exc_info=True)
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
                AppState.PUZZLE,
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
                    logger.debug(
                        f"Using cached state from {time_since_last_check:.2f}s ago: {self._last_state_value}"
                    )
                    self.current_state = self._last_state_value
                    return self.current_state

            # Get current state from view inspector without storing page source first
            # Only store page source for unknown or ambiguous states
            self.current_state = self._get_current_state()
            logger.info(f"Updated current state to: {self.current_state}")

            # Track authentication state changes
            if self.current_state in [AppState.LIBRARY, AppState.LIBRARY_SIGN_IN, AppState.SEARCH_RESULTS]:
                try:
                    from datetime import datetime

                    profile_manager = self.driver.automator.profile_manager
                    profile = profile_manager.get_current_profile()
                    email = profile.get("email")

                    if self.current_state == AppState.LIBRARY:
                        # User is authenticated
                        profile_manager.update_auth_state(email, authenticated=True)

                    elif self.current_state == AppState.LIBRARY_SIGN_IN:
                        # User lost authentication
                        profile_manager.update_auth_state(email, authenticated=False)

                    elif self.current_state == AppState.SEARCH_RESULTS:
                        # Check if user has auth_date when in search results
                        auth_date = profile_manager.get_user_field(email, "auth_date")
                        if not auth_date:
                            logger.info(
                                f"User {email} in SEARCH_RESULTS but no auth_date set - will verify auth status"
                            )
                            # Need to verify auth status by backing out to library
                            self._verify_auth_from_search_results(email, profile_manager)

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
                    logger.debug("Download limit reached dialog detected within READING state")
                    # Don't override the state as it's correctly detected as READING already
                    return self.current_state

                # Double check for library elements
                library_elements_found = False
                logger.debug("State detected as READING - double checking for library elements...")

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
                                logger.debug(
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
                    logger.debug(f"Confirmed READING state with {reading_elements_count} strong indicators")

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
                    logger.warning(f"Error checking current activity: {e}", exc_info=True)

                # Store page source for debugging if still unknown
                source = self.driver.page_source
                store_page_source(source, "unknown_state")

                # Try to detect library state specifically
                if self.library_handler._is_library_tab_selected():
                    self.current_state = AppState.LIBRARY
                    logger.debug("Detected LIBRARY state from library handler")

                    # Set auth_date immediately when we detect LIBRARY state
                    try:
                        from datetime import datetime

                        profile_manager = self.driver.automator.profile_manager
                        profile = profile_manager.get_current_profile()
                        email = profile.get("email")

                        if email:
                            # User is authenticated
                            profile_manager.update_auth_state(email, authenticated=True)
                    except Exception as e:
                        logger.warning(f"Error setting auth_date during LIBRARY detection: {e}")

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
                                logger.debug("Detected READING state from 'Go to that location?' dialog")
                                break
                        except:
                            continue
                except Exception as e:
                    logger.warning(f"Error checking for reading state: {e}", exc_info=True)

            return self.current_state

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error updating current state: {e}", exc_info=True)
            self.current_state = AppState.UNKNOWN
            return self.current_state

    def check_initial_state_with_restart(self):
        """Check state at the beginning of specific requests and restart if UNKNOWN.

        This method should only be called at the start of /open-book, /navigate, and /books-stream requests.
        It will force restart the app if we're in an UNKNOWN state to ensure clean operation.

        Returns:
            AppState: The current state after checking (and potentially restarting)
        """
        # First update the state to get current status
        self.update_current_state()

        # If we're in UNKNOWN state, force restart the app
        if self.current_state == AppState.UNKNOWN:
            logger.info("Initial state is UNKNOWN - force restarting app for clean operation")

            # Force restart the app
            if self.view_inspector.ensure_app_foreground(force_restart=True):
                logger.info("Successfully restarted Kindle app, waiting for it to initialize...")
                time.sleep(2)  # Wait for app to fully initialize

                # Update state again after restart
                self.update_current_state()
                logger.info(f"After app restart, state is: {self.current_state}")

        return self.current_state

    def _verify_auth_from_search_results(self, email: str, profile_manager) -> None:
        """Verify authentication status when in search results without auth_date.

        This backs out from search results to library, refreshes, and checks auth status.
        """
        try:
            logger.debug(f"Verifying auth status for {email} from search results")

            # Back out from search results to library
            from appium.webdriver.common.appiumby import AppiumBy
            from selenium.common.exceptions import NoSuchElementException

            # Try to find and click the back button
            try:
                back_button = self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, "Navigate up")
                back_button.click()
                logger.info("Clicked back button to exit search results")
                time.sleep(1)
            except NoSuchElementException:
                logger.warning("Back button not found, trying alternative methods")
                # Try pressing device back button
                self.driver.back()
                time.sleep(1)

            # Update state to see where we are now
            self.update_current_state()

            if self.current_state == AppState.LIBRARY:
                # We're in library, now pull to refresh
                logger.info("Successfully in library view, performing pull to refresh")

                # Perform pull to refresh gesture
                screen_size = self.driver.get_window_size()
                start_x = screen_size["width"] // 2
                start_y = screen_size["height"] // 4
                end_y = screen_size["height"] // 2

                self.driver.swipe(start_x, start_y, start_x, end_y, duration=800)
                logger.debug("Performed pull to refresh gesture")
                time.sleep(0.5)  # Wait for refresh to complete

                # Update state again after refresh
                self.update_current_state()

                if self.current_state == AppState.LIBRARY:
                    # Still in library after refresh - user is authenticated
                    logger.debug(f"User {email} confirmed authenticated after refresh")
                    profile_manager.update_auth_state(email, authenticated=True)

                elif self.current_state == AppState.LIBRARY_SIGN_IN:
                    # After refresh, we're in sign-in state - user lost auth
                    logger.warning(f"User {email} lost authentication - in LIBRARY_SIGN_IN after refresh")
                    profile_manager.update_auth_state(email, authenticated=False)

            else:
                logger.warning(
                    f"Failed to navigate back to library from search results, current state: {self.current_state}"
                )

        except Exception as e:
            logger.warning(f"Error verifying auth from search results: {e}", exc_info=True)

    def handle_auth_state_detection(self, current_state, sindarin_email=None):
        """
        Handle detection of auth states by updating profile and returning appropriate response data.

        Args:
            current_state: The current AppState
            sindarin_email: Optional email, will be retrieved from profile if not provided

        Returns:
            dict: Response data with authentication info, or None if not an auth state
        """
        if not current_state.is_auth_state():
            return None

        # Get email if not provided
        if not sindarin_email:
            profile = self.driver.automator.profile_manager.get_current_profile()
            sindarin_email = profile.get("email") if profile else None
            if not sindarin_email:
                logger.warning("No email found for auth state detection")
                return None

        profile_manager = self.driver.automator.profile_manager
        auth_date = profile_manager.get_user_field(sindarin_email, "auth_date")

        # Update auth_failed_date if user was previously authenticated
        if auth_date and current_state in [AppState.SIGN_IN, AppState.LIBRARY_SIGN_IN]:
            logger.info(f"User {sindarin_email} lost authentication - was authenticated on {auth_date}")
            profile_manager.update_auth_state(sindarin_email, authenticated=False)

        # Get emulator ID
        emulator_id = None
        try:
            if hasattr(self.driver.automator, "emulator_manager"):
                emulator_id = self.driver.automator.emulator_manager.emulator_launcher.get_emulator_id(
                    sindarin_email
                )
        except Exception as e:
            logger.warning(f"Could not get emulator ID: {e}")

        # Build response based on whether user was previously authenticated
        if auth_date:
            return {
                "error": "Authentication token lost",
                "authenticated": False,
                "current_state": current_state.name,
                "message": "Your Kindle authentication token was lost. Authentication is required via VNC.",
                "emulator_id": emulator_id,
                "previous_auth_date": auth_date,
                "auth_token_lost": True,
            }
        else:
            return {
                "error": "Authentication required",
                "authenticated": False,
                "current_state": current_state.name,
                "message": "Authentication is required via VNC",
                "emulator_id": emulator_id,
            }
