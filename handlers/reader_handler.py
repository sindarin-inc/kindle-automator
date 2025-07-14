import logging
import os
import re
import subprocess
import time
from io import BytesIO

from appium.webdriver.common.appiumby import AppiumBy
from PIL import Image
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from server.logging_config import store_page_source
from server.utils.request_utils import get_sindarin_email
from server.utils.screenshot_utils import take_adb_screenshot
from views.reading.interaction_strategies import (
    ABOUT_BOOK_SLIDEOVER_IDENTIFIERS,
    BOTTOM_SHEET_IDENTIFIERS,
    CLOSE_BOOK_STRATEGIES,
    COMIC_BOOK_NEXT_BUTTON,
    COMIC_BOOK_X_BUTTON,
    DOWNLOAD_LIMIT_CHECKEDTEXTVIEW,
    DOWNLOAD_LIMIT_DEVICE_LIST,
    DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
    DOWNLOAD_LIMIT_ERROR_TEXT,
    DOWNLOAD_LIMIT_FIRST_DEVICE,
    DOWNLOAD_LIMIT_REMOVE_BUTTON,
    FULL_SCREEN_DIALOG_GOT_IT,
    LAST_READ_PAGE_DIALOG_BUTTONS,
    READING_TOOLBAR_STRATEGIES,
    WORD_WISE_DIALOG_IDENTIFIERS,
    WORD_WISE_NO_THANKS_BUTTON,
    handle_item_removed_dialog,
)
from views.reading.view_strategies import (
    BLACK_BG_IDENTIFIERS,
    COMIC_BOOK_VIEW_IDENTIFIERS,
    GO_TO_LOCATION_DIALOG_IDENTIFIERS,
    GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS,
    GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS,
    ITEM_REMOVED_DIALOG_CLOSE_BUTTON,
    ITEM_REMOVED_DIALOG_IDENTIFIERS,
    LAST_READ_PAGE_DIALOG_IDENTIFIERS,
    LAYOUT_TAB_IDENTIFIERS,
    PAGE_NAVIGATION_ZONES,
    PAGE_NUMBER_IDENTIFIERS,
    PLACEMARK_IDENTIFIERS,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
    TUTORIAL_MESSAGE_CONTAINER,
    TUTORIAL_MESSAGE_IDENTIFIERS,
    WHITE_BG_IDENTIFIERS,
    is_item_removed_dialog_visible,
)

logger = logging.getLogger(__name__)


class ReaderHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _check_for_download_limit_dialog(self) -> bool:
        """Check if a Download Limit dialog is currently visible.

        Returns:
            bool: True if a Download Limit dialog is found, False otherwise.
        """
        try:
            # Check all possible ways the dialog could be detected

            # Method 1: Check for dialog title
            for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS):
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Found Download Limit dialog title with #{idx}: {strategy}={locator}")
                        # Take page source for diagnostics
                        store_page_source(self.driver.page_source, "download_limit_dialog_detected")
                        return True
                except NoSuchElementException:
                    pass
                except Exception as e:
                    logger.debug(f"Error in dialog title check #{idx}: {e}")

            # Method 2: Check for download limit error text
            for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_ERROR_TEXT):
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Found Download Limit error text #{idx}: {strategy}={locator}")
                        store_page_source(self.driver.page_source, "download_limit_error_text_detected")
                        return True
                except NoSuchElementException:
                    pass
                except Exception as e:
                    logger.debug(f"Error in error text check #{idx}: {e}")

            # Method 3: Check for device list with button combination
            try:
                # Check if we have both a device list and remove button
                device_list = None
                for dl_strat, dl_loc in DOWNLOAD_LIMIT_DEVICE_LIST:
                    try:
                        device_list = self.driver.find_element(dl_strat, dl_loc)
                        if device_list.is_displayed():
                            break
                    except NoSuchElementException:
                        device_list = None

                button = None
                for btn_strat, btn_loc in DOWNLOAD_LIMIT_REMOVE_BUTTON:
                    try:
                        button = self.driver.find_element(btn_strat, btn_loc)
                        if button.is_displayed():
                            break
                    except NoSuchElementException:
                        button = None

                if device_list and button:
                    logger.info("Found Download Limit dialog via device list + button combination")
                    store_page_source(self.driver.page_source, "download_limit_combo_detected")
                    return True
            except Exception as e:
                from server.utils.appium_error_utils import is_appium_error

                if is_appium_error(e):
                    raise
                logger.debug(f"Error in device list + button check: {e}")

            # Method 4: Check current activity directly
            try:
                current_activity = self.driver.current_activity
                if "RemoteLicenseReleaseActivity" in current_activity:
                    logger.info(f"Found Download Limit dialog via activity name: {current_activity}")
                    store_page_source(self.driver.page_source, "download_limit_activity_detected")
                    return True
            except Exception as e:
                logger.debug(f"Error checking activity name: {e}")

            # If we reach here, no dialog was found
            return False

        except Exception as e:
            logger.error(f"Error checking for Download Limit dialog: {e}", exc_info=True)
            return False

    def handle_download_limit_dialog(self) -> bool:
        """Handle the 'Download Limit Reached' dialog by selecting the top device and clicking 'Remove and Download'.

        Returns:
            bool: True if successfully handled the dialog, False otherwise.
        """
        try:
            # Store page source for debugging
            store_page_source(self.driver.page_source, "download_limit_before_handling")

            # Check all possible places the dialog could be found
            dialog_found = False

            # First check title identifier with more logging
            for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS):
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        dialog_found = True
                        logger.info(
                            f"Found Download Limit dialog with identifier #{idx}: {strategy}={locator}"
                        )
                        break
                except NoSuchElementException:
                    logger.debug(f"Download limit identifier #{idx} not found")
                except Exception as e:
                    logger.warning(f"Error checking download limit identifier #{idx}: {e}")

            # Also check error text as a backup
            if not dialog_found:
                for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_ERROR_TEXT):
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            dialog_found = True
                            logger.info(f"Found Download Limit via error text #{idx}: {strategy}={locator}")
                            break
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.warning(f"Error checking error text #{idx}: {e}")

            # If still not found, check for device list with button as last resort
            if not dialog_found:
                try:
                    # Check if we have both a device list and remove button
                    device_list = None
                    for dl_strat, dl_loc in DOWNLOAD_LIMIT_DEVICE_LIST:
                        try:
                            device_list = self.driver.find_element(dl_strat, dl_loc)
                            if device_list.is_displayed():
                                break
                        except:
                            device_list = None

                    button = None
                    for btn_strat, btn_loc in DOWNLOAD_LIMIT_REMOVE_BUTTON:
                        try:
                            button = self.driver.find_element(btn_strat, btn_loc)
                            if button.is_displayed():
                                break
                        except:
                            button = None

                    if device_list and button:
                        dialog_found = True
                        logger.info(
                            "Found Download Limit dialog by identifying device list and button together"
                        )
                except Exception as e:
                    logger.debug(f"Error during combined device list + button check: {e}")

            if not dialog_found:
                logger.info("Download Limit Reached dialog not found after trying all approaches")
                self.driver.save_screenshot("screenshots/download_limit_not_found.png")
                return False

            # Use a direct approach based on the XML structure
            first_device_tapped = False

            # Direct approach using XPath to click the first LinearLayout in the device list
            try:
                # Simple XPath to find the first clickable LinearLayout in the device list
                first_device_layout = self.driver.find_element(
                    AppiumBy.XPATH,
                    "//android.widget.ListView[@resource-id='com.amazon.kindle:id/rlr_device_list']/android.widget.LinearLayout[1]",
                )
                if first_device_layout:
                    first_device_layout.click()
                    logger.info("Successfully clicked first device layout directly")
                    first_device_tapped = True
                    time.sleep(1)  # Short wait for UI to update
            except Exception as e:
                logger.warning(f"Error clicking first device: {e}")

                # Fallback to coordinate-based tap if direct method fails
                try:
                    # Get screen dimensions to calculate tap position
                    window_size = self.driver.get_window_size()
                    width = window_size["width"]

                    # Calculate position for first device (based on XML layout)
                    x = width // 2
                    y = 1335  # From the XML, the first device's CheckedTextView is around y=1283-1336

                    # Perform tap
                    self.driver.tap([(x, y)])
                    logger.info(f"Used coordinate tap at ({x}, {y}) for first device")
                    first_device_tapped = True
                    time.sleep(1)
                except Exception as e2:
                    logger.warning(f"Error with coordinate tap approach: {e2}")

            # Save a screenshot after the selection attempt
            self.driver.save_screenshot("screenshots/after_device_selection.png")

            # Find and tap the "Remove and Read Now" button
            remove_button_tapped = False

            # Wait for up to 2 seconds for the button to become enabled
            start_time = time.time()
            button_enabled = False
            enable_wait_time = 2  # seconds

            logger.info(f"Waiting up to {enable_wait_time}s for button to become enabled")
            while time.time() - start_time < enable_wait_time and not button_enabled:
                try:
                    button = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/rlr_remove_and_read_now_button"
                    )
                    if button and button.is_displayed():
                        enabled_attr = button.get_attribute("enabled")
                        if enabled_attr == "true":
                            button_enabled = True
                            logger.info(f"Button is now enabled")
                            break
                except Exception:
                    pass
                time.sleep(0.2)

            # Try clicking the button by ID first
            try:
                button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/rlr_remove_and_read_now_button"
                )
                button.click()
                logger.info("Clicked 'REMOVE AND READ NOW' button by ID")
                remove_button_tapped = True
            except Exception as e:
                logger.warning(f"Error clicking button by ID: {e}")

            # If that didn't work, try clicking by text
            if not remove_button_tapped:
                try:
                    button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[@text='REMOVE AND READ NOW']"
                    )
                    button.click()
                    logger.info("Clicked 'REMOVE AND READ NOW' button by text")
                    remove_button_tapped = True
                except Exception as e:
                    logger.warning(f"Error clicking button by text: {e}")

            # Last resort - use coordinates based on XML
            if not remove_button_tapped:
                try:
                    # Button is at bounds="[81,2132][999,2227]" in the XML
                    window_size = self.driver.get_window_size()
                    width = window_size["width"]

                    x = width // 2  # Center horizontally
                    y = 2180  # Based on XML bounds

                    self.driver.tap([(x, y)])
                    logger.info(f"Used coordinate tap for button at ({x}, {y})")
                    remove_button_tapped = True
                except Exception as e:
                    logger.warning(f"Error using coordinate tap for button: {e}")

            # Check if dialog is still visible
            dialog_still_visible = False
            try:
                dialog_title = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/rlr_title")
                if dialog_title and dialog_title.is_displayed():
                    dialog_still_visible = True
                    logger.warning("Download Limit dialog still visible after attempts")
                else:
                    logger.info("Dialog no longer visible - successfully handled")
            except NoSuchElementException:
                logger.info("Dialog title element not found - dialog may have closed")

            if dialog_still_visible and not remove_button_tapped:
                logger.error("Could not handle the Download Limit dialog", exc_info=True)
                return False

            # Wait a short time for the UI transition
            time.sleep(1)

            return True

        except Exception as e:
            logger.error(f"Error handling download limit dialog: {e}", exc_info=True)
            store_page_source(self.driver.page_source, "download_limit_error")
            return False

    def open_book(self, book_title: str, show_placemark: bool = False) -> bool:
        """Handle reading view actions after a book has been opened.

        This method assumes we're already in the reading view or about to transition to it,
        and handles all reading-view related dialogs (download limit, last read page, etc.).
        It does NOT open the book from the library - that's handled by library_handler.

        Args:
            book_title (str): Title of the book to handle.
            show_placemark (bool): Whether to tap to display the placemark ribbon.
                                  Default is False (don't show placemark).

        Returns:
            bool: True if reading view was successfully handled, False otherwise.
        """
        logger.info(f"Starting reading flow for book: {book_title}")

        # First, check immediately for special dialogs that need handling before waiting for anything else
        # This addresses the issue where we could miss detecting them during transitions

        # Check for Item Removed dialog first
        if is_item_removed_dialog_visible(self.driver):
            logger.info("Item Removed dialog detected immediately - handling it")
            if handle_item_removed_dialog(self.driver):
                logger.info("Successfully handled Item Removed dialog immediately")
                # After handling this, check if we're now looking at the Download Limit dialog
                # This can happen when the book is removed and when trying to re-open, hits download limit
                time.sleep(1)  # Short wait to ensure UI is updated

                # After Item Removed dialog closes, we're back in library view and the book may be clicked again
                # Check if Download Limit dialog appears immediately after
                if self._check_for_download_limit_dialog():
                    logger.info("Download Limit dialog detected after Item Removed dialog - handling it")
                    if self.handle_download_limit_dialog():
                        logger.info("Successfully handled Download Limit dialog after Item Removed dialog")
                        # Now wait for reading view after handling both dialogs
                        return True
                    else:
                        logger.error("Failed to handle Download Limit dialog after Item Removed dialog")
                        return False

                # If no Download Limit dialog, then we're just back to library view
                return True
            else:
                logger.error("Failed to handle Item Removed dialog detected immediately")
                return False

        # Check for download limit dialog
        download_limit_found = self._check_for_download_limit_dialog()
        if download_limit_found:
            logger.info("Download Limit dialog detected immediately - handling it")
            if self.handle_download_limit_dialog():
                logger.info("Successfully handled Download Limit dialog immediately")
                # Continue to reading view handling below
            else:
                logger.error("Failed to handle Download Limit dialog detected immediately")
                return False

        # Check for dialogs that might appear immediately after opening a book
        from views.common.dialog_handler import DialogHandler

        dialog_handler = DialogHandler(self.driver)

        # Check for dialogs in a loop (up to 3 dialogs)
        dialogs_handled = 0
        max_dialogs = 3

        for i in range(max_dialogs):
            dialog_found = False

            # Check for Read and Listen dialog
            if dialog_handler.check_for_read_and_listen_dialog():
                logger.info("Read and Listen dialog detected and handled")
                dialog_found = True
                dialogs_handled += 1
                time.sleep(0.5)  # Brief wait for dialog dismissal

            # Check for Viewing full screen dialog
            if dialog_handler.check_for_viewing_full_screen_dialog():
                logger.info("Viewing full screen dialog detected and handled")
                dialog_found = True
                dialogs_handled += 1
                time.sleep(0.5)  # Brief wait for dialog dismissal

            # If no dialog was found this iteration, break the loop
            if not dialog_found:
                break

        if dialogs_handled > 0:
            logger.info(f"Handled {dialogs_handled} dialog(s) before waiting for reading view")

        # Wait for the reading view to appear
        try:
            # Track time and capture page source periodically
            start_time = time.time()
            last_capture_time = start_time - 1.0  # Ensure first capture happens immediately
            capture_count = 0

            # Capture initial state
            logger.info("Capturing initial state before waiting for reading view")
            store_page_source(self.driver.page_source, "before_reading_view_wait")

            # Custom wait condition to check for any of the reading view identifiers,
            # download limit dialog, or Word Wise dialog
            def reading_view_or_dialog_present(driver):
                nonlocal last_capture_time, capture_count

                # Always do time-based capture first, before any early returns
                current_time = time.time()
                elapsed_since_last = current_time - last_capture_time

                if elapsed_since_last >= 1.0:
                    capture_count += 1
                    elapsed = current_time - start_time
                    logger.info(f"Waiting for reading view to appear... {elapsed:.1f}s elapsed")
                    store_page_source(
                        driver.page_source, f"waiting_for_reading_view_{capture_count}_{int(elapsed)}s"
                    )
                    last_capture_time = current_time
                # First check for download limit dialog - try all detection methods

                # Method 1: Check for download limit dialog headers
                for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS):
                    try:
                        element = driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            logger.info(
                                f"Download Limit dialog detected with identifier #{idx}: {strategy}={locator}"
                            )
                            return "download_limit"
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.debug(f"Error checking download limit identifier #{idx}: {e}")

                # Method 2: Check for download limit error text
                try:
                    for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_ERROR_TEXT):
                        try:
                            element = driver.find_element(strategy, locator)
                            if element and element.is_displayed():
                                logger.info(f"Download Limit dialog detected via error text #{idx}")
                                return "download_limit"
                        except NoSuchElementException:
                            pass
                        except Exception as e:
                            logger.debug(f"Error checking error text identifier #{idx}: {e}")
                except Exception as e:
                    logger.debug(f"General error checking error text: {e}")

                # Method 3: Check for download limit device list + button combination
                try:
                    # Try to find both a device list and remove/download button
                    device_list = None
                    for dl_strategy, dl_locator in DOWNLOAD_LIMIT_DEVICE_LIST:
                        try:
                            el = driver.find_element(dl_strategy, dl_locator)
                            if el.is_displayed():
                                device_list = True
                                break
                        except NoSuchElementException:
                            pass

                    remove_button = None
                    for btn_strategy, btn_locator in DOWNLOAD_LIMIT_REMOVE_BUTTON:
                        try:
                            el = driver.find_element(btn_strategy, btn_locator)
                            if el.is_displayed():
                                remove_button = True
                                break
                        except NoSuchElementException:
                            pass

                    if device_list and remove_button:
                        logger.info("Download Limit dialog detected via device list + button combination")
                        return "download_limit"
                except Exception as e:
                    logger.debug(f"Error checking for device list + button: {e}")

                # Then check for reading view
                for idx, strategy in enumerate(READING_VIEW_IDENTIFIERS):
                    try:
                        element = driver.find_element(strategy[0], strategy[1])
                        if element:
                            return "reading_view"
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.debug(f"Error checking reading view identifier #{idx}: {e}")

                # Check for last read page dialog as a separate detectable state
                try:
                    last_read = driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Go to that')]"
                    )
                    if last_read and last_read.is_displayed():
                        logger.info(f"Last Read dialog detected during open_book: {last_read.text}")
                        # We'll treat this as a reading_view since we have handling for it later
                        return "reading_view"
                except NoSuchElementException:
                    pass

                # Check for Word Wise dialog
                for idx, (strategy, locator) in enumerate(WORD_WISE_DIALOG_IDENTIFIERS):
                    try:
                        element = driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            logger.info(
                                f"Word Wise dialog detected with identifier #{idx}: {strategy}={locator}"
                            )
                            return "word_wise"
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.debug(f"Error checking Word Wise identifier #{idx}: {e}")

                # Check for Goodreads auto-update dialog
                for idx, (strategy, locator) in enumerate(GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS):
                    try:
                        element = driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            logger.info(
                                f"Goodreads auto-update dialog detected with identifier #{idx}: {strategy}={locator}"
                            )
                            return "goodreads"
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.debug(f"Error checking Goodreads identifier #{idx}: {e}")

                return False

            # If we already found and handled the download limit dialog, skip the wait
            if not download_limit_found:
                # Wait for either reading view element or blocking dialogs to appear
                result = WebDriverWait(self.driver, 6).until(
                    reading_view_or_dialog_present
                )  # Wait up to 6 seconds
            else:
                # We already handled the download limit dialog, just wait for reading view
                logger.info("Skipping wait since download limit dialog was already handled")
                # Set result to avoid undefined variable
                result = "reading_view"

            # Handle download limit dialog if it appeared and wasn't already handled
            if result == "download_limit" and not download_limit_found:
                logger.info("Download Limit dialog detected - handling it")
                if self.handle_download_limit_dialog():
                    logger.info("Successfully handled Download Limit dialog, waiting for reading view")
                    # Now wait for the reading view after handling the dialog
                    try:
                        # Track time for second wait
                        wait_start_time = time.time()
                        wait_last_capture_time = wait_start_time
                        wait_capture_count = 0

                        def reading_view_present(driver):
                            nonlocal wait_last_capture_time, wait_capture_count

                            # Capture page source every second while waiting
                            current_time = time.time()
                            if current_time - wait_last_capture_time >= 1.0:
                                wait_capture_count += 1
                                elapsed = current_time - wait_start_time
                                logger.info(
                                    f"Waiting for reading view after download limit... {elapsed:.1f}s elapsed"
                                )
                                store_page_source(
                                    driver.page_source,
                                    f"after_download_limit_wait_{wait_capture_count}_{int(elapsed)}s",
                                )
                                wait_last_capture_time = current_time

                            for strategy in READING_VIEW_IDENTIFIERS:
                                try:
                                    element = driver.find_element(strategy[0], strategy[1])
                                    if element:
                                        return True
                                except NoSuchElementException:
                                    pass
                            return False

                        # Wait for reading view now that download limit is handled
                        try:
                            WebDriverWait(self.driver, 5).until(
                                reading_view_present
                            )  # Shorter timeout for download after limit handling
                            logger.info("Reading view detected after handling download limit")
                        except TimeoutException:
                            # If we timeout waiting for the reading view, we might be back at the library
                            # Let's check if we're back in the library view
                            store_page_source(self.driver.page_source, "after_download_limit_timeout")
                            logger.info(
                                "Checking if we're back at the library view after download limit handling..."
                            )

                            # Check for library view elements
                            try:
                                library_view = False
                                try:
                                    # Check for library view root
                                    library_element = self.driver.find_element(
                                        AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                                    )
                                    if library_element.is_displayed():
                                        library_view = True
                                except NoSuchElementException:
                                    # Try another library indicator
                                    try:
                                        library_tab = self.driver.find_element(
                                            AppiumBy.XPATH,
                                            "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']",
                                        )
                                        if library_tab.is_displayed():
                                            library_view = True
                                    except:
                                        pass

                                if library_view:
                                    logger.info(
                                        "We're back at the library view after handling download limit"
                                    )
                                    logger.info("Attempting to open the book again...")

                                    # Retry finding and clicking the book one more time
                                    # Without causing a circular reference, we'll handle this in a special way
                                    if (
                                        hasattr(self.driver, "automator")
                                        and hasattr(self.driver.automator, "state_machine")
                                        and hasattr(self.driver.automator.state_machine, "library_handler")
                                    ):
                                        library_handler = self.driver.automator.state_machine.library_handler
                                        # Use find_book instead of open_book to avoid circular reference
                                        if library_handler.find_book(book_title):
                                            logger.info(
                                                "Successfully clicked on book again after download limit handling"
                                            )
                                        else:
                                            logger.error(
                                                f"Failed to click on book: {book_title} after download limit handling",
                                                exc_info=True,
                                            )
                                            return False
                                    else:
                                        logger.error(
                                            f"Cannot reopen book: {book_title} - library_handler not available"
                                        )
                                        return False

                                    # Now wait for reading view again
                                    try:
                                        WebDriverWait(self.driver, 15).until(reading_view_present)
                                        logger.info("Reading view detected after reopening book")
                                        return True
                                    except TimeoutException:
                                        logger.error(
                                            "Failed to detect reading view after reopening book",
                                            exc_info=True,
                                        )
                                        store_page_source(
                                            self.driver.page_source, "failed_reopen_after_download_limit"
                                        )
                            except Exception as back_to_lib_e:
                                logger.error(
                                    f"Error checking if back at library: {back_to_lib_e}", exc_info=True
                                )

                            # If we're still here, we failed
                            logger.error("Failed to detect reading view after handling download limit")
                            store_page_source(
                                self.driver.page_source, "failed_to_detect_reading_view_after_download"
                            )
                            return False
                    except Exception as e:
                        logger.error(
                            f"Error while waiting for reading view after download limit: {e}", exc_info=True
                        )
                        store_page_source(self.driver.page_source, "error_waiting_after_download_limit")
                        return False
                else:
                    logger.error("Failed to handle Download Limit dialog")
                    return False

            # Handle Word Wise dialog if it appeared
            elif result == "word_wise":
                logger.info("Word Wise dialog detected - handling it")
                store_page_source(self.driver.page_source, "word_wise_dialog_detected")

                # Find and click the "NO THANKS" button
                for strategy, locator in WORD_WISE_NO_THANKS_BUTTON:
                    try:
                        no_thanks_button = self.driver.find_element(strategy, locator)
                        if no_thanks_button.is_displayed():
                            logger.info("Clicking 'NO THANKS' button on Word Wise dialog")
                            no_thanks_button.click()

                            # Verify dialog is gone and wait for reading view
                            try:
                                time.sleep(0.5)  # Brief pause for dialog dismissal

                                # Now wait for the reading view after handling the dialog
                                def reading_view_present_after_word_wise(driver):
                                    for strategy in READING_VIEW_IDENTIFIERS:
                                        try:
                                            element = driver.find_element(strategy[0], strategy[1])
                                            if element:
                                                return True
                                        except NoSuchElementException:
                                            pass
                                    return False

                                WebDriverWait(self.driver, 10).until(reading_view_present_after_word_wise)
                                logger.info("Reading view detected after dismissing Word Wise dialog")
                                store_page_source(self.driver.page_source, "word_wise_dialog_dismissed")
                                break
                            except TimeoutException:
                                logger.error(
                                    "Failed to detect reading view after dismissing Word Wise dialog",
                                    exc_info=True,
                                )
                                store_page_source(
                                    self.driver.page_source, "failed_reading_view_after_word_wise"
                                )
                                return False
                    except NoSuchElementException:
                        continue
                    except Exception as e:
                        logger.error(f"Error clicking Word Wise NO THANKS button: {e}", exc_info=True)

            # Handle Goodreads dialog if it appeared
            elif result == "goodreads":
                logger.info("Goodreads auto-update dialog detected - handling it")
                store_page_source(self.driver.page_source, "goodreads_dialog_detected")

                try:
                    # Find and click the "NOT NOW" button
                    not_now_button = self.driver.find_element(
                        *GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS[1]  # Index 1 is the "NOT NOW" button
                    )
                    if not_now_button.is_displayed():
                        logger.info("Clicking 'NOT NOW' button on Goodreads auto-update dialog")
                        not_now_button.click()

                        # Wait for reading view
                        try:
                            time.sleep(0.5)  # Brief pause for dialog dismissal

                            def reading_view_present_after_goodreads(driver):
                                for strategy in READING_VIEW_IDENTIFIERS:
                                    try:
                                        element = driver.find_element(strategy[0], strategy[1])
                                        if element:
                                            return True
                                    except NoSuchElementException:
                                        pass
                                return False

                            WebDriverWait(self.driver, 10).until(reading_view_present_after_goodreads)
                            logger.info("Reading view detected after dismissing Goodreads dialog")
                            store_page_source(self.driver.page_source, "goodreads_dialog_dismissed")
                        except TimeoutException:
                            logger.error(
                                "Failed to detect reading view after dismissing Goodreads dialog",
                                exc_info=True,
                            )
                            store_page_source(self.driver.page_source, "failed_reading_view_after_goodreads")
                            return False
                except Exception as e:
                    logger.error(f"Error handling Goodreads dialog: {e}", exc_info=True)
                    return False
        except TimeoutException:
            logger.error("Failed to detect reading view or blocking dialogs after 6 seconds", exc_info=True)

            # Capture final state for debugging
            final_elapsed = time.time() - start_time
            logger.info(f"Timeout occurred after {final_elapsed:.1f}s total wait time")
            store_page_source(self.driver.page_source, f"timeout_final_state_{int(final_elapsed)}s")

            # Check if we're unexpectedly still in the library view
            try:
                library_element = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                )
                if library_element.is_displayed():
                    logger.error("Unexpectedly still in library view - book click may have failed")
                    store_page_source(self.driver.page_source, "still_in_library_view_in_reader_handler")
                    return False
            except NoSuchElementException:
                # Not in library view, but also not in reading view - unknown state
                logger.error("Not in library or reading view - unknown state", exc_info=True)

            store_page_source(self.driver.page_source, "failed_to_detect_reading_view_or_download_limit")
            return False
        except Exception as e:
            logger.error(f"Error while waiting for reading view or download limit: {e}", exc_info=True)
            store_page_source(self.driver.page_source, "error_waiting_for_reading_view_or_download_limit")
            return False

        # Viewing full screen dialog is now handled in the dialog loop above

        # We already confirmed the reading view is loaded above, so no need for additional waiting
        # Just check for page content container which should be available immediately
        try:
            page_content = self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/reader_content_container"
            )
        except NoSuchElementException:
            logger.warning("Page content container not immediately found - app may still be loading content")
        except Exception as e:
            logger.error(f"Error checking for page content: {e}", exc_info=True)
            # Continue anyway as we already confirmed we're in reading view

        # Check for and handle tutorial message
        try:
            if self.check_and_handle_tutorial_message():
                logger.info("Successfully handled tutorial message")
        except Exception as e:
            logger.error(f"Error checking/handling tutorial message: {e}", exc_info=True)

        # Check for and dismiss bottom sheet dialog
        try:
            # Try to find the bottom sheet dialog
            try:
                bottom_sheet = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[0])
                if bottom_sheet.is_displayed():
                    logger.info("Found bottom sheet dialog - attempting to dismiss")
                    try:
                        pill = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[1])
                        if pill.is_displayed():
                            pill.click()
                            logger.info("Clicked bottom sheet pill to dismiss")

                            # Verify bottom sheet is gone
                            try:
                                bottom_sheet = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[0])
                                if bottom_sheet.is_displayed():
                                    logger.error("Bottom sheet dialog is still visible after dismissal")
                                    return False
                                else:
                                    logger.info("Bottom sheet successfully dismissed")
                            except NoSuchElementException:
                                logger.info("Bottom sheet successfully dismissed")

                            filepath = store_page_source(self.driver.page_source, "bottom_sheet_dismissed")
                            logger.info(f"Stored bottom sheet dismissed page source at: {filepath}")
                        else:
                            logger.info("Bottom sheet pill found but not visible")
                    except NoSuchElementException:
                        logger.info("Bottom sheet found but dismiss pill not found")
                    except Exception as e:
                        logger.error(f"Error clicking bottom sheet pill: {e}", exc_info=True)
                else:
                    logger.info("Bottom sheet dialog found but not visible")
            except NoSuchElementException:
                pass
            except Exception as e:
                logger.error(f"Error checking for bottom sheet dialog: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Unexpected error handling bottom sheet: {e}", exc_info=True)

        # We'll use the NavigationResourceHandler to handle the last read page dialog
        # so we can return it to the client for decision instead of automatically clicking YES
        from handlers.navigation_handler import NavigationResourceHandler

        try:
            nav_handler = NavigationResourceHandler(self.driver.automator, self.screenshots_dir)
            # We don't auto-accept the dialog - we'll return it to the client
            # The client will then use the /last-read-page-dialog endpoint to make a decision
            dialog_result = nav_handler._handle_last_read_page_dialog(auto_accept=False)

            # If dialog was found, we let the caller handle it and don't click anything
            if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
                logger.info("Found 'last read page' dialog - leaving it for client to decide")
                # We don't click anything - the client will decide using the /last-read-page-dialog endpoint
        except Exception as e:
            logger.error(f"Error checking for 'last read page/location' dialog: {e}", exc_info=True)

        # The "Go to that location/page?" dialog is essentially the same as "Last read page" dialog,
        # so we handle both identically - either could be shown when opening a book
        # We've already checked for the "Last read page" dialog above and don't click either one

        # We'll add the "Go to that page" text to the dialog detection in NavigationResourceHandler
        # nav_handler is already created above, so we'll keep this section simple
        try:
            # Check for "Go to that location/page?" dialog
            for strategy, locator in GO_TO_LOCATION_DIALOG_IDENTIFIERS:
                try:
                    message = self.driver.find_element(strategy, locator)
                    if message.is_displayed() and (
                        "Go to that location?" in message.text or "Go to that page?" in message.text
                    ):
                        logger.info(
                            "Found 'Go to that location/page?' dialog - leaving it for client to decide"
                        )
                        # Don't click anything - client will decide via /last-read-page-dialog endpoint
                        # The /last-read-page-dialog endpoint already looks for both types of dialogs
                        break
                except NoSuchElementException:
                    continue
        except Exception as e:
            logger.error(f"Error checking for 'Go to that location/page?' dialog: {e}", exc_info=True)

        # Note: Goodreads and Word Wise dialogs are now handled during the wait condition above
        # to prevent them from blocking the reading view detection

        # Check for and dismiss the comic book view
        try:
            # Try to handle the comic book view if present
            self.handle_comic_book_view()
        except Exception as e:
            logger.error(f"Error during comic book view handling: {e}", exc_info=True)

        # Check for and dismiss "About this book" slideover
        try:
            about_book_visible = False

            for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                try:
                    slideover = self.driver.find_element(strategy, locator)
                    if slideover.is_displayed():
                        about_book_visible = True
                        logger.info("Found 'About this book' slideover")
                        break
                except NoSuchElementException:
                    continue

            if about_book_visible:
                # Try finding and clicking the pill element to dismiss
                try:
                    pill = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[1])
                    if pill.is_displayed():
                        pill.click()
                        logger.info("Clicked pill to dismiss 'About this book' slideover")
                        time.sleep(1)
                    else:
                        logger.info("Pill found but not visible")
                except NoSuchElementException:
                    logger.info("Pill not found - trying alternative dismissal method")

                    # Try tapping near the top of the screen
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    top_y = int(window_size["height"] * 0.10)  # Tap at approx. 10% from the top
                    self.driver.tap([(center_x, top_y)])
                    logger.info("Tapped near top of screen to dismiss 'About this book' slideover")
                    time.sleep(1)

                # Verify dismissal
                still_visible = False
                for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                    try:
                        slideover = self.driver.find_element(strategy, locator)
                        if slideover.is_displayed():
                            still_visible = True
                            break
                    except NoSuchElementException:
                        continue

                if still_visible:
                    logger.info("Slideover still visible - trying another approach")
                    # Try swiping down to dismiss
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    start_y = int(window_size["height"] * 0.3)
                    end_y = int(window_size["height"] * 0.7)
                    self.driver.swipe(center_x, start_y, center_x, end_y, 500)
                    logger.info("Swiped down to dismiss 'About this book' slideover")
                    time.sleep(1)

                    # Final verification
                    still_visible = False
                    for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = self.driver.find_element(strategy, locator)
                            if slideover.is_displayed():
                                still_visible = True
                                break
                        except NoSuchElementException:
                            continue

                    if still_visible:
                        logger.warning(
                            "'About this book' slideover is still visible after dismissal attempts"
                        )
                    else:
                        logger.info("'About this book' slideover successfully dismissed")
                else:
                    logger.info("'About this book' slideover successfully dismissed")

                filepath = store_page_source(self.driver.page_source, "after_about_book_dismissal")
                logger.info(f"Stored page source after dismissal at: {filepath}")
        except Exception as e:
            logger.error(f"Error handling 'About this book' slideover: {e}", exc_info=True)

        # Get current page
        current_page = self.get_current_page()

        # Check if we need to update reading styles for this profile
        if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "profile_manager"):
            profile_manager = self.driver.automator.profile_manager
            if hasattr(self.driver.automator, "state_machine") and hasattr(
                self.driver.automator.state_machine, "style_handler"
            ):
                style_handler = self.driver.automator.state_machine.style_handler

                # Update styles if needed
                if not profile_manager.is_styles_updated():
                    logger.info("First-time reading with this profile, updating reading styles...")
                    if style_handler.update_reading_style(show_placemark=show_placemark):
                        logger.info("Successfully updated reading styles")
                    else:
                        logger.warning("Failed to update reading styles")
                else:
                    logger.info("Reading styles already updated for this profile, skipping")
            else:
                logger.warning("Cannot update reading styles - style_handler not available")
        else:
            logger.warning("Cannot update reading styles - profile_manager not available")

        # Optionally show placemark by tapping center of page
        if show_placemark:
            logger.info("Placemark mode enabled - tapping to show placemark ribbon")
            try:
                window_size = self.driver.get_window_size()
                center_x = window_size["width"] // 2
                center_y = window_size["height"] // 2
                self.driver.tap([(center_x, center_y)])
                logger.info("Tapped center of page to show placemark")
                time.sleep(0.5)  # Brief wait for placemark to appear

                # Verify placemark is visible
                placemark_visible, _ = self._check_element_visibility(
                    PLACEMARK_IDENTIFIERS, "placemark ribbon"
                )
                if placemark_visible:
                    logger.info("Placemark ribbon successfully displayed")
                else:
                    logger.warning("Placemark ribbon not visible after tapping")
            except Exception as e:
                logger.error(f"Error showing placemark: {e}", exc_info=True)
        else:
            logger.info("Placemark mode disabled - skipping center tap")

        # Save the actively reading title to profile settings
        try:
            sindarin_email = get_sindarin_email()
            if sindarin_email:
                self.driver.automator.profile_manager.save_style_setting(
                    "actively_reading_title", book_title, email=sindarin_email
                )
                logger.info(f"Saved actively reading title: {book_title}")
            else:
                logger.warning("No sindarin_email available to save actively reading title")
        except Exception as e:
            logger.error(f"Error saving actively reading title: {e}", exc_info=True)
            # Don't fail the whole operation just because we couldn't save the title

        return True

    def get_current_page(self):
        """Get the current page number without triggering placemark

        Returns:
            str: Page number text or None if not found
        """
        try:
            # Look for page number without any tapping
            for strategy, locator in PAGE_NUMBER_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    page_text = element.text.strip()
                    logger.info(f"Found page number: {page_text}")
                    return page_text
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.warning(f"Error getting page text with strategy {strategy}: {e}")

            # If we get here, we couldn't find the page number element
            return None
        except Exception as e:
            logger.error(f"Error getting page number: {e}", exc_info=True)
            return None

    def capture_page_screenshot(self):
        """Capture a screenshot of the current page"""
        try:
            logger.info("Capturing page screenshot...")

            # Get device ID from driver
            device_id = None
            if hasattr(self.driver, "automator") and self.driver.automator:
                device_id = self.driver.automator.device_id
            elif hasattr(self.driver, "_caps") and "udid" in self.driver._caps:
                device_id = self.driver._caps["udid"]
            else:
                # Try to get from adb devices
                result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
                lines = result.stdout.strip().split("\n")[1:]
                if lines and "device" in lines[0]:
                    device_id = lines[0].split("\t")[0]

            if not device_id:
                logger.error("Could not determine device ID for screenshot")
                return False

            screenshot_path = os.path.join(self.screenshots_dir, "reading_page.png")
            result_path = take_adb_screenshot(device_id, screenshot_path)

            if result_path:
                logger.info(f"Successfully saved page screenshot to {result_path}")
                return True
            else:
                logger.error("Failed to capture page screenshot")
                return False

        except Exception as e:
            logger.error(f"Error capturing page screenshot: {e}", exc_info=True)
            return False

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 0):
        """Swipe from one point to another point, for an optional duration.

        Args:
            start_x: x-coordinate at which to start
            start_y: y-coordinate at which to start
            end_x: x-coordinate at which to stop
            end_y: y-coordinate at which to stop
            duration: defines the swipe speed as time taken to swipe from point a to point b, in ms.

        Usage:
            driver.swipe(100, 100, 100, 400)

        Returns:
            Union['WebDriver', 'ActionHelpers']: Self instance
        """

        self.driver.swipe(start_x, start_y, end_x, end_y, duration)

    def turn_page(self, direction: int):
        """Turn to the next/previous page."""
        try:
            # First check if a placemark is active and close it by tapping in the top area
            # which won't interfere with navigation
            try:
                placemark_visible, _ = self._check_element_visibility(
                    PLACEMARK_IDENTIFIERS, "placemark ribbon"
                )
                if placemark_visible:
                    logger.info("Found placemark ribbon - removing it before page turn")
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    top_y = int(window_size["height"] * 0.05)  # 5% from top
                    self.driver.tap([(center_x, top_y)])
                    logger.info(f"Tapped near top ({center_x}, {top_y}) to close placemark before page turn")
                    time.sleep(0.5)  # Wait for placemark to disappear
            except Exception as e:
                logger.warning(f"Error checking/closing placemark: {e}")

            # Check if we're in reading toolbar view
            for strategy, locator in READING_TOOLBAR_IDENTIFIERS:
                try:
                    toolbar = self.driver.find_element(strategy, locator)
                    if toolbar.is_displayed():
                        # Tap center to exit toolbar view
                        logger.info("Tapping center to exit toolbar view")
                        window_size = self.driver.get_window_size()
                        center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                        center_y = window_size["height"] // 2
                        self.driver.tap([(center_x, center_y)])
                        time.sleep(0.5)  # Wait for toolbar to hide
                        break
                except NoSuchElementException:
                    continue  # Try the next strategy

            # Get screen dimensions and calculate tap coordinates
            window_size = self.driver.get_window_size()
            tap_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["next"])  # 90% of screen width
            end_x = tap_x * 0.2
            tap_y = window_size["height"] // 2

            # Gesture swipe left
            if direction == 1:
                self.swipe(tap_x, tap_y, end_x, tap_y, 200)
                logger.info(f"Swiped left ({tap_x}, {tap_y}) to turn page forward")
            else:
                self.swipe(end_x, tap_y, tap_x, tap_y, 200)
                logger.info(f"Swiped right ({tap_x}, {tap_y}) to turn page backward")

            # Short wait for page turn animation
            time.sleep(0.5)
            return True

        except Exception as e:
            logger.error(f"Error turning page forward: {e}", exc_info=True)
            return False

    def turn_page_forward(self):
        """Turn to the next page."""

        return self.turn_page(1)

    def turn_page_backward(self):
        """Turn to the previous page."""

        return self.turn_page(-1)

    def _extract_screenshot_for_ocr(self, prefix):
        """Take a screenshot and perform OCR on it.

        Args:
            prefix: Prefix for the screenshot filename

        Returns:
            tuple: (ocr_text, error_message) - OCR text if successful, error message if failed
        """
        try:
            # Give the page a moment to render fully
            time.sleep(0.5)

            # Take screenshot
            screenshot_id = f"{prefix}_{int(time.time())}"
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.driver.save_screenshot(screenshot_path)

            # Get OCR text from screenshot
            ocr_text = None
            error_msg = None

            try:
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                # Import the OCR processor
                from server.server import KindleOCR

                ocr_text, error_msg = KindleOCR.process_ocr(image_data)

                # Delete the screenshot file after processing
                try:
                    os.remove(screenshot_path)
                    logger.info(f"Deleted screenshot after OCR processing: {screenshot_path}")
                except Exception as del_e:
                    logger.error(f"Failed to delete screenshot {screenshot_path}: {del_e}", exc_info=True)

            except Exception as e:
                logger.error(f"Error processing OCR: {e}", exc_info=True)
                error_msg = str(e)

            return ocr_text, error_msg

        except Exception as e:
            logger.error(f"Error taking screenshot for OCR: {e}", exc_info=True)
            return None, str(e)

    def preview_page_forward(self):
        """Preview the next page - turn forward, take OCR screenshot, then turn back."""
        try:
            logger.info("Previewing next page")

            # First turn the page forward
            success = self.turn_page_forward()
            if not success:
                logger.error("Failed to turn page forward during preview")
                return False, None

            # Extract text with OCR
            ocr_text, error_msg = self._extract_screenshot_for_ocr("preview_next")

            # Now turn the page back to the original
            back_success = self.turn_page_backward()
            if not back_success:
                logger.error("Failed to turn page back to original after preview")
                # Still continue to return the OCR text

            if ocr_text:
                logger.info("Successfully previewed next page and extracted OCR text")
                return True, ocr_text
            else:
                logger.error(f"Failed to extract OCR text from preview: {error_msg}")
                return False, None

        except Exception as e:
            logger.error(f"Error during next page preview: {e}", exc_info=True)
            # Try to turn back to the original page if an error occurred
            try:
                self.turn_page_backward()
            except Exception as turn_back_error:
                logger.error(
                    f"Failed to turn back to original page after error: {turn_back_error}", exc_info=True
                )
            return False, None

    def preview_page_backward(self):
        """Preview the previous page - turn backward, take OCR screenshot, then turn forward."""
        try:
            logger.info("Previewing previous page")

            # First turn the page backward
            success = self.turn_page_backward()
            if not success:
                logger.error("Failed to turn page backward during preview")
                return False, None

            # Extract text with OCR
            ocr_text, error_msg = self._extract_screenshot_for_ocr("preview_prev")

            # Now turn the page forward to the original
            forward_success = self.turn_page_forward()
            if not forward_success:
                logger.error("Failed to turn page forward to original after preview")
                # Still continue to return the OCR text

            if ocr_text:
                logger.info("Successfully previewed previous page and extracted OCR text")
                return True, ocr_text
            else:
                logger.error(f"Failed to extract OCR text from preview: {error_msg}")
                return False, None

        except Exception as e:
            logger.error(f"Error during previous page preview: {e}", exc_info=True)
            # Try to turn forward to the original page if an error occurred
            try:
                self.turn_page_forward()
            except Exception as turn_forward_error:
                logger.error(
                    f"Failed to turn forward to original page after error: {turn_forward_error}",
                    exc_info=True,
                )
            return False, None

    def get_reading_progress(self, show_placemark=False):
        """Get reading progress information

        Args:
            show_placemark (bool): Whether to use center tap that could trigger placemark.
                                   If False, skip getting reading progress to avoid placemark.

        Returns:
            dict: Dictionary containing:
                - percentage: Reading progress as percentage (str)
                - current_page: Current page number (int)
                - total_pages: Total pages (int)
            or None if progress info couldn't be retrieved
            or a minimal dict with just page number if show_placemark=False
        """
        opened_controls = False
        try:
            # Always try to get basic page info first without tapping
            page_info = self.get_current_page()
            logger.info(f"Initial page info: {page_info}")

            # If placemark is not requested, never tap
            if not show_placemark:
                logger.info("Placemark mode disabled - skipping reading progress tap entirely")
                # Return a minimal set of information
                if page_info and "Page" in page_info:
                    try:
                        parts = page_info.split(" of ")
                        if len(parts) == 2:
                            current_page = int(parts[0].replace("Page ", ""))
                            total_pages = int(parts[1])
                            return {
                                "percentage": None,
                                "current_page": current_page,
                                "total_pages": total_pages,
                            }
                    except Exception as e:
                        logger.warning(f"Error parsing basic page info: {e}")
                # If we can't parse, just return an empty result
                return {"percentage": None, "current_page": None, "total_pages": None}

            # If we get here, show_placemark is True - try to get full progress info

            # First check if we can find progress element directly
            try:
                progress_element = self.driver.find_element(*READING_PROGRESS_IDENTIFIERS[0])
                logger.info("Found progress element without tapping")
            except NoSuchElementException:
                logger.info("Progress element not found initially - will need to tap")
                # Only tap if explicitly requested via show_placemark=True
                window_size = self.driver.get_window_size()
                center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                center_y = window_size["height"] // 2
                self.driver.tap([(center_x, center_y)])
                logger.info("Tapped center to show controls (placemark explicitly enabled)")
                time.sleep(0.5)  # Wait for controls to appear

                # Wait for toolbar to appear
                try:

                    def check_toolbar_visibility(driver):
                        for strategy, locator in READING_TOOLBAR_IDENTIFIERS:
                            try:
                                element = driver.find_element(strategy, locator)
                                if element.is_displayed():
                                    return True
                            except NoSuchElementException:
                                continue
                        return False

                    WebDriverWait(self.driver, 3).until(check_toolbar_visibility)
                    logger.info("Reading controls now visible")
                    opened_controls = True
                except TimeoutException:
                    logger.error("Could not make reading controls visible", exc_info=True)
                    return None

                try:
                    for strategy, locator in READING_PROGRESS_IDENTIFIERS:
                        try:
                            progress_element = self.driver.find_element(strategy, locator)
                            break
                        except NoSuchElementException:
                            continue
                    else:
                        raise NoSuchElementException("Could not find any reading progress element")
                except NoSuchElementException:
                    logger.error("Could not find progress element after showing controls", exc_info=True)
                    return None

            # Extract progress text (format: "Page X of Y  •  Z%" or "Page X of Y")
            progress_text = progress_element.text.strip()
            logger.info(f"Found progress text: {progress_text}")

            # Initialize return values
            percentage = None
            current_page = None
            total_pages = None

            # Extract percentage if present (between the last space before the % and the %)
            if "%" in progress_text:
                percentage_regex = r"(\d+)%"
                match = re.search(percentage_regex, progress_text)
                if match:
                    percentage = int(match.group(1))

            # Extract page numbers
            if "of" in progress_text.lower():
                try:
                    page_regex = r"page\s+(\d+)\sof\s+(\d+)"
                    match = re.search(page_regex, progress_text.lower())
                    if match:
                        current_page = int(match.group(1))
                        total_pages = int(match.group(2))

                    # Calculate percentage if not found in text
                    if not percentage and current_page is not None and total_pages is not None:
                        calc_percentage = round((current_page / total_pages) * 100)
                        percentage = calc_percentage  # Return as int, not string
                except Exception as e:
                    logger.error(f"Error parsing page numbers: {e}", exc_info=True)

            if opened_controls and show_placemark:
                # Only try to close controls by tapping if we're in placemark mode
                # Otherwise we'd be showing placemark when trying to hide controls
                window_size = self.driver.get_window_size()
                center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                center_y = window_size["height"] // 2
                logger.info("Closing reading controls")
                self.driver.tap([(center_x, center_y)])

            if not any([percentage, current_page, total_pages]):
                logger.error("Could not extract any progress information")
                return None

            return {"percentage": percentage, "current_page": current_page, "total_pages": total_pages}

        except Exception as e:
            logger.error(f"Error getting reading progress: {e}", exc_info=True)
            return None

    def _check_element_visibility(self, strategies, description):
        """Check if any element from the given strategies is visible.

        Args:
            strategies: List of (strategy, locator) tuples to check
            description: Description of what we're checking for logging

        Returns:
            tuple: (is_visible, element) or (False, None) if not found
        """
        for strategy, locator in strategies:
            try:
                element = self.driver.find_element(strategy, locator)
                if element.is_displayed():
                    logger.info(f"Found visible {description}")
                    return True, element
            except NoSuchElementException:
                continue
        return False, None

    def get_book_title(self):
        """Get the title of the book currently being read.

        Returns:
            str: Book title if found, None otherwise
        """
        try:
            logger.info("Trying to get current book title")

            # Try to show the reader toolbar to access book info
            visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "reading toolbar")

            # If toolbar not visible, try to show it by tapping center
            if not visible:
                logger.info("Toolbar not visible, attempting to show it")
                try:
                    # Get screen dimensions
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    tap_y = window_size["height"] // 2

                    # Try tapping center of screen to show toolbar
                    self.driver.tap([(center_x, tap_y)])
                    logger.info(f"Tapped center at ({center_x}, {tap_y})")
                    time.sleep(0.5)

                    # Check if toolbar appeared
                    visible, _ = self._check_element_visibility(
                        READING_TOOLBAR_IDENTIFIERS, "reading toolbar after tap"
                    )
                    if not visible:
                        logger.warning("Failed to show toolbar to get book title")
                except Exception as e:
                    logger.warning(f"Error showing toolbar: {e}")

            # Try different strategies to get the book title

            # Strategy 1: Try to find title from the reader screen
            try:
                # Look for the title in the reader view toolbar
                title_element = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/ToolbarTitleBar")
                if title_element.is_displayed():
                    title = title_element.text
                    logger.info(f"Found book title from toolbar: '{title}'")
                    return title
            except NoSuchElementException:
                pass

            # Strategy 2: Show book details by clicking menu button and look for title there
            try:
                # First check if the toolbar is visible
                visible, toolbar = self._check_element_visibility(
                    READING_TOOLBAR_IDENTIFIERS, "reading toolbar"
                )

                if visible:
                    # Click on the menu button (three dots) if present
                    try:
                        menu_button = self.driver.find_element(
                            AppiumBy.ID, "com.amazon.kindle:id/reader_menu_button"
                        )
                        if menu_button.is_displayed():
                            logger.info("Clicking menu button to show book details")
                            menu_button.click()
                            time.sleep(1)

                            # Look for book title in the menu
                            try:
                                # Attempt to find About This Book option
                                about_book = self.driver.find_element(
                                    AppiumBy.XPATH, "//android.widget.TextView[@text='About This Book']"
                                )
                                if about_book.is_displayed():
                                    about_book.click()
                                    time.sleep(1)

                                    # Now try to find the book title in the About This Book popup
                                    try:
                                        title_element = self.driver.find_element(
                                            AppiumBy.ID, "com.amazon.kindle:id/about_book_title"
                                        )
                                        title = title_element.text
                                        logger.info(f"Found book title from About This Book popup: '{title}'")

                                        # Close the popup
                                        try:
                                            close_button = self.driver.find_element(
                                                AppiumBy.ID, "com.amazon.kindle:id/about_book_back_button"
                                            )
                                            close_button.click()
                                            time.sleep(0.5)
                                        except Exception:
                                            pass

                                        return title
                                    except NoSuchElementException:
                                        logger.info("Couldn't find title in About This Book popup")

                                    # Close the popup anyway if we couldn't find the title
                                    try:
                                        close_button = self.driver.find_element(
                                            AppiumBy.ID, "com.amazon.kindle:id/about_book_back_button"
                                        )
                                        close_button.click()
                                        time.sleep(0.5)
                                    except Exception:
                                        pass
                            except NoSuchElementException:
                                logger.info("Couldn't find About This Book option")
                    except NoSuchElementException:
                        logger.info("Couldn't find menu button")
            except Exception as e:
                logger.warning(f"Error getting title from menu: {e}")

            # If we got here, we couldn't find the title
            logger.warning("Could not determine book title")
            return None

        except Exception as e:
            logger.error(f"Error getting book title: {e}", exc_info=True)
            return None

    def navigate_back_to_library(self) -> bool:
        """Handle the reading state by navigating back to the library."""
        logger.info("Handling reading state - navigating back to library...")

        try:
            # Check for Item Removed dialog first
            if is_item_removed_dialog_visible(self.driver):
                logger.info("Item Removed dialog detected - handling it")
                if handle_item_removed_dialog(self.driver):
                    logger.info("Successfully handled Item Removed dialog")
                    # After handling this, we'll be back in library view, so return True
                    return True
                else:
                    logger.error("Failed to handle Item Removed dialog")
                    # Continue with other methods to try getting back to library

            # Check for and dismiss the comic book view
            if self.handle_comic_book_view():
                logger.info("Successfully dismissed comic book view during navigation")
                # Refresh page source for logging
                filepath = store_page_source(self.driver.page_source, "after_comic_book_dismiss")
                logger.info(f"Stored page source after comic book dismissal at: {filepath}")

            # First check if toolbar is already visible
            toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
            if toolbar_visible:
                logger.info("Toolbar already visible - proceeding to close book")
                return self._click_close_book_button()

            # Check for and dismiss bottom sheet if present
            bottom_sheet_visible, bottom_sheet = self._check_element_visibility(
                BOTTOM_SHEET_IDENTIFIERS, "bottom sheet dialog"
            )
            if bottom_sheet_visible:
                logger.info("Found bottom sheet dialog - attempting to dismiss")
                pill_visible, pill = self._check_element_visibility(
                    [BOTTOM_SHEET_IDENTIFIERS[1]], "bottom sheet pill"
                )
                if pill_visible:
                    pill.click()
                    logger.info("Clicked bottom sheet pill to dismiss")
                    time.sleep(1)

                    # Verify dismissal
                    still_visible, _ = self._check_element_visibility(
                        BOTTOM_SHEET_IDENTIFIERS, "bottom sheet dialog"
                    )
                    if still_visible:
                        logger.error("Bottom sheet dialog is still visible after dismissal")
                        return False
                    logger.info("Bottom sheet successfully dismissed")

            # Check for and dismiss "About this book" slideover
            about_book_visible, _ = self._check_element_visibility(
                ABOUT_BOOK_SLIDEOVER_IDENTIFIERS, "About this book slideover"
            )
            if about_book_visible:
                logger.info("Found 'About this book' slideover - attempting to dismiss")
                # Try finding the pill element to dismiss it
                pill_visible, pill = self._check_element_visibility(
                    [BOTTOM_SHEET_IDENTIFIERS[1]], "bottom sheet pill"
                )
                if pill_visible:
                    pill.click()
                    logger.info("Clicked pill to dismiss 'About this book' slideover")
                    time.sleep(1)
                else:
                    # If pill not found, try tapping near the top of the screen to dismiss
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    top_y = int(window_size["height"] * 0.10)  # Tap at approx. 10% from the top
                    self.driver.tap([(center_x, top_y)])
                    logger.info("Tapped near top of screen to dismiss 'About this book' slideover")
                    time.sleep(1)

                # Verify dismissal
                still_visible, _ = self._check_element_visibility(
                    ABOUT_BOOK_SLIDEOVER_IDENTIFIERS, "About this book slideover"
                )
                if still_visible:
                    logger.info("Slideover still visible - trying another approach")
                    # Try swiping down to dismiss
                    window_size = self.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    start_y = int(window_size["height"] * 0.3)
                    end_y = int(window_size["height"] * 0.7)
                    self.driver.swipe(center_x, start_y, center_x, end_y, 500)
                    logger.info("Swiped down to dismiss 'About this book' slideover")
                    time.sleep(1)

                    # Final verification
                    still_visible, _ = self._check_element_visibility(
                        ABOUT_BOOK_SLIDEOVER_IDENTIFIERS, "About this book slideover"
                    )
                    if still_visible:
                        logger.error("'About this book' slideover is still visible after dismissal attempts")
                    else:
                        logger.info("'About this book' slideover successfully dismissed")
                else:
                    logger.info("'About this book' slideover successfully dismissed")

            # Check for and dismiss full screen dialog using DialogHandler
            from views.common.dialog_handler import DialogHandler

            dialog_handler = DialogHandler(self.driver)

            if dialog_handler.check_for_viewing_full_screen_dialog():
                logger.info("Successfully handled 'Viewing full screen' dialog")
                time.sleep(0.5)  # Brief wait for dialog dismissal animation

            # Check for and handle "Go to that location/page?" dialog
            go_to_location_visible, message = self._check_element_visibility(
                GO_TO_LOCATION_DIALOG_IDENTIFIERS, "'Go to that location/page?' dialog"
            )
            if go_to_location_visible:
                logger.info("Found 'Go to that location/page?' dialog - clicking YES")
                yes_button_visible, yes_button = self._check_element_visibility(
                    LAST_READ_PAGE_DIALOG_BUTTONS, "YES button"
                )
                if yes_button_visible:
                    yes_button.click()
                    logger.info("Clicked YES button")
                    time.sleep(1)

            # Check for and dismiss Goodreads auto-update dialog
            goodreads_dialog_visible, _ = self._check_element_visibility(
                GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS, "Goodreads auto-update dialog"
            )
            if goodreads_dialog_visible:
                logger.info("Found Goodreads auto-update dialog - clicking NOT NOW")
                try:
                    not_now_button = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
                    )
                    if not_now_button.is_displayed():
                        not_now_button.click()
                        logger.info("Clicked NOT NOW button")
                        time.sleep(1)

                        # Verify dialog is gone
                        try:
                            not_now_button = self.driver.find_element(
                                AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
                            )
                            if not_now_button.is_displayed():
                                logger.error("Goodreads dialog still visible after clicking NOT NOW")
                            else:
                                logger.info("Successfully dismissed Goodreads dialog")
                        except NoSuchElementException:
                            logger.info("Successfully dismissed Goodreads dialog")

                except NoSuchElementException:
                    logger.error("NOT NOW button not found for Goodreads dialog", exc_info=True)
                except Exception as e:
                    logger.error(f"Error clicking NOT NOW button: {e}", exc_info=True)

            # Check for and dismiss Word Wise dialog
            word_wise_dialog_visible, _ = self._check_element_visibility(
                WORD_WISE_DIALOG_IDENTIFIERS, "Word Wise dialog"
            )
            if word_wise_dialog_visible:
                logger.info("Found Word Wise dialog - clicking NO THANKS")
                no_thanks_button_visible, no_thanks_button = self._check_element_visibility(
                    WORD_WISE_NO_THANKS_BUTTON, "NO THANKS button"
                )

                if no_thanks_button_visible:
                    no_thanks_button.click()
                    logger.info("Clicked NO THANKS button")
                    time.sleep(1)

                    # Verify dialog is gone
                    still_visible, _ = self._check_element_visibility(
                        WORD_WISE_DIALOG_IDENTIFIERS, "Word Wise dialog"
                    )
                    if still_visible:
                        logger.error("Word Wise dialog still visible after clicking NO THANKS")
                    else:
                        logger.info("Successfully dismissed Word Wise dialog")

                else:
                    logger.error("NO THANKS button not found for Word Wise dialog")

            # Now try to make toolbar visible if it isn't already
            return self._show_toolbar_and_close_book()

        except Exception as e:
            logger.error(f"Error handling reading state: {e}", exc_info=True)
            return False

    def _show_toolbar_and_close_book(self):
        """Show the toolbar by tapping and then close the book."""
        # Get screen dimensions
        window_size = self.driver.get_window_size()
        center_x = window_size["width"] // 2
        tap_y = window_size["height"] // 2

        # Check if we're looking at the Goodreads auto-update dialog
        goodreads_dialog_visible, _ = self._check_element_visibility(
            GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS, "Goodreads auto-update dialog"
        )
        if goodreads_dialog_visible:
            logger.info("Found Goodreads auto-update dialog before showing toolbar - dismissing it first")
            try:
                not_now_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
                )
                if not_now_button.is_displayed():
                    not_now_button.click()
                    logger.info("Clicked NOT NOW button")
                    time.sleep(1)
                    store_page_source(self.driver.page_source, "goodreads_dialog_dismissed_toolbar")
            except NoSuchElementException:
                logger.error("NOT NOW button not found for Goodreads dialog", exc_info=True)
            except Exception as e:
                logger.error(f"Error clicking NOT NOW button: {e}", exc_info=True)

        # Check if we're looking at the Word Wise dialog
        word_wise_dialog_visible, _ = self._check_element_visibility(
            WORD_WISE_DIALOG_IDENTIFIERS, "Word Wise dialog"
        )
        if word_wise_dialog_visible:
            logger.info("Found Word Wise dialog before showing toolbar - dismissing it first")
            no_thanks_button_visible, no_thanks_button = self._check_element_visibility(
                WORD_WISE_NO_THANKS_BUTTON, "NO THANKS button"
            )

            if no_thanks_button_visible:
                no_thanks_button.click()
                logger.info("Clicked NO THANKS button")
                time.sleep(1)
                store_page_source(self.driver.page_source, "word_wise_dialog_dismissed_toolbar")
            else:
                logger.error("NO THANKS button not found for Word Wise dialog")

        # First check if toolbar is already visible
        toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
        if toolbar_visible:
            logger.info("Toolbar is already visible - proceeding to close book")
            return self._click_close_book_button()

        # Try alternate toolbar checking with toolbar strategies from interaction_strategies.py
        toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_STRATEGIES, "toolbar (alt check)")
        if toolbar_visible:
            logger.info("Toolbar is already visible (alt check) - proceeding to close book")
            return self._click_close_book_button()

        # Try multiple different tap patterns to show the toolbar
        max_attempts = 3
        for attempt in range(max_attempts):
            logger.info(f"Attempting to show toolbar (attempt {attempt + 1}/{max_attempts})")

            # Try different tap pattern based on attempt number
            if attempt == 0:
                # First try: Simple center tap
                self.driver.tap([(center_x, tap_y)])
                logger.info(f"Tapped center at ({center_x}, {tap_y})")
            elif attempt == 1:
                # Second try: Tap near the top of the page
                top_y = int(window_size["height"] * 0.25)  # 25% from top
                self.driver.tap([(center_x, top_y)])
                logger.info(f"Tapped near top at ({center_x}, {top_y})")
            else:
                # Third try: Try a double tap
                self.driver.tap([(center_x, tap_y)])
                time.sleep(0.1)  # Brief pause between taps
                self.driver.tap([(center_x, tap_y)])
                logger.info(f"Double-tapped center at ({center_x}, {tap_y})")

            # Generous wait for toolbar to appear
            time.sleep(0.5)

            # Check if toolbar appeared using multiple strategies
            toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
            if toolbar_visible:
                logger.info(f"Toolbar successfully appeared on attempt {attempt + 1}")
                return self._click_close_book_button()

            # Also check with alternative toolbar identifiers
            toolbar_visible, _ = self._check_element_visibility(
                READING_TOOLBAR_STRATEGIES, "toolbar (alt check)"
            )
            if toolbar_visible:
                logger.info(f"Toolbar successfully appeared (alt check) on attempt {attempt + 1}")
                return self._click_close_book_button()

            # Check for and handle interrupting dialogs
            # Check for Goodreads dialog
            goodreads_dialog_visible, _ = self._check_element_visibility(
                GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS, "Goodreads auto-update dialog"
            )
            if goodreads_dialog_visible:
                logger.info("Found Goodreads auto-update dialog after tapping - dismissing it")
                try:
                    not_now_button = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
                    )
                    if not_now_button.is_displayed():
                        not_now_button.click()
                        logger.info("Clicked NOT NOW button")
                        time.sleep(1)
                        store_page_source(
                            self.driver.page_source, "goodreads_dialog_dismissed_during_toolbar"
                        )

                        # Try again immediately to show toolbar after dismissing dialog
                        self.driver.tap([(center_x, tap_y)])
                        time.sleep(0.5)

                        # Check if toolbar appeared
                        toolbar_visible, _ = self._check_element_visibility(
                            READING_TOOLBAR_IDENTIFIERS, "toolbar"
                        )
                        if toolbar_visible:
                            logger.info("Toolbar appeared after dismissing Goodreads dialog")
                            return self._click_close_book_button()

                        # Also check with alternative toolbar identifiers
                        toolbar_visible, _ = self._check_element_visibility(
                            READING_TOOLBAR_STRATEGIES, "toolbar (alt check)"
                        )
                        if toolbar_visible:
                            logger.info("Toolbar appeared (alt check) after dismissing Goodreads dialog")
                            return self._click_close_book_button()
                except NoSuchElementException:
                    logger.error("NOT NOW button not found for Goodreads dialog", exc_info=True)
                except Exception as e:
                    logger.error(f"Error clicking NOT NOW button: {e}", exc_info=True)

            # Check for Word Wise dialog
            word_wise_dialog_visible, _ = self._check_element_visibility(
                WORD_WISE_DIALOG_IDENTIFIERS, "Word Wise dialog"
            )
            if word_wise_dialog_visible:
                logger.info("Found Word Wise dialog after tapping - dismissing it")
                no_thanks_button_visible, no_thanks_button = self._check_element_visibility(
                    WORD_WISE_NO_THANKS_BUTTON, "NO THANKS button"
                )

                if no_thanks_button_visible:
                    no_thanks_button.click()
                    logger.info("Clicked NO THANKS button")
                    time.sleep(1)
                    store_page_source(self.driver.page_source, "word_wise_dialog_dismissed_during_toolbar")

                    # Try again immediately to show toolbar after dismissing dialog
                    self.driver.tap([(center_x, tap_y)])
                    time.sleep(0.5)

                    # Check if toolbar appeared
                    toolbar_visible, _ = self._check_element_visibility(
                        READING_TOOLBAR_IDENTIFIERS, "toolbar"
                    )
                    if toolbar_visible:
                        logger.info("Toolbar appeared after dismissing Word Wise dialog")
                        return self._click_close_book_button()

                    # Also check with alternative toolbar identifiers
                    toolbar_visible, _ = self._check_element_visibility(
                        READING_TOOLBAR_STRATEGIES, "toolbar (alt check)"
                    )
                    if toolbar_visible:
                        logger.info("Toolbar appeared (alt check) after dismissing Word Wise dialog")
                        return self._click_close_book_button()
                else:
                    logger.error("NO THANKS button not found for Word Wise dialog")

            # Check for placemark ribbon which could be blocking our taps
            placemark_visible, _ = self._check_element_visibility(PLACEMARK_IDENTIFIERS, "placemark ribbon")
            if placemark_visible:
                logger.info("Found placemark ribbon - will try tapping elsewhere")
                # Try tapping in a different location
                self.driver.tap([(center_x, int(window_size["height"] * 0.75))])  # Lower on screen
                time.sleep(0.5)

                # Check if toolbar appeared
                toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
                if toolbar_visible:
                    logger.info("Toolbar appeared after tapping away from placemark")
                    return self._click_close_book_button()

            # If still nothing, try checking for close book button directly
            # Sometimes the toolbar is there but not detected with our standard checks
            close_visible, close_button = self._check_element_visibility(
                CLOSE_BOOK_STRATEGIES, "close book button"
            )
            if close_visible:
                logger.info("Found close book button directly without toolbar visibility check")
                return self._click_close_book_button()

            if attempt < max_attempts - 1:
                logger.info("Toolbar not visible, will try again with different tap strategy...")
                # Slightly longer wait between attempts
                time.sleep(0.5)

        # As a last resort attempt, try directly going back using the system back button
        logger.warning("Could not show toolbar after all attempts - trying system back button as fallback")
        try:
            # Press back button
            self.driver.press_keycode(4)  # Android back button keycode
            time.sleep(1)

            # Check if we're still in reading view
            reading_view = False
            for strategy, locator in READING_VIEW_IDENTIFIERS[:3]:  # Use just the first few identifiers
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        reading_view = True
                        break
                except NoSuchElementException:
                    continue

            if not reading_view:
                logger.info("Successfully exited reading view using system back button")
                return True
        except Exception as e:
            logger.error(f"Error using system back button: {e}", exc_info=True)

        logger.error("Failed to make toolbar visible or exit reading view after all attempts")
        return False

    def handle_comic_book_view(self) -> bool:
        """Check for and dismiss the comic book view by clicking the X button.

        Returns:
            bool: True if successfully handled the comic book view, False if not found or error occurred.
        """
        try:
            # Check if we're in the comic book view
            comic_book_view_visible = False
            for strategy, locator in COMIC_BOOK_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        comic_book_view_visible = True
                        logger.info(f"Found comic book view with {strategy}: {locator}")
                        break
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.warning(f"Error checking for comic book view: {e}")

            if not comic_book_view_visible:
                return False

            logger.info("Comic book view detected - looking for X button to dismiss")

            # Find and click the X button
            x_button_found = False
            for strategy, locator in COMIC_BOOK_X_BUTTON:
                try:
                    x_button = self.driver.find_element(strategy, locator)
                    if x_button and x_button.is_displayed():
                        logger.info(f"Found comic book X button with {strategy}: {locator}")
                        x_button.click()
                        logger.info("Clicked X button to dismiss comic book view")
                        x_button_found = True
                        time.sleep(0.5)  # Wait for view to dismiss
                        break
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.warning(f"Error interacting with comic book X button: {e}")

            if not x_button_found:
                logger.warning("Could not find X button in comic book view")
                return False

            # Verify the view was dismissed
            try:
                still_visible = False
                for strategy, locator in COMIC_BOOK_VIEW_IDENTIFIERS:
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            still_visible = True
                            break
                    except NoSuchElementException:
                        continue

                if still_visible:
                    logger.warning("Comic book view is still visible after clicking X button")
                    return False
                else:
                    logger.info("Successfully dismissed comic book view")
                    return True
            except Exception as e:
                logger.error(f"Error verifying comic book view dismissal: {e}", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"Error handling comic book view: {e}", exc_info=True)
            return False

    def check_and_handle_tutorial_message(self) -> bool:
        """Check for and handle the 'Tap the middle of the page' tutorial message.

        Returns:
            bool: True if successfully handled the tutorial message, False if not found.
        """
        try:
            # Check if tutorial message is visible
            tutorial_visible = False
            for strategy, locator in TUTORIAL_MESSAGE_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        tutorial_visible = True
                        logger.info(f"Found tutorial message: {element.text}")
                        break
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for tutorial message: {e}")

            if not tutorial_visible:
                return False

            logger.info("Tutorial message detected - will tap to dismiss it")

            # Check if we should open the style dialog or just dismiss
            if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "profile_manager"):
                profile_manager = self.driver.automator.profile_manager
                sindarin_email = get_sindarin_email()

                # Check if the user has the style dialog preference set
                if sindarin_email:
                    show_style_dialog = profile_manager.get_style_setting(
                        "show_style_dialog", email=sindarin_email
                    )

                    if show_style_dialog is False:
                        # User doesn't want style dialog, so we need to tap twice
                        # First tap opens toolbar, second tap closes it
                        logger.info("User has style dialog disabled - will tap twice to dismiss tutorial")

                        # Get screen dimensions
                        window_size = self.driver.get_window_size()
                        center_x = window_size["width"] // 2
                        center_y = window_size["height"] // 2

                        # First tap to open toolbar
                        self.driver.tap([(center_x, center_y)])
                        logger.info("First tap to open toolbar")
                        time.sleep(0.5)

                        # Second tap to close toolbar and get back to reading view
                        self.driver.tap([(center_x, center_y)])
                        logger.info("Second tap to close toolbar and dismiss tutorial")
                        time.sleep(0.5)

                        # Verify tutorial is gone
                        tutorial_still_visible = False
                        for strategy, locator in TUTORIAL_MESSAGE_IDENTIFIERS:
                            try:
                                element = self.driver.find_element(strategy, locator)
                                if element and element.is_displayed():
                                    tutorial_still_visible = True
                                    break
                            except NoSuchElementException:
                                continue

                        if tutorial_still_visible:
                            logger.warning("Tutorial message still visible after double tap")
                            return False
                        else:
                            logger.info("Successfully dismissed tutorial message")
                            return True
                    else:
                        # User wants style dialog or hasn't set preference
                        logger.info("User has style dialog enabled - single tap will open style dialog")

                        # Single tap to open toolbar/style dialog
                        window_size = self.driver.get_window_size()
                        center_x = window_size["width"] // 2
                        center_y = window_size["height"] // 2

                        self.driver.tap([(center_x, center_y)])
                        logger.info("Tapped to open toolbar and dismiss tutorial")
                        time.sleep(0.5)

                        # Verify tutorial is gone
                        tutorial_still_visible = False
                        for strategy, locator in TUTORIAL_MESSAGE_IDENTIFIERS:
                            try:
                                element = self.driver.find_element(strategy, locator)
                                if element and element.is_displayed():
                                    tutorial_still_visible = True
                                    break
                            except NoSuchElementException:
                                continue

                        if tutorial_still_visible:
                            logger.warning("Tutorial message still visible after tap")
                            return False
                        else:
                            logger.info("Successfully dismissed tutorial message and opened toolbar")
                            return True

            # Fallback: just do a single tap if we can't determine preference
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            center_y = window_size["height"] // 2

            self.driver.tap([(center_x, center_y)])
            logger.info("Tapped to dismiss tutorial message")
            time.sleep(0.5)

            return True

        except Exception as e:
            logger.error(f"Error handling tutorial message: {e}", exc_info=True)
            return False

    def _click_close_book_button(self):
        """Find and click the close book button."""
        close_visible, close_button = self._check_element_visibility(
            CLOSE_BOOK_STRATEGIES, "close book button"
        )
        if close_visible:
            close_button.click()
            logger.info("Clicked close book button")

            # Add debug page source dump after clicking close button
            filepath = store_page_source(self.driver.page_source, "failed_transition")
            logger.info(f"Stored page source after closing book at: {filepath}")

            # Clear the actively reading title when closing the book
            try:
                sindarin_email = get_sindarin_email()
                if sindarin_email:
                    self.driver.automator.profile_manager.save_style_setting(
                        "actively_reading_title", None, email=sindarin_email
                    )
                    logger.info("Cleared actively reading title")
            except Exception as e:
                logger.error(f"Error clearing actively reading title: {e}", exc_info=True)

            return True

        logger.error("Could not find close book button")
        return False
