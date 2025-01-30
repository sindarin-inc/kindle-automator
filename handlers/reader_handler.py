import logging
import os
import subprocess
import time
from io import BytesIO

from appium.webdriver.common.appiumby import AppiumBy
from PIL import Image
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from handlers.library_handler import LibraryHandler
from server.logging_config import store_page_source
from views.library.view_strategies import BOOK_TITLE_ELEMENT_ID, BOOK_TITLE_IDENTIFIERS
from views.reading.interaction_strategies import (
    BOTTOM_SHEET_IDENTIFIERS,
    CLOSE_BOOK_STRATEGIES,
)
from views.reading.view_strategies import (
    PAGE_NAVIGATION_ZONES,
    PAGE_NUMBER_IDENTIFIERS,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
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
        """Handle the entire reading flow for a specified book.

        Args:
            book_title (str): The exact title of the book to open

        Returns:
            tuple: (success, page_number) where success is a boolean and
                  page_number is the current page number or None if not found
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

            # Tap center of screen to show reading controls
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            center_y = window_size["height"] // 2
            self.driver.tap([(center_x, center_y)])
            logger.info(f"Tapped center of screen at ({center_x}, {center_y})")

            # Wait for reading controls to appear
            logger.info("Waiting for reading controls to appear...")
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.amazon.kindle:id/reader_footer_container"))
            )
            logger.info("Reading controls visible")

            # Short wait for controls to settle
            time.sleep(1)
        except Exception as e:
            logger.error(f"Failed to wait for reading view or content: {e}")
            return False

        # Log the page source to check for slideout
        filepath = store_page_source(self.driver.page_source, "reading_view")
        logger.info(f"Stored reading view page source at: {filepath}")

        # Check for and dismiss bottom sheet dialog
        try:
            strategy, locator = BOTTOM_SHEET_IDENTIFIERS[0]  # Get dialog identifier
            bottom_sheet = self.driver.find_element(strategy, locator)
            if bottom_sheet.is_displayed():
                logger.info("Found bottom sheet dialog, dismissing it...")
                # Find and click the drag pill to dismiss
                strategy, locator = BOTTOM_SHEET_IDENTIFIERS[1]  # Get pill identifier
                pill = self.driver.find_element(strategy, locator)
                pill.click()
                logger.info("Clicked bottom sheet pill to dismiss")
                # Wait briefly for animation
                time.sleep(1)
                # Verify bottom sheet is gone
                try:
                    strategy, locator = BOTTOM_SHEET_IDENTIFIERS[0]  # Get dialog identifier
                    bottom_sheet = self.driver.find_element(strategy, locator)
                    if bottom_sheet.is_displayed():
                        logger.error("Bottom sheet dialog is still visible after dismissal")
                        return False
                except:
                    logger.info("Bottom sheet dialog successfully dismissed")
        except Exception as e:
            logger.info(f"No bottom sheet dialog found or error dismissing it: {e}")

        # Wait for page number to be visible
        try:
            logger.info("Waiting for page number to be visible...")
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

    def turn_page_forward(self):
        """Turn to the next page."""
        try:
            # Check if we're in reading toolbar view
            try:
                toolbar = self.driver.find_element(*READING_TOOLBAR_IDENTIFIERS[0])
                if toolbar.is_displayed():
                    # Tap center to exit toolbar view
                    logger.info("Tapping center to exit toolbar view")
                    window_size = self.driver.get_window_size()
                    center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                    center_y = window_size["height"] // 2
                    self.driver.tap([(center_x, center_y)])
                    time.sleep(0.5)  # Wait for toolbar to hide
            except:
                pass  # Not in toolbar view, continue with page turn

            # Get screen dimensions and calculate tap coordinates
            window_size = self.driver.get_window_size()
            tap_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["next"])  # 90% of screen width
            tap_y = window_size["height"] // 2

            # Tap to turn page
            self.driver.tap([(tap_x, tap_y)])
            logger.info(f"Tapped at ({tap_x}, {tap_y}) to turn page forward")

            # Short wait for page turn animation
            time.sleep(0.5)
            return True

        except Exception as e:
            logger.error(f"Error turning page forward: {e}")
            return False

    def turn_page_backward(self):
        """Turn to the previous page."""
        try:
            # Get screen dimensions
            window_size = self.driver.get_window_size()
            screen_width = window_size["width"]
            screen_height = window_size["height"]

            # Calculate tap coordinates for left side of screen
            tap_x = int(screen_width * 0.1)  # 10% of screen width
            tap_y = int(screen_height * 0.5)  # Middle of screen height

            # Tap to turn page
            self.driver.tap([(tap_x, tap_y)])
            logger.info(f"Tapped at ({tap_x}, {tap_y}) to turn page backward")

            # Short wait for page turn animation
            time.sleep(0.5)
            return True

        except Exception as e:
            logger.error(f"Error turning page backward: {e}")
            return False

    def get_reading_progress(self):
        """Get reading progress as percentage"""
        try:
            # First check if we need to show controls
            try:
                # Try to find progress element directly first
                progress_element = self.driver.find_element(*READING_PROGRESS_IDENTIFIERS[0])
            except:
                # If not found, tap center to show controls
                window_size = self.driver.get_window_size()
                center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
                center_y = window_size["height"] // 2
                self.driver.tap([(center_x, center_y)])
                time.sleep(0.5)  # Wait for controls to appear

                try:
                    progress_element = self.driver.find_element(*READING_PROGRESS_IDENTIFIERS[0])
                except:
                    logger.error("Could not find progress element after showing controls")
                    return None

            # Extract progress text (usually in format "Page X of Y (Z%)")
            progress_text = progress_element.text
            logger.info(f"Found progress text: {progress_text}")

            # Try to extract percentage
            try:
                if "%" in progress_text:
                    percentage = progress_text.split("(")[-1].split("%")[0]
                    return f"{percentage}%"
            except:
                pass

            # If no percentage, try to extract page numbers
            try:
                if "of" in progress_text:
                    current, total = progress_text.lower().replace("page", "").split("of")
                    current = int("".join(filter(str.isdigit, current)))
                    total = int("".join(filter(str.isdigit, total)))
                    percentage = round((current / total) * 100)
                    return f"{percentage}%"
            except:
                pass

            return None

        except Exception as e:
            logger.error(f"Error getting reading progress: {e}")
            return None

    def handle_reading(self) -> bool:
        """Handle the reading state by navigating back to the library.

        Returns:
            bool: True if successfully navigated back to library, False otherwise
        """
        logger.info("Handling reading state - navigating back to library...")

        # Log the initial page source for debugging
        logger.info("\n=== INITIAL PAGE SOURCE START ===")
        logger.info(self.driver.page_source)
        logger.info("=== INITIAL PAGE SOURCE END ===\n")

        try:
            # First check for and dismiss bottom sheet if present
            try:
                bottom_sheet = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[0])
                if bottom_sheet.is_displayed():
                    logger.info("Found bottom sheet dialog, dismissing it...")
                    pill = self.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[1])
                    pill.click()
                    logger.info("Clicked bottom sheet pill to dismiss")
                    time.sleep(1)  # Wait for dismiss animation

                    # Log the page source after dismissing bottom sheet
                    filepath = store_page_source(self.driver.page_source, "bottom_sheet_dismissed")
                    logger.info(f"Stored bottom sheet dismissed page source at: {filepath}")
            except WebDriverException:
                logger.info("No bottom sheet dialog found")
            except Exception as e:
                logger.error(f"Error dismissing bottom sheet: {e}")

            # Now try to make toolbar visible by tapping top of screen
            # Get screen dimensions
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            tap_y = window_size["height"] // 10  # Tap at 10% of screen height

            # Try tapping up to 3 times
            max_attempts = 3
            toolbar_visible = False

            for attempt in range(max_attempts):
                filepath = store_page_source(self.driver.page_source, f"tap_attempt")
                logger.info(f"Stored tap attempt {attempt + 1} page source at: {filepath}")

                logger.info(
                    f"Toolbar is not visible, tapping top of screen (attempt {attempt + 1}/{max_attempts})"
                )
                self.driver.tap([(center_x, tap_y)])
                logger.info(f"Tapped top of screen at ({center_x}, {tap_y})")

                try:
                    # Wait for any toolbar element to become visible
                    WebDriverWait(self.driver, 3).until(
                        lambda x: any(
                            x.find_element(strategy, locator).is_displayed()
                            for strategy, locator in READING_TOOLBAR_IDENTIFIERS
                        )
                    )
                    logger.info("Toolbar is now visible")
                    filepath = store_page_source(self.driver.page_source, "toolbar_visible")
                    logger.info(f"Stored toolbar visible page source at: {filepath}")
                    toolbar_visible = True
                    break

                except Exception as e:
                    logger.error(f"Error checking toolbar visibility: {e}")
                    if attempt < max_attempts - 1:
                        logger.info("Toolbar did not appear, trying again...")
                    else:
                        logger.error("Failed to make toolbar visible after all attempts")
                        # Save page source
                        filepath = store_page_source(self.driver.page_source, "failed_toolbar_visibility")
                        logger.info(f"Stored failed toolbar visibility page source at: {filepath}")

                        # Save screenshot of failed state
                        try:
                            screenshot_path = os.path.join(
                                self.screenshots_dir, "failed_toolbar_visibility.png"
                            )
                            self.driver.save_screenshot(screenshot_path)
                            logger.info(f"Saved screenshot of failed state to {screenshot_path}")
                        except Exception as screenshot_error:
                            logger.error(f"Failed to save error screenshot: {screenshot_error}")
                        return False

            if not toolbar_visible:
                logger.error("Could not make toolbar visible")
                logger.info("\n=== FINAL PAGE SOURCE START ===")
                logger.info(self.driver.page_source)
                logger.info("=== FINAL PAGE SOURCE END ===\n")
                # Save screenshot of failed state
                try:
                    screenshot_path = os.path.join(self.screenshots_dir, "toolbar_not_visible.png")
                    self.driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot of failed state to {screenshot_path}")
                except Exception as screenshot_error:
                    logger.error(f"Failed to save error screenshot: {screenshot_error}")
                return False

            # Find and click close book button
            try:
                # Try each close book strategy in order
                for strategy, locator in CLOSE_BOOK_STRATEGIES:
                    try:
                        close_button = self.driver.find_element(strategy, locator)
                        if close_button.is_displayed():
                            close_button.click()
                            logger.info(f"Clicked close book button using {strategy}: {locator}")
                            return True
                    except:
                        continue

                logger.error("Failed to find close book button with any strategy")
                return False
            except Exception as e:
                logger.error(f"Error handling close book button: {e}")
                return False

        except Exception as e:
            logger.error(f"Error handling reading state: {e}")
            return False
