import logging
import os
import re
import subprocess
import time
import traceback

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from server.logging_config import store_page_source
from server.utils.request_utils import get_sindarin_email
from views.auth.interaction_strategies import (
    EMAIL_FIELD_STRATEGIES,
    PASSWORD_FIELD_STRATEGIES,
    SIGN_IN_RADIO_BUTTON_STRATEGIES,
)
from views.auth.view_strategies import (
    AUTH_RESTART_MESSAGES,
    CAPTCHA_REQUIRED_INDICATORS,
    EMAIL_VIEW_IDENTIFIERS,
    PASSWORD_VIEW_IDENTIFIERS,
)
from views.common.dialog_strategies import APP_NOT_RESPONDING_DIALOG_IDENTIFIERS
from views.core.app_state import AppState, AppView
from views.core.tab_strategies import get_tab_selection_strategies
from views.home.view_strategies import HOME_TAB_IDENTIFIERS, HOME_VIEW_IDENTIFIERS
from views.library.view_strategies import (
    EMPTY_LIBRARY_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_STRATEGIES,
    LIBRARY_VIEW_DETECTION_STRATEGIES,
    LIBRARY_VIEW_IDENTIFIERS,
)
from views.notifications.view_strategies import NOTIFICATION_DIALOG_IDENTIFIERS
from views.reading.interaction_strategies import ABOUT_BOOK_SLIDEOVER_IDENTIFIERS
from views.reading.view_strategies import (
    GO_TO_LOCATION_DIALOG_IDENTIFIERS,
    GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS,
    LAST_READ_PAGE_DIALOG_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
)
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES

logger = logging.getLogger(__name__)


