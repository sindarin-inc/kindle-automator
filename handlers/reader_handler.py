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
from views.reading.interaction_strategies import (
    ABOUT_BOOK_SLIDEOVER_IDENTIFIERS,
    BOTTOM_SHEET_IDENTIFIERS,
    CLOSE_BOOK_STRATEGIES,
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
)
from views.reading.view_strategies import (
    BLACK_BG_IDENTIFIERS,
    GO_TO_LOCATION_DIALOG_IDENTIFIERS,
    GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS,
    GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS,
    LAST_READ_PAGE_DIALOG_IDENTIFIERS,
    LAYOUT_TAB_IDENTIFIERS,
    PAGE_NAVIGATION_ZONES,
    PAGE_NUMBER_IDENTIFIERS,
    PLACEMARK_IDENTIFIERS,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
    WHITE_BG_IDENTIFIERS,
)

logger = logging.getLogger(__name__)


class ReaderHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def handle_download_limit_dialog(self) -> bool:
        """Handle the 'Download Limit Reached' dialog by selecting the top device and clicking 'Remove and Download'.

        Returns:
            bool: True if successfully handled the dialog, False otherwise.
        """
        try:
            # Store initial page source for debugging
            store_page_source(self.driver.page_source, "download_limit_initial")

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
                return False

            # Store the page source for debugging
            store_page_source(self.driver.page_source, "download_limit_dialog_found")

            # Find and tap the first device in the list - try multiple methods with longer wait times
            first_device_tapped = False

            # Method 1: Direct targeting of first device LinearLayout
            for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_FIRST_DEVICE):
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        element.click()
                        logger.info(f"Tapped first device method 1 using #{idx}: {strategy}={locator}")
                        first_device_tapped = True
                        time.sleep(1.5)  # Longer wait for UI update
                        break
                except NoSuchElementException:
                    logger.debug(f"First device #{idx} not found")
                except Exception as e:
                    logger.warning(f"Error tapping first device #{idx}: {e}")

            # Method 2: Try to find and click CheckedTextView directly
            if not first_device_tapped:
                logger.info("Trying CheckedTextView direct approach")
                try:
                    # Try to get all CheckedTextViews
                    for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_CHECKEDTEXTVIEW):
                        try:
                            # First try to get direct element
                            device = self.driver.find_element(strategy, locator)
                            if device and device.is_displayed():
                                device.click()
                                logger.info(f"Tapped checked text view #{idx} directly")
                                first_device_tapped = True
                                time.sleep(1.5)
                                break
                        except NoSuchElementException:
                            # Try to get all elements of this type
                            try:
                                devices = self.driver.find_elements(strategy, locator)
                                if devices and len(devices) > 0:
                                    # Click the first device in the list
                                    devices[0].click()
                                    logger.info(
                                        f"Tapped first of {len(devices)} checked text views from collection #{idx}"
                                    )
                                    first_device_tapped = True
                                    time.sleep(1.5)
                                    break
                            except Exception as e_list:
                                logger.debug(f"Error with device collection #{idx}: {e_list}")
                        except Exception as e:
                            logger.warning(f"Error with direct checked text view #{idx}: {e}")
                except Exception as e:
                    logger.warning(f"General error in CheckedTextView approach: {e}")

            # Method 3: Find device list and tap in top area
            if not first_device_tapped:
                logger.info("Trying device list area approach")
                for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_DEVICE_LIST):
                    try:
                        device_list = self.driver.find_element(strategy, locator)
                        if device_list and device_list.is_displayed():
                            # Get location and size to tap in upper area
                            location = device_list.location
                            size = device_list.size

                            # Calculate tap point in upper portion of list
                            x = location["x"] + (size["width"] // 2)
                            y = location["y"] + 70  # Tap higher in list

                            # Try tapping
                            self.driver.tap([(x, y)])
                            logger.info(f"Tapped at ({x}, {y}) in device list #{idx} upper area")
                            first_device_tapped = True
                            time.sleep(1.5)
                            break
                    except NoSuchElementException:
                        logger.debug(f"Device list #{idx} not found for area tap")
                    except Exception as e:
                        logger.warning(f"Error with area tap #{idx}: {e}")

            # If we still couldn't tap a device, we'll try to tap button anyway
            if not first_device_tapped:
                logger.warning("Could not tap any device after multiple methods. Will try button anyway")

            # Store state after device selection
            store_page_source(self.driver.page_source, "download_limit_after_device_tap")

            # Find and tap the "Remove and Download" button with retry logic
            remove_button_tapped = False

            # Method 1: Standard button search and click
            for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_REMOVE_BUTTON):
                try:
                    button = self.driver.find_element(strategy, locator)
                    if button and button.is_displayed():
                        # Check if it's enabled
                        button_enabled = False
                        try:
                            button_enabled = button.is_enabled()
                        except:
                            try:
                                # Fallback to attribute
                                enabled_attr = button.get_attribute("enabled")
                                button_enabled = enabled_attr == "true"
                            except:
                                # Last resort - just assume it might work
                                button_enabled = True
                                logger.warning("Couldn't determine button state, attempting click anyway")

                        if button_enabled:
                            button.click()
                            logger.info(f"Tapped enabled Remove/Download button #{idx}")
                            remove_button_tapped = True
                            time.sleep(3)  # Longer wait for download start
                            break
                        else:
                            logger.warning(f"Button #{idx} found but disabled")
                except NoSuchElementException:
                    logger.debug(f"Remove/Download button #{idx} not found")
                except Exception as e:
                    logger.warning(f"Error with Remove/Download button #{idx}: {e}")

            # Method 2: Try one more round of device selection then button tap
            if not remove_button_tapped:
                logger.info("Button not tapped. Trying one more round of device+button...")

                # Try all device strategies again with more forceful clicking
                for idx, (strategy, locator) in enumerate(DOWNLOAD_LIMIT_FIRST_DEVICE):
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element and element.is_displayed():
                            # Double tap with longer wait
                            element.click()
                            time.sleep(0.5)
                            element.click()  # Double tap
                            logger.info(f"Double-tapped device #{idx} in second attempt")
                            time.sleep(2)

                            # Now try all buttons again
                            for btn_idx, (btn_strategy, btn_locator) in enumerate(
                                DOWNLOAD_LIMIT_REMOVE_BUTTON
                            ):
                                try:
                                    button = self.driver.find_element(btn_strategy, btn_locator)
                                    if button.is_displayed() and button.is_enabled():
                                        button.click()
                                        logger.info(f"Tapped button #{btn_idx} after second device selection")
                                        remove_button_tapped = True
                                        time.sleep(3)
                                        break
                                except:
                                    continue

                            if remove_button_tapped:
                                break
                    except:
                        continue

            # Final state capture
            store_page_source(self.driver.page_source, "download_limit_after_button_tap")

            if not remove_button_tapped:
                logger.error("Could not tap the Remove and Download button after all attempts")
                # Return false since we couldn't tap the button
                return False

            # Wait for reading view to appear after download
            logger.info("Remove button tapped successfully, waiting for download...")
            time.sleep(5)  # Longer wait for download to start showing

            return True

        except Exception as e:
            logger.error(f"Error handling download limit dialog: {e}")
            store_page_source(self.driver.page_source, "download_limit_error")
            return False

    def open_book(self, book_title: str, show_placemark: bool = False) -> bool:
        """Open a book in the library and wait for reading view to load.

        Args:
            book_title (str): Title of the book to open.
            show_placemark (bool): Whether to tap to display the placemark ribbon.
                                  Default is False (don't show placemark).

        Returns:
            bool: True if book was successfully opened, False otherwise.
        """
        logger.info(f"Starting reading flow for book: {book_title}")

        if (
            hasattr(self.driver, "automator")
            and hasattr(self.driver.automator, "state_machine")
            and hasattr(self.driver.automator.state_machine, "library_handler")
        ):
            library_handler = self.driver.automator.state_machine.library_handler
            # Call open_book and capture the result
            open_book_result = library_handler.open_book(book_title)

            # Check for "Title Not Available" dialog result
            if open_book_result == "title_not_available":
                logger.error(f"Title Not Available dialog detected for book: {book_title}")
                # Set a special error flag on the automator for the response_handler to detect
                if hasattr(self.driver, "automator"):
                    self.driver.automator.title_not_available_error = {
                        "error": "Title Not Available",
                        "book_title": book_title,
                    }
                return False
            # Check for general failure
            elif not open_book_result:
                logger.error(f"Failed to open book: {book_title}")
                return False
        else:
            logger.error(
                f"Cannot open book: {book_title} - library_handler not available through driver.automator.state_machine"
            )
            return False

        logger.info(f"Successfully navigated away from library view")

        # Wait for the reading view to appear
        try:
            # Custom wait condition to check for any of the reading view identifiers
            # or for the download limit dialog
            def reading_view_or_download_limit_present(driver):
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
                        except:
                            pass

                    remove_button = None
                    for btn_strategy, btn_locator in DOWNLOAD_LIMIT_REMOVE_BUTTON:
                        try:
                            el = driver.find_element(btn_strategy, btn_locator)
                            if el.is_displayed():
                                remove_button = True
                                break
                        except:
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
                            logger.info(f"Reading view detected with identifier #{idx}: {strategy}")
                            return "reading_view"
                    except NoSuchElementException:
                        pass
                    except Exception as e:
                        logger.debug(f"Error checking reading view identifier #{idx}: {e}")

                # Check for last read page dialog as a separate detectable state
                try:
                    last_read = driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Go to that page?')]"
                    )
                    if last_read and last_read.is_displayed():
                        logger.info("Last Read Page dialog detected during open_book")
                        # We'll treat this as a reading_view since we have handling for it later
                        return "reading_view"
                except:
                    pass

                return False

            # Wait for either reading view element or download limit dialog to appear
            result = WebDriverWait(self.driver, 10).until(reading_view_or_download_limit_present)

            # Handle download limit dialog if it appeared
            if result == "download_limit":
                logger.info("Download Limit dialog detected - handling it")
                if self.handle_download_limit_dialog():
                    logger.info("Successfully handled Download Limit dialog, waiting for reading view")
                    # Now wait for the reading view after handling the dialog
                    try:

                        def reading_view_present(driver):
                            for strategy in READING_VIEW_IDENTIFIERS:
                                try:
                                    element = driver.find_element(strategy[0], strategy[1])
                                    if element:
                                        logger.info(f"Reading view detected with identifier: {strategy}")
                                        return True
                                except NoSuchElementException:
                                    pass
                            return False

                        # Wait for reading view now that download limit is handled
                        try:
                            WebDriverWait(self.driver, 30).until(
                                reading_view_present
                            )  # Longer timeout for download
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
                                except:
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

                                    # Retry opening the book one more time
                                    if (
                                        hasattr(self.driver, "automator")
                                        and hasattr(self.driver.automator, "state_machine")
                                        and hasattr(self.driver.automator.state_machine, "library_handler")
                                    ):
                                        library_handler = self.driver.automator.state_machine.library_handler
                                        if library_handler.open_book(book_title):
                                            logger.info(
                                                "Successfully reopened book after download limit handling"
                                            )
                                        else:
                                            logger.error(
                                                f"Failed to reopen book: {book_title} after download limit handling"
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
                                        logger.error("Failed to detect reading view after reopening book")
                                        store_page_source(
                                            self.driver.page_source, "failed_reopen_after_download_limit"
                                        )
                            except Exception as back_to_lib_e:
                                logger.error(f"Error checking if back at library: {back_to_lib_e}")

                            # If we're still here, we failed
                            logger.error("Failed to detect reading view after handling download limit")
                            store_page_source(
                                self.driver.page_source, "failed_to_detect_reading_view_after_download"
                            )
                            return False
                    except Exception as e:
                        logger.error(f"Error while waiting for reading view after download limit: {e}")
                        store_page_source(self.driver.page_source, "error_waiting_after_download_limit")
                        return False
                else:
                    logger.error("Failed to handle Download Limit dialog")
                    return False
            else:
                logger.info("Reading view detected successfully")
        except TimeoutException:
            logger.error("Failed to detect reading view or download limit dialog after 10 seconds")
            store_page_source(self.driver.page_source, "failed_to_detect_reading_view_or_download_limit")
            return False
        except Exception as e:
            logger.error(f"Error while waiting for reading view or download limit: {e}")
            store_page_source(self.driver.page_source, "error_waiting_for_reading_view_or_download_limit")
            return False

        # Check for fullscreen dialog immediately without a long wait
        try:
            # Use the existing identifiers from view_strategies.py
            dialog_present = False
            for strategy, locator in READING_VIEW_FULL_SCREEN_DIALOG:
                try:
                    dialog = self.driver.find_element(strategy, locator)
                    if dialog.is_displayed():
                        dialog_present = True
                        logger.info(f"Detected full screen dialog with {strategy}: {locator}")
                        break
                except NoSuchElementException:
                    continue

            if dialog_present:
                # Try to find the "Got it" button using defined strategies
                for strategy, locator in FULL_SCREEN_DIALOG_GOT_IT:
                    try:
                        got_it_button = self.driver.find_element(strategy, locator)
                        if got_it_button.is_displayed():
                            got_it_button.click()
                            logger.info(f"Clicked 'Got it' button with {strategy}: {locator}")

                            # Verify the dialog was dismissed
                            try:
                                WebDriverWait(self.driver, 2).until_not(
                                    EC.presence_of_element_located(READING_VIEW_FULL_SCREEN_DIALOG[0])
                                )
                                logger.info("Full screen dialog successfully dismissed")
                            except TimeoutException:
                                logger.warning(
                                    "Full screen dialog may not have closed properly after clicking 'Got it'"
                                )

                            break
                    except NoSuchElementException:
                        continue
        except NoSuchElementException:
            # Dialog not present, continue immediately
            logger.info("No full screen dialog detected, continuing immediately")
        except TimeoutException:
            logger.warning("Full screen dialog may not have closed properly after clicking 'Got it'")
        except Exception as e:
            logger.warning(f"Error handling full screen dialog: {e}")

        # We already confirmed the reading view is loaded above, so no need for additional waiting
        # Just check for page content container which should be available immediately
        try:
            page_content = self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/reader_content_container"
            )
            if page_content:
                logger.info("Page content container is ready")
        except NoSuchElementException:
            logger.warning("Page content container not immediately found - app may still be loading content")
        except Exception as e:
            logger.error(f"Error checking for page content: {e}")
            # Continue anyway as we already confirmed we're in reading view

        # Log the page source
        filepath = store_page_source(self.driver.page_source, "reading_view")
        logger.info(f"Stored reading view page source at: {filepath}")

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
                        logger.error(f"Error clicking bottom sheet pill: {e}")
                else:
                    logger.info("Bottom sheet dialog found but not visible")
            except NoSuchElementException:
                logger.info("No bottom sheet dialog found - continuing")
            except Exception as e:
                logger.error(f"Error checking for bottom sheet dialog: {e}")

        except Exception as e:
            logger.error(f"Unexpected error handling bottom sheet: {e}")

        # Check for and handle "last read page" dialog
        try:
            store_page_source(self.driver.page_source, "last_read_page_dialog")
            for strategy, locator in LAST_READ_PAGE_DIALOG_IDENTIFIERS:
                try:
                    message = self.driver.find_element(strategy, locator)
                    if message.is_displayed() and (
                        "You are currently on page" in message.text
                        or "You are currently at location" in message.text
                    ):
                        logger.info("Found 'last read page/location' dialog - clicking YES")
                        for btn_strategy, btn_locator in LAST_READ_PAGE_DIALOG_BUTTONS:
                            try:
                                yes_button = self.driver.find_element(btn_strategy, btn_locator)
                                if yes_button.is_displayed():
                                    yes_button.click()
                                    logger.info("Clicked YES button")
                                    break
                            except NoSuchElementException:
                                continue
                        break
                except NoSuchElementException:
                    continue
        except Exception as e:
            logger.error(f"Error handling 'last read page/location' dialog: {e}")

        # Check for and handle "Go to that location?" dialog
        try:
            store_page_source(self.driver.page_source, "go_to_location_dialog")
            for strategy, locator in GO_TO_LOCATION_DIALOG_IDENTIFIERS:
                try:
                    message = self.driver.find_element(strategy, locator)
                    if message.is_displayed() and (
                        "Go to that location?" in message.text or "Go to that page?" in message.text
                    ):
                        logger.info("Found 'Go to that location/page?' dialog - clicking YES")
                        for (
                            btn_strategy,
                            btn_locator,
                        ) in LAST_READ_PAGE_DIALOG_BUTTONS:  # Reuse the same buttons as last read page dialog
                            try:
                                yes_button = self.driver.find_element(btn_strategy, btn_locator)
                                if yes_button.is_displayed():
                                    yes_button.click()
                                    logger.info("Clicked YES button")
                                    break
                            except NoSuchElementException:
                                continue
                        break
                except NoSuchElementException:
                    continue
        except Exception as e:
            logger.error(f"Error handling 'Go to that location/page?' dialog: {e}")

        # Check for and dismiss Goodreads auto-update dialog
        try:
            # Store the page source before checking for the Goodreads dialog
            store_page_source(self.driver.page_source, "goodreads_autoupdate_dialog")

            # Check if the Goodreads dialog is present
            dialog_present = False
            for strategy, locator in GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS:
                try:
                    dialog = self.driver.find_element(strategy, locator)
                    if dialog.is_displayed():
                        dialog_present = True
                        logger.info("Found Goodreads auto-update dialog")
                        break
                except NoSuchElementException:
                    continue

            if dialog_present:
                # Find and click the "NOT NOW" button
                not_now_button = self.driver.find_element(
                    *GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS[1]  # Index 1 is the "NOT NOW" button
                )
                if not_now_button.is_displayed():
                    logger.info("Clicking 'NOT NOW' button on Goodreads auto-update dialog")
                    not_now_button.click()

                    # Verify dialog is gone
                    try:
                        not_now_button = self.driver.find_element(*GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS[1])
                        if not_now_button.is_displayed():
                            logger.error("Goodreads dialog still visible after clicking Not Now")
                            return False
                    except NoSuchElementException:
                        logger.info("Successfully dismissed Goodreads dialog")

                    filepath = store_page_source(self.driver.page_source, "goodreads_dialog_dismissed")
                    logger.info(f"Stored Goodreads dialog dismissed page source at: {filepath}")
        except NoSuchElementException:
            logger.info("No Goodreads auto-update dialog found - continuing")
        except Exception as e:
            logger.error(f"Error handling Goodreads dialog: {e}")

        # Check for and dismiss Word Wise dialog
        try:
            # Store the page source before checking for the Word Wise dialog
            store_page_source(self.driver.page_source, "word_wise_dialog")

            # Check if the Word Wise dialog is present
            dialog_present = False
            for strategy, locator in WORD_WISE_DIALOG_IDENTIFIERS:
                try:
                    dialog = self.driver.find_element(strategy, locator)
                    if dialog.is_displayed():
                        dialog_present = True
                        logger.info("Found Word Wise dialog")
                        break
                except NoSuchElementException:
                    continue

            if dialog_present:
                # Find and click the "NO THANKS" button
                for strategy, locator in WORD_WISE_NO_THANKS_BUTTON:
                    try:
                        no_thanks_button = self.driver.find_element(strategy, locator)
                        if no_thanks_button.is_displayed():
                            logger.info("Clicking 'NO THANKS' button on Word Wise dialog")
                            no_thanks_button.click()

                            # Verify dialog is gone
                            try:
                                # Check if the Word Wise dialog is still present
                                still_visible = False
                                for dialog_strategy, dialog_locator in WORD_WISE_DIALOG_IDENTIFIERS:
                                    try:
                                        dialog = self.driver.find_element(dialog_strategy, dialog_locator)
                                        if dialog.is_displayed():
                                            still_visible = True
                                            break
                                    except NoSuchElementException:
                                        continue

                                if still_visible:
                                    logger.error("Word Wise dialog still visible after clicking No Thanks")
                                    return False
                                else:
                                    logger.info("Successfully dismissed Word Wise dialog")
                            except Exception as verify_e:
                                logger.error(f"Error verifying Word Wise dialog dismissal: {verify_e}")

                            filepath = store_page_source(
                                self.driver.page_source, "word_wise_dialog_dismissed"
                            )
                            logger.info(f"Stored Word Wise dialog dismissed page source at: {filepath}")
                            break
                    except NoSuchElementException:
                        continue
        except NoSuchElementException:
            logger.info("No Word Wise dialog found - continuing")
        except Exception as e:
            logger.error(f"Error handling Word Wise dialog: {e}")

        # Check for and dismiss "About this book" slideover
        try:
            store_page_source(self.driver.page_source, "about_book_slideover_check")
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
            logger.error(f"Error handling 'About this book' slideover: {e}")

        # Get current page
        current_page = self.get_current_page()
        logger.info(f"Current page: {current_page}")
        logger.info("Successfully opened book and captured first page")

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
                logger.error(f"Error showing placemark: {e}")
        else:
            logger.info("Placemark mode disabled - skipping center tap")

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
            logger.error(f"Error getting page number: {e}")
            return None

    def capture_page_screenshot(self):
        """Capture a screenshot of the current page"""
        try:
            logger.info("Capturing page screenshot...")

            # Take screenshot using adb for better quality
            result = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                check=True,
                capture_output=True,
            )

            image = Image.open(BytesIO(result.stdout))
            screenshot_path = os.path.join(self.screenshots_dir, "reading_page.png")
            image.save(screenshot_path)
            logger.info(f"Successfully saved page screenshot to {screenshot_path}")
            return True

        except Exception as e:
            logger.error(f"Error capturing page screenshot: {e}")
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
                except:
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
            logger.error(f"Error turning page forward: {e}")
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
                    logger.error(f"Failed to delete screenshot {screenshot_path}: {del_e}")

            except Exception as e:
                logger.error(f"Error processing OCR: {e}")
                error_msg = str(e)

            return ocr_text, error_msg

        except Exception as e:
            logger.error(f"Error taking screenshot for OCR: {e}")
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
            logger.error(f"Error during next page preview: {e}")
            # Try to turn back to the original page if an error occurred
            try:
                self.turn_page_backward()
            except Exception as turn_back_error:
                logger.error(f"Failed to turn back to original page after error: {turn_back_error}")
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
            logger.error(f"Error during previous page preview: {e}")
            # Try to turn forward to the original page if an error occurred
            try:
                self.turn_page_forward()
            except Exception as turn_forward_error:
                logger.error(f"Failed to turn forward to original page after error: {turn_forward_error}")
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
                    logger.error("Could not make reading controls visible")
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
                    logger.error("Could not find progress element after showing controls")
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
                    logger.error(f"Error parsing page numbers: {e}")

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
            logger.error(f"Error getting reading progress: {e}")
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
            logger.error(f"Error getting book title: {e}")
            return None

    def navigate_back_to_library(self) -> bool:
        """Handle the reading state by navigating back to the library."""
        logger.info("Handling reading state - navigating back to library...")

        # Log the initial page source for debugging
        filepath = store_page_source(self.driver.page_source, "reading_state")
        logger.info(f"Stored reading state page source at: {filepath}")

        try:
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

            # Check for and dismiss full screen dialog
            dialog_visible, _ = self._check_element_visibility(
                READING_VIEW_FULL_SCREEN_DIALOG, "full screen dialog"
            )
            if dialog_visible:
                logger.info("Found full screen dialog - attempting to dismiss")
                got_it_visible, got_it_button = self._check_element_visibility(
                    FULL_SCREEN_DIALOG_GOT_IT, "'Got it' button"
                )
                if got_it_visible:
                    got_it_button.click()
                    logger.info("Clicked 'Got it' button to dismiss dialog")
                    time.sleep(1)

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

                        filepath = store_page_source(
                            self.driver.page_source, "goodreads_dialog_dismissed_navigation"
                        )
                        logger.info(f"Stored Goodreads dialog dismissed page source at: {filepath}")
                except NoSuchElementException:
                    logger.error("NOT NOW button not found for Goodreads dialog")
                except Exception as e:
                    logger.error(f"Error clicking NOT NOW button: {e}")

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

                    filepath = store_page_source(
                        self.driver.page_source, "word_wise_dialog_dismissed_navigation"
                    )
                    logger.info(f"Stored Word Wise dialog dismissed page source at: {filepath}")
                else:
                    logger.error("NO THANKS button not found for Word Wise dialog")

            # Now try to make toolbar visible if it isn't already
            return self._show_toolbar_and_close_book()

        except Exception as e:
            logger.error(f"Error handling reading state: {e}")
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
                logger.error("NOT NOW button not found for Goodreads dialog")
            except Exception as e:
                logger.error(f"Error clicking NOT NOW button: {e}")

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
                    logger.error("NOT NOW button not found for Goodreads dialog")
                except Exception as e:
                    logger.error(f"Error clicking NOT NOW button: {e}")

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
            logger.error(f"Error using system back button: {e}")

        logger.error("Failed to make toolbar visible or exit reading view after all attempts")
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

            return True

        logger.error("Could not find close book button")
        return False
