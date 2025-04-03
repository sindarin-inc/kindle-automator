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

from handlers.library_handler import LibraryHandler
from server.logging_config import store_page_source
from views.core.avd_profile_manager import AVDProfileManager
from views.reading.interaction_strategies import (
    ABOUT_BOOK_SLIDEOVER_IDENTIFIERS,
    BOTTOM_SHEET_IDENTIFIERS,
    CLOSE_BOOK_STRATEGIES,
    FULL_SCREEN_DIALOG_GOT_IT,
    LAST_READ_PAGE_DIALOG_BUTTONS,
)
from views.reading.view_strategies import (
    ABOUT_BOOK_CHECKBOX,
    BLACK_BG_IDENTIFIERS,
    FONT_SIZE_SLIDER_IDENTIFIERS,
    GO_TO_LOCATION_DIALOG_IDENTIFIERS,
    GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS,
    GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS,
    HIGHLIGHT_MENU_CHECKBOX,
    LAST_READ_PAGE_DIALOG_IDENTIFIERS,
    LAYOUT_TAB_IDENTIFIERS,
    MORE_TAB_IDENTIFIERS,
    PAGE_NAVIGATION_ZONES,
    PAGE_NUMBER_IDENTIFIERS,
    PAGE_TURN_ANIMATION_CHECKBOX,
    PLACEMARK_IDENTIFIERS,
    POPULAR_HIGHLIGHTS_CHECKBOX,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    READING_VIEW_FULL_SCREEN_DIALOG,
    READING_VIEW_IDENTIFIERS,
    REALTIME_HIGHLIGHTING_CHECKBOX,
    STYLE_BUTTON_IDENTIFIERS,
    STYLE_SHEET_PILL_IDENTIFIERS,
    STYLE_SLIDEOVER_IDENTIFIERS,
    WHITE_BG_IDENTIFIERS,
)

logger = logging.getLogger(__name__)


