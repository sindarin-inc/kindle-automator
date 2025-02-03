import logging
import os
import re
import subprocess
import time
from io import BytesIO

from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.extensions.action_helpers import ActionHelpers
from PIL import Image
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.mouse_button import MouseButton
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from typing_extensions import Self

from handlers.library_handler import LibraryHandler
from server.logging_config import store_page_source
from views.library.view_strategies import BOOK_TITLE_ELEMENT_ID, BOOK_TITLE_IDENTIFIERS
from views.reading.interaction_strategies import (
    BOTTOM_SHEET_IDENTIFIERS,
    CLOSE_BOOK_STRATEGIES,
    FULL_SCREEN_DIALOG_GOT_IT,
)
from views.reading.view_strategies import (
    PAGE_NAVIGATION_ZONES,
    PAGE_NUMBER_IDENTIFIERS,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
)

logger = logging.getLogger(__name__)


class ReaderHandler:
    def __init__(self, driver):
        self.driver = driver
        self.library_handler = LibraryHandler(driver)
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def handle_reading_flow(self, book_title):
        """Handle the reading flow for a specific book.

        Args:
            book_title (str): Title of the book to read

        Returns:
            tuple: (success, page_number) where success is a boolean and page_number
                   is the current page number or None if not found
        """
        try:
            logger.info(f"Starting reading flow for book: {book_title}")

            # Try to open the book
            if not self.open_book(book_title):
                logger.error(f"Failed to open book: {book_title}")
                return False, None

            # Get page number
            page_number = self.get_current_page()
            logger.info(f"Current page: {page_number}")

            # Capture screenshot
            if not self.capture_page_screenshot():
                logger.error("Failed to capture page screenshot")
                return False, page_number

            # Check for and handle full screen dialog
            try:
                dialog = self.driver.find_element(*READING_VIEW_FULL_SCREEN_DIALOG[0])
                if dialog:
                    logger.info("Found full screen reading dialog - dismissing...")
                    # Tap in center of screen to dismiss
                    screen_size = self.driver.get_window_size()
                    center_x = screen_size["width"] // 2
                    center_y = screen_size["height"] // 2
                    self.driver.tap([(center_x, center_y)], 100)
                    time.sleep(1)  # Wait for dialog to dismiss
            except NoSuchElementException:
                pass  # Dialog not present, continue normally

            logger.info("Successfully opened book and captured first page")
            return True, page_number

        except Exception as e:
            logger.error(f"Error in reading flow: {e}")
            return False, None

    def open_book(self, book_title: str) -> bool:
        """Open a book in the library and wait for reading view to load.

        Args:
            book_title (str): Title of the book to open.

        Returns:
            bool: True if book was successfully opened, False otherwise.
        """
        logger.info(f"Starting reading flow for book: {book_title}")

        if not self.library_handler.open_book(book_title):
            logger.error(f"Failed to open book: {book_title}")
            return False

        logger.info(f"Successfully clicked book: {book_title}")

        # Wait for reading view to load
        try:
            logger.info("Waiting for reading view to load...")
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located(READING_VIEW_IDENTIFIERS[0]))
            logger.info("Reading view loaded")

            # Wait for page content to load
            logger.info("Waiting for page content to load...")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.amazon.kindle:id/reader_content_container"))
            )
            logger.info("Page content loaded")

            # Short wait for content to settle
            time.sleep(1)

        except TimeoutException:
            filepath = store_page_source(self.driver.page_source, "reading_view_timeout")
            logger.error(f"Failed to wait for reading view or content, stored page source at: {filepath}")
            return False

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
                            time.sleep(1)  # Wait for dismiss animation

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

        # Check for and dismiss Goodreads auto-update dialog
        try:
            not_now_button = self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
            )
            if not_now_button.is_displayed():
                logger.info("Found Goodreads auto-update dialog - clicking Not Now")
                not_now_button.click()
                time.sleep(0.5)  # Wait for dialog to dismiss

                # Verify dialog is gone
                try:
                    not_now_button = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"
                    )
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

        # Wait for page number to be visible
        try:
            logger.info("Waiting for page number to be visible...")
            store_page_source(self.driver.driver.page_source, "page_number_waiting")
            WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(PAGE_NUMBER_IDENTIFIERS[0]))
            logger.info("Page number element found")
        except Exception as e:
            logger.info(f"Page number element not found: {e}")

        # Get current page
        current_page = self.get_current_page()
        logger.info(f"Current page: {current_page}")

        # Capture screenshot of first page
        logger.info("Capturing page screenshot...")
        try:
            screenshot_path = os.path.join(self.screenshots_dir, "first_page.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Successfully saved page screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save page screenshot: {e}")

        logger.info("Successfully opened book and captured first page")
        return True

    def get_current_page(self):
        """Get the current page number"""
        try:
            for strategy, locator in PAGE_NUMBER_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    page_text = element.text.strip()
                    logger.info(f"Found page number: {page_text}")
                    return page_text
                except:
                    continue
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

    def get_reading_progress(self):
        """Get reading progress information

        Returns:
            dict: Dictionary containing:
                - percentage: Reading progress as percentage (str)
                - current_page: Current page number (int)
                - total_pages: Total pages (int)
            or None if progress info couldn't be retrieved
        """
        opened_controls = False
        try:
            # First check if we need to show controls
            try:
                # Try to find progress element directly first
                progress_element = self.driver.find_element(*READING_PROGRESS_IDENTIFIERS[0])
            except NoSuchElementException:
                # If not found, tap center to show controls
                window_size = self.driver.get_window_size()
                center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                center_y = window_size["height"] // 2
                self.driver.tap([(center_x, center_y)])
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
                    if not percentage:
                        calc_percentage = round((current_page / total_pages) * 100)
                        percentage = f"{calc_percentage}%"
                except Exception as e:
                    logger.error(f"Error parsing page numbers: {e}")

            if opened_controls:
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

        # Try tapping up to 3 times
        max_attempts = 3
        for attempt in range(max_attempts):
            logger.info(f"Attempting to show toolbar (attempt {attempt + 1}/{max_attempts})")
            self.driver.tap([(center_x, tap_y)])

            # Check if toolbar appeared
            toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
            if toolbar_visible:
                return self._click_close_book_button()

            if attempt < max_attempts - 1:
                logger.info("Toolbar not visible, will try again...")
                continue

        logger.error("Failed to make toolbar visible after all attempts")
        return False

    def _click_close_book_button(self):
        """Find and click the close book button."""
        close_visible, close_button = self._check_element_visibility(
            CLOSE_BOOK_STRATEGIES, "close book button"
        )
        if close_visible:
            close_button.click()
            logger.info("Clicked close book button")
            return True

        logger.error("Could not find close book button")
        return False
