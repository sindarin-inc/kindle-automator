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
from server.utils.screenshot_utils import take_adb_screenshot, take_secure_screenshot
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
from views.common.dialog_strategies import (
    APP_NOT_RESPONDING_DIALOG_IDENTIFIERS,
    DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
)
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
    ITEM_REMOVED_DIALOG_CLOSE_BUTTON,
    ITEM_REMOVED_DIALOG_IDENTIFIERS,
    LAST_READ_PAGE_DIALOG_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
    is_item_removed_dialog_visible,
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

                    if device_count > 1:
                        logger.error(
                            f"Multiple devices detected ({device_count}) but no device ID available - cannot proceed with app launch"
                        )
                        return False
                    elif device_count == 1:
                        # If only one device is available, use it
                        device_id = available_devices[0]
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
            start_time = time.time()
            max_wait_time = 10  # 10 seconds max wait time
            poll_interval = 0.2  # 200ms between checks
            app_ready = False

            while time.time() - start_time < max_wait_time:
                try:
                    current_activity = self.driver.current_activity

                    # Check for both com.amazon.kindle and com.amazon.kcp activities (both are valid Kindle activities)
                    # Also handle the Google Play review dialog which can appear over the Kindle app
                    # Also recognize the RemoteLicenseReleaseActivity (Download Limit dialog) as a valid activity
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
                except Exception as e:
                    logger.warning(f"Error checking current activity: {e}")
                    # If session is terminated, stop the loop early
                    if "A session is either terminated or not started" in str(e):
                        logger.error("Session terminated, stopping app status check")
                        break

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
                result = True
        except NoSuchElementException:
            # Only try additional strategies if the primary one fails
            for strategy in get_tab_selection_strategies(tab_name):
                try:
                    by, value = strategy
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
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

            # Check for download limit reached dialog
            # This can happen when trying to open a book with RemoteLicenseReleaseActivity
            download_limit_elements = 0
            for strategy, locator in DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        download_limit_elements += 1
                        logger.info(f"   Found download limit dialog element: {strategy}={locator}")
                except NoSuchElementException:
                    continue

            # Also check for specific activity name
            try:
                current_activity = self.driver.current_activity
                if "RemoteLicenseReleaseActivity" in current_activity:
                    download_limit_elements += 1
                    logger.info(f"   Found RemoteLicenseReleaseActivity: {current_activity}")
            except Exception as e:
                logger.debug(f"   Error checking current activity: {e}")

            # If we found at least 2 elements of the download limit dialog, we're confident
            if download_limit_elements >= 2:
                logger.info("   Download limit reached dialog detected")
                # Store page source for debugging
                store_page_source(self.driver.page_source, "download_limit_dialog")

                # Set this as reading state with a dialog, since it's related to book opening
                logger.info("   Treating download limit dialog as part of reading state")
                return AppView.READING

            # Check for Item Removed dialog which is a specific reading state dialog
            if is_item_removed_dialog_visible(self.driver):
                logger.info("   Found Item Removed dialog - treating as reading view")
                # Store page source for debugging
                store_page_source(self.driver.page_source, "item_removed_dialog")
                return AppView.READING

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

            # Check if we're in search results interface (which is separate from library)
            if self._is_in_search_interface():
                logger.info("   Detected search results interface, treating as SEARCH_RESULTS view")
                return AppView.SEARCH_RESULTS

            # First check the more accurate tab selection because library_root_view exists for both tabs
            if self._is_tab_selected("LIBRARY"):
                logger.info("   LIBRARY tab is selected, confirming we are in library view")
                # Cache this view detection
                self._current_view_cache_time = time.time()
                self._current_view_cache = AppView.LIBRARY

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
                        store_page_source(self.driver.page_source, "library_direct_element_detected")
                        return AppView.LIBRARY
                except NoSuchElementException:
                    pass

            if self._is_tab_selected("LIBRARY"):
                logger.info("Detected LIBRARY view")
                return AppView.LIBRARY

            # Check for view options menu (part of library view)
            if self._is_view_options_menu_open():
                logger.info("   Found view options menu - this is part of library view")
                return AppView.LIBRARY

            # Check for Grid/List view dialog (part of library view)
            if self._is_grid_list_view_dialog_open():
                logger.info("   Found Grid/List view dialog - this is part of library view")
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

                # Try to use secure screenshot method if we have device_id
                success = False
                if hasattr(self, "automator") and self.automator and hasattr(self.automator, "device_id"):
                    device_id = self.automator.device_id
                    logger.info("Attempting secure screenshot for unknown view...")
                    # Get current state if available
                    current_state = None
                    if hasattr(self.automator, "state_machine") and self.automator.state_machine:
                        current_state = self.automator.state_machine.current_state
                    secure_path = take_secure_screenshot(
                        device_id=device_id, output_path=screenshot_path, current_state=current_state
                    )
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

                # Try to use secure screenshot method if we have device_id
                success = False
                if hasattr(self, "automator") and self.automator and hasattr(self.automator, "device_id"):
                    device_id = self.automator.device_id
                    logger.info("Attempting secure screenshot for error view...")
                    # Get current state if available
                    current_state = None
                    if hasattr(self.automator, "state_machine") and self.automator.state_machine:
                        current_state = self.automator.state_machine.current_state
                    secure_path = take_secure_screenshot(
                        device_id=device_id, output_path=screenshot_path, current_state=current_state
                    )
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

    def _focus_input_field_if_needed(self, field_element, field_type="input"):
        """Helper method to focus an input field only if it doesn't already have focus.

        Args:
            field_element: The UI element to focus if needed
            field_type: String description of field type (e.g., "email", "password")

        Returns:
            Boolean indicating whether the element was successfully focused
        """
        try:
            # Check if the element already has focus
            has_focus = False
            try:
                focused_element = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.EditText[@focused='true']"
                )
                if focused_element and focused_element.get_attribute(
                    "resource-id"
                ) == field_element.get_attribute("resource-id"):
                    logger.info(f"   {field_type.capitalize()} field already has focus, no need to tap")
                    has_focus = True

                    # Hide the keyboard if it's visible
                    try:
                        self.driver.hide_keyboard()
                        logger.info(f"   Successfully hid keyboard for already focused {field_type} field")
                    except Exception as hide_err:
                        logger.warning(
                            f"   Could not hide keyboard for already focused {field_type} field: {hide_err}"
                        )
            except NoSuchElementException:
                # No focused element found, we'll need to tap
                pass
            except Exception as focus_err:
                logger.warning(f"   Error checking if {field_type} field has focus: {focus_err}")

            # Only tap if the field doesn't already have focus
            if not has_focus:
                try:
                    logger.info(f"   Tapping {field_type} field to focus it")
                    field_element.click()

                    # Hide the keyboard after tapping
                    try:
                        self.driver.hide_keyboard()
                        logger.info(f"   Successfully hid keyboard after focusing {field_type} field")
                    except Exception as hide_err:
                        logger.warning(
                            f"   Could not hide keyboard after focusing {field_type} field: {hide_err}"
                        )
                except Exception as tap_err:
                    logger.warning(f"   Error tapping {field_type} field: {tap_err}")
                    return False

            return True

        except Exception as e:
            logger.error(f"   Error in _focus_input_field_if_needed for {field_type} field: {e}")
            return False

    def _is_auth_view(self):
        """Check if we're on any authentication-related view."""
        try:
            # Check for email input field
            for strategy in EMAIL_FIELD_STRATEGIES:
                try:
                    element = self.driver.find_element(*strategy)
                    if element:
                        logger.info("   Found email input field - on auth view")
                        self._focus_input_field_if_needed(element, "email")
                        return True
                except NoSuchElementException:
                    continue

            # Check for password input field
            for strategy in PASSWORD_FIELD_STRATEGIES:
                try:
                    element = self.driver.find_element(*strategy)
                    if element:
                        logger.info("   Found password input field - on auth view")
                        self._focus_input_field_if_needed(element, "password")
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

    def _is_in_search_interface(self):
        """
        Check if we're currently in the search results interface.
        This can be misidentified as the library view because it uses some of the same elements.

        Search results view is identified by the presence of "In your library" and "Results from Kindle" sections.
        """
        try:
            # Check for search-specific elements
            search_indicators = 0

            # Check for search query input field
            try:
                search_query = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
                if search_query and search_query.is_displayed():
                    search_indicators += 1
                    logger.info("Found search query input field")
            except NoSuchElementException:
                pass

            # Check for search recycler view
            try:
                search_results = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/search_recycler_view"
                )
                if search_results and search_results.is_displayed():
                    search_indicators += 1
                    logger.info("Found search results recycler view")
            except NoSuchElementException:
                pass

            # Check for "Navigate up" button which is present in search view
            try:
                up_button = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Navigate up']"
                )
                if up_button and up_button.is_displayed():
                    search_indicators += 1
                    logger.info("Found Navigate up button in search view")
            except NoSuchElementException:
                pass

            # Check for "In your library" section header - a key indicator of search results
            try:
                in_library_header = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='In your library']"
                )
                if in_library_header and in_library_header.is_displayed():
                    search_indicators += 2  # Strong indicator, count as 2
                    logger.info("Found 'In your library' section header in search results")
            except NoSuchElementException:
                try:
                    # Alternative way to find the header by text
                    in_library_text = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[@text='In your library']"
                    )
                    if in_library_text and in_library_text.is_displayed():
                        search_indicators += 2  # Strong indicator, count as 2
                        logger.info("Found 'In your library' text in search results")
                except NoSuchElementException:
                    pass

            # Check for "Results from Kindle" section header - another key indicator
            try:
                store_results_header = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='Results from Kindle']"
                )
                if store_results_header and store_results_header.is_displayed():
                    search_indicators += 2  # Strong indicator, count as 2
                    logger.info("Found 'Results from Kindle' section header in search results")
            except NoSuchElementException:
                try:
                    # Alternative way to find the header by text
                    store_results_text = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[@text='Results from Kindle']"
                    )
                    if store_results_text and store_results_text.is_displayed():
                        search_indicators += 2  # Strong indicator, count as 2
                        logger.info("Found 'Results from Kindle' text in search results")
                except NoSuchElementException:
                    pass

            # We need at least 2 indicators to be confident we're in search view
            is_search = search_indicators >= 2
            if is_search:
                logger.info(f"Detected search interface with {search_indicators} indicators")
            return is_search

        except Exception as e:
            logger.error(f"Error checking for search interface: {e}")
            return False