class ViewInspector:
    def __init__(self, driver):
        self.driver = driver
        logger.info(f"ViewInspector initialized with driver: {self.driver}")
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.app_package = "com.amazon.kindle"
        self.app_activity = "com.amazon.kindle.UpgradePage"
        # Initialize device_id to None - will be set properly later
        self.automator = self.driver.automator

    def ensure_app_foreground(self):
        """Ensures the Kindle app is in the foreground"""
        try:
            # Get device ID through multiple methods to ensure we have one
            # Get the emulator ID for this email if possible
            sindarin_email = get_sindarin_email()
            device_id = self.automator.emulator_manager.emulator_launcher.get_emulator_id(sindarin_email)

            logger.info(f"Bringing {self.app_package} to foreground using device_id={device_id}...")

            # Check if we have a device ID and if multiple devices exist
            if not device_id:
                logger.warning("No device ID available, checking if we have multiple devices running")
                # Try to check how many devices are running and possibly identify one
                try:
                    adb_result = subprocess.run(
                        ["adb", "devices"],
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    # Count devices and try to get a single device if possible
                    device_count = 0
                    available_devices = []

                    for line in adb_result.stdout.splitlines():
                        if "device" in line and not "List of devices" in line:
                            parts = line.split()
                            if len(parts) >= 1:
                                device_id_candidate = parts[0].strip()
                                if device_id_candidate:
                                    device_count += 1
                                    available_devices.append(device_id_candidate)

                    logger.info(f"Found {device_count} devices: {available_devices}")

                    if device_count > 1:
                        logger.error(
                            f"Multiple devices detected ({device_count}) but no device ID available - cannot proceed with app launch"
                        )
                        return False
                    elif device_count == 1:
                        # If only one device is available, use it
                        device_id = available_devices[0]
                        logger.info(f"Using the only available device: {device_id}")
                except Exception as e:
                    logger.warning(f"Error checking for devices: {e}")

            # One more check - if we still don't have a device ID but stderr contains "more than one"
            if not device_id:
                logger.error("Still no device ID and multiple emulators may be running - cannot proceed")
                return False

            # Build the ADB command based on whether we have a device ID
            cmd = ["adb"]
            if device_id:
                cmd.extend(["-s", device_id])
            cmd.extend(["shell", f"am start -n {self.app_package}/{self.app_activity}"])
            logger.info(f"Running command: {cmd}")
            # Run the command but don't check for errors - sometimes the exit code is 1
            # even when the app launches successfully
            result = subprocess.run(
                cmd,
                check=False,  # Changed from True to False to avoid exceptions on non-zero exit
                capture_output=True,
                text=True,
            )

            # Log but don't fail on non-zero exit code
            if result.returncode != 0:
                logger.warning(f"App launch command returned non-zero: {result.returncode}")
                logger.warning(f"Stdout: {result.stdout.strip()}")
                logger.warning(f"Stderr: {result.stderr.strip()}")

            # Wait for the app to initialize with polling instead of fixed sleep
            logger.info("Waiting for Kindle app to initialize (max 4 seconds)...")
            start_time = time.time()
            max_wait_time = 10  # 10 seconds max wait time
            poll_interval = 0.2  # 200ms between checks
            app_ready = False

            while time.time() - start_time < max_wait_time:
                try:
                    current_activity = self.driver.current_activity
                    logger.info(f"Current activity is: {self.driver} {current_activity}")

                    # Check for both com.amazon.kindle and com.amazon.kcp activities (both are valid Kindle activities)
                    # Also handle the Google Play review dialog which can appear over the Kindle app
                    if (
                        current_activity.startswith("com.amazon")
                        or current_activity
                        == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
                    ):
                        logger.info(
                            f"Successfully verified Kindle app is in foreground after {time.time() - start_time:.2f}s: {current_activity}"
                        )
                        app_ready = True

                        # Try to dismiss the Google Play review dialog if it's showing
                        if (
                            current_activity
                            == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
                        ):
                            logger.info("Attempting to dismiss Google Play review dialog...")
                            try:
                                # Method 1: Press back button
                                self.driver.press_keycode(4)  # Android back key
                                time.sleep(1)

                                # Method 2: Try to find and click close/cancel buttons
                                for button_text in ["Close", "Cancel", "Not now", "Later", "No thanks"]:
                                    try:
                                        buttons = self.driver.find_elements(
                                            AppiumBy.XPATH,
                                            f"//android.widget.Button[contains(@text, '{button_text}')]",
                                        )
                                        if buttons:
                                            buttons[0].click()
                                            logger.info(f"Clicked '{button_text}' button to dismiss dialog")
                                            time.sleep(1)
                                            break
                                    except Exception as button_e:
                                        logger.debug(
                                            f"Could not find button with text '{button_text}': {button_e}"
                                        )
                            except Exception as dismiss_e:
                                logger.warning(f"Failed to dismiss review dialog: {dismiss_e}")
                        break
                    else:
                        logger.info(
                            f"App not ready yet - current activity is: {current_activity}, polling again in {poll_interval}s"
                        )
                except Exception as e:
                    logger.warning(f"Error checking current activity: {e}")

                # Sleep for poll_interval before checking again
                time.sleep(poll_interval)

            if not app_ready:
                logger.warning(f"Timed out waiting for app to initialize after {max_wait_time}s")

            logger.info("App brought to foreground")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error bringing app to foreground: {e}")
            return False

    def _is_tab_selected(self, tab_name):
        """Check if a specific tab is currently selected."""
        logger.info(f"   Checking if {tab_name} tab is selected...")

        # Check for cached tab selection to avoid redundant checks
        cache_key = f"{tab_name}_tab_selected"
        if hasattr(self, "_tab_check_time") and hasattr(self, cache_key):
            # Use cached result if it's less than 0.5 seconds old
            time_since_check = time.time() - self._tab_check_time.get(tab_name, 0)
            if time_since_check < 0.5:
                cached_result = getattr(self, cache_key)
                logger.info(
                    f"   Using cached {tab_name} tab selection from {time_since_check:.2f}s ago: {cached_result}"
                )
                return cached_result

        # Try the most reliable tab selection strategy first (second strategy in the list)
        result = False
        try:
            by, value = (
                AppiumBy.XPATH,
                f"//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/{tab_name.lower()}_tab']//android.widget.TextView[@selected='true']",
            )
            element = self.driver.find_element(by, value)
            if element.is_displayed():
                logger.info(f"   Found {tab_name} tab with strategy: {by}, value: {value}")
                result = True
        except NoSuchElementException:
            # Only try additional strategies if the primary one fails
            for strategy in get_tab_selection_strategies(tab_name):
                try:
                    by, value = strategy
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
                        logger.info(f"   Found {tab_name} tab with strategy: {by}, value: {value}")
                        result = True
                        break
                except NoSuchElementException:
                    continue

        # Cache the result
        if not hasattr(self, "_tab_check_time"):
            self._tab_check_time = {}
        self._tab_check_time[tab_name] = time.time()
        setattr(self, cache_key, result)

        return result

    def _dump_page_source(self):
        """Dump the page source for debugging"""
        try:
            source = self.driver.page_source

            # Store the page source
            filepath = store_page_source(source, "unknown_view")
            logger.info(f"Stored unknown view page source at: {filepath}")
        except Exception as e:
            logger.error(f"Failed to get page source: {e.__class__.__name__}")

    def _try_find_element(self, strategies, success_message=None):
        """Try to find an element using multiple strategies"""
        for strategy in strategies:
            try:
                element = self.driver.find_element(strategy[0], strategy[1])
                if success_message:
                    logger.info(success_message)
                return element
            except:
                continue
        return None

    def _is_view_options_menu_open(self):
        """Check if the view options menu is currently open."""
        try:
            for strategy, locator in VIEW_OPTIONS_MENU_STATE_STRATEGIES:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"View options menu detected via {strategy}: {locator}")
                    return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Error checking view options menu state: {e}")
            return False

    def _is_grid_list_view_dialog_open(self):
        """Check if the Grid/List view selection dialog is open.

        This dialog appears when view options is clicked and shows Grid, List, and Collections choices.
        """
        try:
            # Import these locally to avoid circular imports
            from views.library.interaction_strategies import (
                GRID_VIEW_OPTION_STRATEGIES,
                LIST_VIEW_OPTION_STRATEGIES,
            )
            from views.library.view_strategies import VIEW_OPTIONS_MENU_STRATEGIES

            # Check for multiple identifiers to ensure we're specifically in the Grid/List dialog
            identifiers_found = 0

            # Check for VIEW_OPTIONS_MENU_STRATEGIES (DONE button)
            for strategy, locator in VIEW_OPTIONS_MENU_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.debug(f"Grid/List dialog element found: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue

            # Check for LIST_VIEW_OPTION_STRATEGIES
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.debug(f"List view option found: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue

            # Check for GRID_VIEW_OPTION_STRATEGIES
            for strategy, locator in GRID_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.debug(f"Grid view option found: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue

            # Also check for specific view type header text
            try:
                header = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/view_type_header")
                if header.is_displayed() and header.text == "View":
                    logger.debug("View type header found with text 'View'")
                    identifiers_found += 1
            except NoSuchElementException:
                pass

            # If we found at least 2 of the identifying elements, we're confident it's the Grid/List dialog
            return identifiers_found >= 2
        except Exception as e:
            logger.debug(f"Error checking for Grid/List view dialog: {e}")
            return False

    def get_current_view(self):
        """Determine the current view based on visible elements."""
        try:
            logger.info("Determining current view...")

            # Check for HOME tab first as it's the most common state
            # This helps avoid all the other expensive checks for common cases
            try:
                # Check if we have a cached current view (valid for 1 second)
                if hasattr(self, "_current_view_cache_time") and hasattr(self, "_current_view_cache"):
                    time_since_check = time.time() - self._current_view_cache_time
                    if time_since_check < 1.0:
                        cached_view = self._current_view_cache
                        logger.info(f"Using cached view from {time_since_check:.2f}s ago: {cached_view}")
                        return cached_view

                # Check for HOME tab first since it's the most common state
                if self._is_tab_selected("HOME"):
                    logger.info("Found HOME tab selected, immediately returning HOME view")
                    # Cache this view detection
                    self._current_view_cache_time = time.time()
                    self._current_view_cache = AppView.HOME
                    return AppView.HOME
            except Exception as e:
                logger.warning(f"Error during early HOME tab check: {e}")

            # Check for app not responding dialog first
            app_not_responding_elements = 0
            for strategy, locator in APP_NOT_RESPONDING_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        app_not_responding_elements += 1
                        logger.info(f"   Found app not responding element: {strategy}={locator}")
                except NoSuchElementException:
                    continue

            # If we found at least 2 elements of the app not responding dialog, we're confident
            if app_not_responding_elements >= 2:
                logger.info("   App not responding dialog detected")
                # Store page source for debugging
                store_page_source(self.driver.page_source, "app_not_responding")

                # Cache this view detection
                self._current_view_cache_time = time.time()
                self._current_view_cache = AppView.APP_NOT_RESPONDING
                return AppView.APP_NOT_RESPONDING

            # Check for reading view identifiers
            reading_view_elements_found = 0
            for strategy, locator in READING_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        reading_view_elements_found += 1
                        logger.info(f"   Found reading view element: {strategy}={locator}")
                except NoSuchElementException:
                    continue

            # Check for "About this book slideover" which indicates reading view with a slideover
            for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"   Found 'About this book slideover' element: {strategy}={locator}")
                        logger.info(
                            "   This indicates we're in reading view with the about book slideover open"
                        )
                        # Save page source for debugging
                        store_page_source(self.driver.page_source, "about_book_slideover_detected")
                        reading_view_elements_found += 1
                except NoSuchElementException:
                    continue

            # If we found multiple reading view elements, we're definitely in reading view
            if reading_view_elements_found >= 2:
                logger.info(
                    f"   Found {reading_view_elements_found} reading view elements - confidently in reading view"
                )
                # Save page source for debugging
                store_page_source(self.driver.page_source, "reading_view_detected")
                return AppView.READING

            # Also check for full screen dialog which indicates reading view
            for strategy, locator in READING_VIEW_FULL_SCREEN_DIALOG:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info("   Found reading view full screen dialog")
                    return AppView.READING
                except NoSuchElementException:
                    continue

            # Check for "Go to that location?" dialog which indicates reading view
            for strategy, locator in GO_TO_LOCATION_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed() and "Go to that location?" in element.text:
                        logger.info("   Found 'Go to that location?' dialog - this indicates reading view")
                        return AppView.READING
                except NoSuchElementException:
                    continue

            # Check for "last read page" dialog which indicates reading view
            for strategy, locator in LAST_READ_PAGE_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        text = element.text
                        if ("You are currently on page" in text) or ("You are currently at location" in text):
                            logger.info(
                                "   Found 'last read page/location' dialog - this indicates reading view"
                            )
                            return AppView.READING
                except NoSuchElementException:
                    continue

            # Check for "Auto-update on Goodreads" dialog which indicates reading view
            for strategy, locator in GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed() and "Auto-update on Goodreads" in element.text:
                        logger.info(
                            "   Found 'Auto-update on Goodreads' dialog - this indicates reading view"
                        )
                        return AppView.READING
                except NoSuchElementException:
                    continue

            # Also check for Goodreads dialog buttons directly
            try:
                # Use strategy from GOODREADS_NOT_NOW_BUTTON
                from views.reading.view_strategies import GOODREADS_NOT_NOW_BUTTON

                not_now_button = self.driver.find_element(*GOODREADS_NOT_NOW_BUTTON)

                if not_now_button.is_displayed():
                    logger.info(
                        "   Found 'NOT NOW' button for Goodreads dialog - this indicates reading view"
                    )
                    return AppView.READING
            except NoSuchElementException:
                pass

            # Check for auth-related views first
            if self._is_auth_view():
                # Store auth page source for debugging
                logger.info("   Found auth view - storing page source for debugging")
                source = self.driver.page_source
                store_page_source(source, "auth_view")
                return AppView.SIGN_IN

            # Check for notification permission dialog first
            if self._try_find_element(
                NOTIFICATION_DIALOG_IDENTIFIERS, "   Found notification permission dialog"
            ):
                logger.info("   Found notification permission dialog")
                return AppView.NOTIFICATION_PERMISSION

            # Check for captcha screen
            indicators_found = 0
            for strategy, locator in CAPTCHA_REQUIRED_INDICATORS:
                try:
                    self.driver.find_element(strategy, locator)
                    indicators_found += 1
                except:
                    continue
            if indicators_found >= 3:
                logger.info("   Found captcha screen")

                # Try to find and tap the captcha input field
                try:
                    captcha_input = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.EditText[not(@password)]"
                    )
                    if captcha_input:
                        logger.info("   Tapping captcha input field to focus it")
                        captcha_input.click()

                        # Hide the keyboard after tapping
                        try:
                            self.driver.hide_keyboard()
                            logger.info("   Successfully hid keyboard after focusing captcha field")
                        except Exception as hide_err:
                            logger.warning(
                                f"   Could not hide keyboard after focusing captcha field: {hide_err}"
                            )
                except Exception as tap_err:
                    logger.warning(f"   Error tapping captcha input field: {tap_err}")

                return AppView.CAPTCHA

            # Check for empty library with sign-in button first
            logger.info("   Checking for empty library with sign-in button...")
            # Try the predefined identifiers
            if self._try_find_element(
                EMPTY_LIBRARY_IDENTIFIERS, "   Found empty library with sign-in button"
            ):
                logger.info("   Found empty library with sign-in button")
                return AppView.LIBRARY_SIGN_IN

            # Also check for more specific identifiers from XML
            try:
                # Check for empty library logged out container
                container_strategy = EMPTY_LIBRARY_IDENTIFIERS[3]  # Using the empty_library_logged_out ID
                container = self.driver.find_element(*container_strategy)
                if container.is_displayed():
                    logger.info("   Found empty library logged out container")
                    # Try to find sign-in button within it
                    try:
                        button_strategy = EMPTY_LIBRARY_IDENTIFIERS[4]  # Using the empty_library_sign_in ID
                        button = self.driver.find_element(*button_strategy)
                        if button.is_displayed():
                            logger.info("   Found sign-in button by ID")
                            return AppView.LIBRARY_SIGN_IN
                    except NoSuchElementException:
                        # Just check for text "It's a little empty here…" which suggests need to sign in
                        try:
                            from views.library.view_strategies import (
                                EMPTY_LIBRARY_TEXT_INDICATORS,
                            )

                            for strategy, locator in EMPTY_LIBRARY_TEXT_INDICATORS:
                                try:
                                    text = self.driver.find_element(strategy, locator)
                                    if text.is_displayed():
                                        logger.info(f"   Found '{text.text}' text suggesting sign-in needed")
                                        return AppView.LIBRARY_SIGN_IN
                                except NoSuchElementException:
                                    continue
                        except Exception as e:
                            logger.debug(f"Error checking for empty library text: {e}")
                            pass
            except NoSuchElementException:
                pass

            # Check for library view indicators
            logger.info("   Checking for library view indicators...")
            has_library_root = False
            has_library_tab = False

            # Directly check for specific library elements
            logger.info("   Directly checking for library view elements...")
            found_library_element = False

            # First check the more accurate tab selection because library_root_view exists for both tabs
            if self._is_tab_selected("LIBRARY"):
                logger.info("   LIBRARY tab is selected, confirming we are in library view")
                # Cache this view detection
                self._current_view_cache_time = time.time()
                self._current_view_cache = AppView.LIBRARY

                # Only store page source in debug mode to reduce I/O
                if logger.isEnabledFor(logging.DEBUG):
                    filepath = store_page_source(self.driver.page_source, "library_tab_selected")
                    logger.debug(f"Stored page source with library tab selected at: {filepath}")
                return AppView.LIBRARY

            # If LIBRARY tab is not selected, check if HOME tab is selected
            if self._is_tab_selected("HOME"):
                logger.info("   HOME tab is selected, we are in home view not library view")
                # Cache this view detection
                self._current_view_cache_time = time.time()
                self._current_view_cache = AppView.HOME
                # If HOME tab is selected, we're confident we're in HOME view - return immediately
                return AppView.HOME

            # Final fallback: check specific elements if tab detection wasn't conclusive
            for strategy, locator in LIBRARY_VIEW_DETECTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    # We need more checks for library_root_view since it's present in both home and library
                    if "library_root_view" in locator:
                        # Only accept if the LIBRARY tab is selected
                        if not self._is_tab_selected("LIBRARY"):
                            continue

                    if element.is_displayed():
                        logger.info(f"   Found library view element: {strategy}={locator}")
                        filepath = store_page_source(
                            self.driver.page_source, "library_direct_element_detected"
                        )
                        logger.info(f"Stored page source with library element detected at: {filepath}")
                        logger.info("Detected LIBRARY view based on direct element detection")
                        return AppView.LIBRARY
                except NoSuchElementException:
                    pass

            if self._is_tab_selected("LIBRARY"):
                logger.info("Detected LIBRARY view")
                # Save page source for debugging
                store_page_source(self.driver.page_source, "library_view_detected")
                return AppView.LIBRARY

            # Check for view options menu (part of library view)
            if self._is_view_options_menu_open():
                logger.info("   Found view options menu - this is part of library view")
                return AppView.LIBRARY

            # Check for Grid/List view dialog (part of library view)
            if self._is_grid_list_view_dialog_open():
                logger.info("   Found Grid/List view dialog - this is part of library view")
                # Store page source for debugging
                store_page_source(self.driver.page_source, "grid_list_dialog_detected")
                return AppView.LIBRARY

            # Check tab selection for HOME view
            logger.info("   Checking tab selection...")
            if self._is_tab_selected("HOME"):
                logger.info("HOME tab is selected")
                return AppView.HOME

            # Check for password view
            logger.info("   Checking for password view...")
            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"   Found password view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN_PASSWORD
                except NoSuchElementException:
                    continue

            # Check for sign in view
            logger.info("   Checking for sign in view...")
            for strategy, locator in EMAIL_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    logger.info(f"   Found sign in view element: {element.get_attribute('text')}")
                    return AppView.SIGN_IN
                except NoSuchElementException:
                    continue

            # Check for general app indicators
            logger.info("   Checking for general app indicators...")
            if self._try_find_element(
                LIBRARY_VIEW_IDENTIFIERS,
                "   Found library root view - in app but can't determine exact view",
            ):
                return AppView.UNKNOWN

            # If we get here, we couldn't determine the view
            logger.warning("Could not determine current view - dumping page source for debugging")
            self._dump_page_source()

            # Also save a screenshot for visual debugging
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "unknown_view.png")

                # Try to use secure screenshot method if we have automator reference
                success = False
                if self.automator and hasattr(self.automator, "take_secure_screenshot"):
                    logger.info("Attempting secure screenshot for unknown view...")
                    secure_path = self.automator.take_secure_screenshot(screenshot_path)
                    if secure_path:
                        logger.info(f"Saved secure screenshot of unknown view to {secure_path}")
                        success = True
                    else:
                        logger.warning("Secure screenshot failed, falling back to standard method")

                # Fall back to standard method if secure screenshot failed or not available
                if not success:
                    self.driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot of unknown view to {screenshot_path}")
            except Exception as e:
                logger.warning(f"Failed to save screenshot: {str(e)[:100]}")

            logger.debug("Not in main app view")
            return AppView.UNKNOWN

        except Exception as e:
            logger.error(f"Error determining current view: {e}")
            logger.warning("Dumping page source due to error")
            traceback.print_exc()
            self._dump_page_source()
            try:
                screenshot_path = os.path.join(self.screenshots_dir, "error_view.png")

                # Try to use secure screenshot method if we have automator reference
                success = False
                if self.automator and hasattr(self.automator, "take_secure_screenshot"):
                    logger.info("Attempting secure screenshot for error view...")
                    secure_path = self.automator.take_secure_screenshot(screenshot_path)
                    if secure_path:
                        logger.info(f"Saved secure screenshot of error view to {secure_path}")
                        success = True
                    else:
                        logger.warning("Secure screenshot failed, falling back to standard method")

                # Fall back to standard method if secure screenshot failed or not available
                if not success:
                    self.driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot of error state to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save error screenshot: {screenshot_error}")
            return AppView.UNKNOWN

    def _is_auth_view(self):
        """Check if we're on any authentication-related view."""
        try:
            # Check for email input field
            for strategy in EMAIL_FIELD_STRATEGIES:
                try:
                    element = self.driver.find_element(*strategy)
                    if element:
                        logger.info("   Found email input field - on auth view")

                        # Tap on the email field and hide keyboard
                        try:
                            logger.info("   Tapping email field to focus it")
                            element.click()

                            # Hide the keyboard after tapping
                            try:
                                self.driver.hide_keyboard()
                                logger.info("   Successfully hid keyboard after focusing email field")
                            except Exception as hide_err:
                                logger.warning(
                                    f"   Could not hide keyboard after focusing email field: {hide_err}"
                                )
                        except Exception as tap_err:
                            logger.warning(f"   Error tapping email field: {tap_err}")

                        return True
                except NoSuchElementException:
                    continue

            # Check for password input field
            for strategy in PASSWORD_FIELD_STRATEGIES:
                try:
                    element = self.driver.find_element(*strategy)
                    if element:
                        logger.info("   Found password input field - on auth view")

                        # Tap on the password field and hide keyboard
                        try:
                            logger.info("   Tapping password field to focus it")
                            element.click()

                            # Hide the keyboard after tapping
                            try:
                                self.driver.hide_keyboard()
                                logger.info("   Successfully hid keyboard after focusing password field")
                            except Exception as hide_err:
                                logger.warning(
                                    f"   Could not hide keyboard after focusing password field: {hide_err}"
                                )
                        except Exception as tap_err:
                            logger.warning(f"   Error tapping password field: {tap_err}")

                        return True
                except NoSuchElementException:
                    continue

            # Check for sign-in button
            for strategy in SIGN_IN_RADIO_BUTTON_STRATEGIES:
                try:
                    if self.driver.find_element(*strategy):
                        logger.info("   Found sign-in radio button - on auth view")
                        return True
                except NoSuchElementException:
                    continue

            return False

        except Exception as e:
            logger.error(f"Error checking for auth view: {e}")
            return False