class ReaderHandler:
    def __init__(self, driver):
        self.driver = driver
        self.library_handler = LibraryHandler(driver)
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        # Initialize profile manager
        self.profile_manager = AVDProfileManager()

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

        # Check for fullscreen dialog that appears after downloading and opening a book
        try:
            full_screen_dialog = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (AppiumBy.XPATH, "//android.widget.TextView[@text='Viewing full screen']")
                )
            )
            logger.info("Detected full screen dialog")

            # Click the "Got it" button
            got_it_button = self.driver.find_element(AppiumBy.ID, "android:id/ok")
            got_it_button.click()
            logger.info("Clicked 'Got it' on full screen dialog")
            time.sleep(1)  # Give time for the dialog to close
        except TimeoutException:
            logger.info("No full screen dialog detected, continuing...")
        except NoSuchElementException:
            logger.warning("Full screen dialog detected but couldn't find 'Got it' button")

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
                                    time.sleep(0.5)  # Wait for dialog to dismiss
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
                                    time.sleep(0.5)  # Wait for dialog to dismiss
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
                    time.sleep(0.5)  # Wait for dialog to dismiss

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
                        logger.warning("'About this book' slideover is still visible after dismissal attempts")
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
        if not self.profile_manager.is_styles_updated():
            logger.info("First-time reading with this profile, updating reading styles...")
            if self.update_reading_style():
                logger.info("Successfully updated reading styles")
            else:
                logger.warning("Failed to update reading styles")
        else:
            logger.info("Reading styles already updated for this profile, skipping")
            
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

        # Try tapping up to 3 times
        max_attempts = 3
        for attempt in range(max_attempts):
            logger.info(f"Attempting to show toolbar (attempt {attempt + 1}/{max_attempts})")
            self.driver.tap([(center_x, tap_y)])

            # Check if toolbar appeared
            toolbar_visible, _ = self._check_element_visibility(READING_TOOLBAR_IDENTIFIERS, "toolbar")
            if toolbar_visible:
                return self._click_close_book_button()

            # If the toolbar didn't appear, check if a dialog is now visible
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

                        # Try again to show toolbar after dismissing dialog
                        self.driver.tap([(center_x, tap_y)])
                        toolbar_visible, _ = self._check_element_visibility(
                            READING_TOOLBAR_IDENTIFIERS, "toolbar"
                        )
                        if toolbar_visible:
                            return self._click_close_book_button()
                except NoSuchElementException:
                    logger.error("NOT NOW button not found for Goodreads dialog")
                except Exception as e:
                    logger.error(f"Error clicking NOT NOW button: {e}")

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

            # Add debug page source dump after clicking close button
            filepath = store_page_source(self.driver.page_source, "failed_transition")
            logger.info(f"Stored page source after closing book at: {filepath}")

            return True

        logger.error("Could not find close book button")
        return False

    def update_reading_style(self) -> bool:
        """
        Update reading styles for the current profile. Should be called after a book is opened.
        This will only update styles if they have not already been updated for this profile.
        
        Returns:
            bool: True if the styles were updated successfully or were already updated, False otherwise
        """
        # First check if styles have already been updated for this profile
        if self.profile_manager.is_styles_updated():
            logger.info("Reading styles already updated for this profile, skipping")
            return True
            
        logger.info("Updating reading styles for the current profile")
        
        try:
            # Store page source before starting
            store_page_source(self.driver.page_source, "style_update_before")
            
            # 1. Tap center of page to show the placemark view
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            center_y = window_size["height"] // 2
            self.driver.tap([(center_x, center_y)])
            logger.info("Tapped center of page")
            time.sleep(1)
            
            # Store page source after tapping center
            store_page_source(self.driver.page_source, "style_update_after_center_tap")
            
            # 2. Tap the Style button
            style_button_found = False
            for strategy, locator in STYLE_BUTTON_IDENTIFIERS:
                try:
                    style_button = self.driver.find_element(strategy, locator)
                    if style_button.is_displayed():
                        style_button.click()
                        logger.info("Clicked style button")
                        style_button_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue
                    
            if not style_button_found:
                logger.error("Could not find style button")
                return False
                
            # Store page source after tapping style button
            store_page_source(self.driver.page_source, "style_update_after_style_button")
            
            # 3. Slide the font size slider all the way to the left
            slider_found = False
            for strategy, locator in FONT_SIZE_SLIDER_IDENTIFIERS:
                try:
                    slider = self.driver.find_element(strategy, locator)
                    if slider.is_displayed():
                        # Get slider dimensions
                        size = slider.size
                        location = slider.location
                        
                        # Calculate slider endpoints for drag action
                        slider_width = size["width"]
                        slider_height = size["height"]
                        start_x = location["x"] + slider_width - 10  # Near the far right
                        end_x = location["x"] + 10  # Near the far left
                        slider_y = location["y"] + slider_height // 2
                        
                        # Swipe from right to left to decrease font size
                        self.driver.swipe(start_x, slider_y, end_x, slider_y, 500)
                        logger.info(f"Slid font size slider from ({start_x}, {slider_y}) to ({end_x}, {slider_y})")
                        slider_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue
            
            # Look for the "A" decrease font size button as an alternative
            if not slider_found:
                try:
                    decrease_button = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_decrease_font_size")
                    if decrease_button.is_displayed():
                        logger.info("Found decrease font size button, tapping multiple times as alternative to slider")
                        # Tap the button multiple times to ensure smallest font size
                        for _ in range(5):
                            decrease_button.click()
                            time.sleep(0.2)
                        slider_found = True
                except NoSuchElementException:
                    logger.warning("Could not find decrease button either")
                except Exception as e:
                    logger.warning(f"Error using decrease button: {e}")
                    
            if not slider_found:
                logger.warning("Could not find font size slider or decrease button, continuing anyway")
                # We'll continue even if we can't find the slider, as other settings are still important
                
            # Store page source after adjusting font size
            store_page_source(self.driver.page_source, "style_update_after_font_size")
            
            # 4. Tap the More tab
            more_tab_found = False
            for strategy, locator in MORE_TAB_IDENTIFIERS:
                try:
                    more_tab = self.driver.find_element(strategy, locator)
                    if more_tab.is_displayed():
                        more_tab.click()
                        logger.info("Clicked More tab")
                        more_tab_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue
                    
            if not more_tab_found:
                # Try by text content as a fallback
                try:
                    more_tab = self.driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='More']")
                    if more_tab.is_displayed():
                        more_tab.click()
                        logger.info("Clicked More tab by text")
                        more_tab_found = True
                        time.sleep(1)
                    else:
                        logger.warning("Found More tab by text but it's not displayed")
                except NoSuchElementException:
                    logger.error("Could not find More tab by any strategy")
                    # We'll continue even without the More tab, try to function with what we have
                    
            # Store page source regardless of whether tab was found
            store_page_source(self.driver.page_source, "style_update_after_more_tab_attempt")
                
            # Store page source after tapping More tab
            store_page_source(self.driver.page_source, "style_update_after_more_tab")
            
            # 5. Disable "Real-time Text Highlighting"
            self._toggle_checkbox(REALTIME_HIGHLIGHTING_CHECKBOX, False, "Real-time Text Highlighting")
            
            # Store page source after toggling highlighting
            store_page_source(self.driver.page_source, "style_update_after_highlight_toggle")
            
            # 6. Scroll down to see more options
            # First get a reference point to scroll from
            try:
                # Use any visible element on the More tab as a reference point
                reference_element = None
                for strategy, locator in REALTIME_HIGHLIGHTING_CHECKBOX:
                    try:
                        element = self.driver.find_element(strategy, locator)
                        if element.is_displayed():
                            reference_element = element
                            break
                    except NoSuchElementException:
                        continue
                
                if reference_element:
                    # Get the element location
                    location = reference_element.location
                    
                    # Calculate scroll coordinates
                    start_y = location["y"] + 200  # A bit below our reference element
                    end_y = location["y"] - 200    # A bit above our reference element
                    scroll_x = window_size["width"] // 2
                    
                    # Scroll down
                    self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 500)
                    logger.info(f"Scrolled down from ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})")
                    time.sleep(1)
                else:
                    logger.warning("Could not find reference element for scrolling, will try generic scroll")
                    # Generic scroll from middle to top quarter
                    start_y = window_size["height"] // 2
                    end_y = window_size["height"] // 4
                    scroll_x = window_size["width"] // 2
                    self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 500)
                    logger.info(f"Performed generic scroll from ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})")
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error during scrolling: {e}")
                # Continue anyway since some devices might show all options without scrolling
            
            # Store page source after scrolling
            store_page_source(self.driver.page_source, "style_update_after_scrolling")
            
            # 7. Disable "About this Book"
            self._toggle_checkbox(ABOUT_BOOK_CHECKBOX, False, "About this Book")
            
            # 8. Disable "Page Turn Animation"
            self._toggle_checkbox(PAGE_TURN_ANIMATION_CHECKBOX, False, "Page Turn Animation")
            
            # 9. Disable "Popular Highlights"
            self._toggle_checkbox(POPULAR_HIGHLIGHTS_CHECKBOX, False, "Popular Highlights")
            
            # 10. Disable "Highlight Menu"
            self._toggle_checkbox(HIGHLIGHT_MENU_CHECKBOX, False, "Highlight Menu")
            
            # Store page source after all toggles
            store_page_source(self.driver.page_source, "style_update_after_all_toggles")
            
            # 11. Tap the slideover tab at the top of the style slideover to set it to half-height
            sheet_pill_found = False
            for strategy, locator in STYLE_SHEET_PILL_IDENTIFIERS:
                try:
                    pill = self.driver.find_element(strategy, locator)
                    if pill.is_displayed():
                        pill.click()
                        logger.info("Clicked style sheet pill to set to half-height")
                        sheet_pill_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue
            
            if not sheet_pill_found:
                logger.warning("Could not find style sheet pill, will try tapping directly where it should be")
                # Try tapping where the pill would typically be (top center of the slideover)
                try:
                    # Look for the slideover first to get its position
                    slideover_found = False
                    for strategy, locator in STYLE_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = self.driver.find_element(strategy, locator)
                            if slideover.is_displayed():
                                # Get the top center of the slideover
                                location = slideover.location
                                size = slideover.size
                                pill_x = location["x"] + size["width"] // 2
                                pill_y = location["y"] + 20  # Near the top
                                
                                self.driver.tap([(pill_x, pill_y)])
                                logger.info(f"Tapped estimated pill location at ({pill_x}, {pill_y})")
                                slideover_found = True
                                time.sleep(1)
                                break
                        except NoSuchElementException:
                            continue
                    
                    if not slideover_found:
                        logger.warning("Could not find style slideover, will try generic tap")
                        # Generic tap near the top of the screen
                        tap_x = window_size["width"] // 2
                        tap_y = window_size["height"] // 4
                        self.driver.tap([(tap_x, tap_y)])
                        logger.info(f"Performed generic tap at ({tap_x}, {tap_y})")
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Error tapping pill location: {e}")
            
            # Store page source after pill tap
            store_page_source(self.driver.page_source, "style_update_after_pill_tap")
            
            # 12. Tap near the top of the screen to hide the style slideover
            top_tap_x = window_size["width"] // 2
            top_tap_y = int(window_size["height"] * 0.1)  # 10% from the top
            self.driver.tap([(top_tap_x, top_tap_y)])
            logger.info(f"Tapped near top of screen at ({top_tap_x}, {top_tap_y}) to hide style slideover")
            time.sleep(1)
            
            # Store final page source
            store_page_source(self.driver.page_source, "style_update_complete")
            
            # Even if some steps failed, we've still likely made some improvements
            # Update the profile to indicate styles have been updated
            success = True
            try:
                if self.profile_manager.update_style_preference(True):
                    logger.info("Successfully updated style preference in profile")
                else:
                    logger.warning("Failed to update style preference in profile, may need to retry")
                    # Don't mark as failure, we'll still return success if we've made it this far
            except Exception as e:
                logger.error(f"Error updating style preference in profile: {e}")
                # Again, don't mark as failure, we'll still return success if we've made it this far
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating reading styles: {e}")
            # Store exception page source
            try:
                store_page_source(self.driver.page_source, "style_update_exception")
            except:
                pass
            return False
            
    def _toggle_checkbox(self, checkbox_strategies, desired_state, description):
        """
        Toggle a checkbox to the desired state.
        
        Args:
            checkbox_strategies: List of (strategy, locator) tuples for the checkbox
            desired_state: Boolean indicating the desired state (True for checked, False for unchecked)
            description: Description of the checkbox for logging
            
        Returns:
            bool: True if the operation was successful, False otherwise
        """
        try:
            # Store before page source
            store_page_source(self.driver.page_source, f"toggle_{description.lower().replace(' ', '_')}_before")
            
            checkbox_found = False
            for strategy, locator in checkbox_strategies:
                try:
                    checkbox = self.driver.find_element(strategy, locator)
                    if checkbox.is_displayed():
                        # Try different attributes to determine the current state
                        current_state = None
                        
                        # Try 'checked' attribute first
                        checked_attr = checkbox.get_attribute("checked")
                        if checked_attr is not None:
                            current_state = checked_attr.lower() == "true"
                        
                        # If that didn't work, try 'selected' attribute
                        if current_state is None:
                            selected_attr = checkbox.get_attribute("selected")
                            if selected_attr is not None:
                                current_state = selected_attr.lower() == "true"
                        
                        # Try content-desc which sometimes contains state information
                        if current_state is None:
                            content_desc = checkbox.get_attribute("content-desc")
                            if content_desc:
                                current_state = "enabled" in content_desc.lower() or "on" in content_desc.lower()
                        
                        # Look at the text which might indicate state
                        if current_state is None:
                            text = checkbox.text
                            if text:
                                current_state = "enabled" in text.lower() or "on" in text.lower()
                        
                        # If we still couldn't determine state, make a best guess based on the UI
                        if current_state is None:
                            logger.warning(f"Could not determine state for {description}, assuming it's on")
                            current_state = True  # Assume it's on, so we'll try to turn it off
                        
                        logger.info(f"Current state of {description}: {current_state}")
                        
                        # Only toggle if the current state doesn't match the desired state
                        if current_state != desired_state:
                            checkbox.click()
                            logger.info(f"Toggled {description} from {current_state} to {desired_state}")
                            time.sleep(0.5)  # Short wait for toggle to take effect
                        else:
                            logger.info(f"{description} is already in the desired state ({desired_state})")
                        
                        checkbox_found = True
                        break
                except NoSuchElementException:
                    continue
                except Exception as inner_e:
                    logger.warning(f"Error interacting with {description} element: {inner_e}")
                    continue
            
            # Try a broader text-based search if the specific strategies failed
            if not checkbox_found:
                try:
                    # Look for a generic Switch or CheckBox with text containing our description
                    logger.info(f"Trying generic search for {description}")
                    # Construct a simple XPath to find a control containing the description text
                    text_parts = description.split()
                    # Create a flexible XPath that checks partial text matches (case-insensitive)
                    xpath = f"//android.widget.Switch[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{description.lower()}')]" + \
                           f"|//android.widget.CheckBox[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{description.lower()}')]"
                    
                    checkbox = self.driver.find_element(AppiumBy.XPATH, xpath)
                    if checkbox.is_displayed():
                        logger.info(f"Found {description} through generic text search")
                        checkbox.click()
                        logger.info(f"Clicked {description} through generic search")
                        checkbox_found = True
                        time.sleep(0.5)
                except NoSuchElementException:
                    logger.warning(f"Could not find {description} through generic text search either")
                except Exception as text_e:
                    logger.warning(f"Error during text-based search for {description}: {text_e}")
                    
            if not checkbox_found:
                logger.warning(f"Could not find checkbox for {description}")
                return False
                
            # Store after page source
            store_page_source(self.driver.page_source, f"toggle_{description.lower().replace(' ', '_')}_after")
            return True
            
        except Exception as e:
            logger.error(f"Error toggling {description}: {e}")
            return False
            
    def set_dark_mode(self, enable: bool) -> bool:
        """Toggle dark mode on/off."""
        try:
            # First tap center to show controls if needed
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            center_y = window_size["height"] // 2
            self.driver.tap([(center_x, center_y)])
            time.sleep(0.5)  # Wait for controls to appear

            store_page_source(self.driver.page_source, "style_button_before")

            # Find and click style button
            for strategy, locator in STYLE_BUTTON_IDENTIFIERS:
                try:
                    style_button = self.driver.find_element(strategy, locator)
                    if style_button.is_displayed():
                        style_button.click()
                        logger.info("Clicked style button")
                        time.sleep(0.5)  # Wait for menu to appear
                        break
                except NoSuchElementException:
                    continue

            store_page_source(self.driver.page_source, "style_button_after")

            # Find and click the layout tab
            for strategy, locator in LAYOUT_TAB_IDENTIFIERS:
                try:
                    layout_tab = self.driver.find_element(strategy, locator)
                    if layout_tab.is_displayed():
                        layout_tab.click()
                        logger.info("Clicked layout tab")
                        break
                except NoSuchElementException:
                    continue

            store_page_source(self.driver.page_source, "layout_tab_after")

            # Verify layout menu is open by checking for the Layout tab
            layout_menu_visible = False
            for strategy, locator in LAYOUT_TAB_IDENTIFIERS:
                try:
                    tab = self.driver.find_element(strategy, locator)
                    if tab.is_displayed():
                        layout_menu_visible = True
                        break
                except NoSuchElementException:
                    continue

            if not layout_menu_visible:
                logger.error("Layout menu not visible after clicking button")
                return False

            # Click appropriate color radio button
            color_identifiers = BLACK_BG_IDENTIFIERS if enable else WHITE_BG_IDENTIFIERS
            for strategy, locator in color_identifiers:
                try:
                    toggle = self.driver.find_element(strategy, locator)
                    if toggle.is_displayed():
                        toggle.click()
                        logger.info(f"Set background color to: {'black' if enable else 'white'}")
                        time.sleep(0.5)  # Wait for change to apply
                        break
                except NoSuchElementException:
                    continue

            # Calculate safe tap position above style menu using strategy constants
            store_page_source(self.driver.page_source, "style_close_style_menu")
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            safe_tap_y = int(window_size["height"] * 0.30)

            self.driver.tap([(center_x, safe_tap_y)])
            time.sleep(0.5)

            return True

        except Exception as e:
            logger.error(f"Error setting dark mode: {e}")
            return False
