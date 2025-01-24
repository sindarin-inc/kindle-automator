from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from views.core.logger import logger
from views.reading.view_strategies import (
    READING_VIEW_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    BOTTOM_SHEET_IDENTIFIERS,
    PAGE_NUMBER_IDENTIFIERS,
)
from views.library.view_strategies import BOOK_TITLE_IDENTIFIERS, BOOK_TITLE_ELEMENT_ID
from handlers.library_handler import LibraryHandler
import subprocess
from PIL import Image
from io import BytesIO
import time
from selenium.common.exceptions import WebDriverException


class ReaderHandler:
    def __init__(self, driver):
        self.driver = driver
        self.library_handler = LibraryHandler(driver)

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

        logger.info(f"Successfully opened book: {book_title}")
        logger.info("Reading view loaded")

        # Log the page source to check for slideout
        logger.info("\n=== READING VIEW PAGE SOURCE START ===")
        logger.info(self.driver.page_source)
        logger.info("=== READING VIEW PAGE SOURCE END ===\n")

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

        # Get current page
        current_page = self.get_current_page()
        logger.info(f"Current page: {current_page}")

        # Capture screenshot of first page
        logger.info("Capturing page screenshot...")
        try:
            self.driver.save_screenshot("first_page.png")
            logger.info("Successfully saved page screenshot")
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
            image.save("reading_page.png")
            logger.info("Successfully saved page screenshot")
            return True

        except Exception as e:
            logger.error(f"Error capturing page screenshot: {e}")
            return False

    def turn_page(self, direction="forward"):
        """Turn the page forward or backward"""
        # TODO: Implement page turning functionality
        pass

    def get_reading_progress(self):
        """Get reading progress as percentage"""
        # TODO: Implement reading progress retrieval
        pass

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
                bottom_sheet = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_dialog"
                )
                if bottom_sheet.is_displayed():
                    logger.info("Found bottom sheet dialog, dismissing it...")
                    pill = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_pill")
                    pill.click()
                    logger.info("Clicked bottom sheet pill to dismiss")
                    time.sleep(1)  # Wait for dismiss animation

                    # Log the page source after dismissing bottom sheet
                    logger.info("\n=== PAGE SOURCE AFTER DISMISSING BOTTOM SHEET START ===")
                    logger.info(self.driver.page_source)
                    logger.info("=== PAGE SOURCE AFTER DISMISSING BOTTOM SHEET END ===\n")
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
                logger.info(f"\n=== PAGE SOURCE BEFORE TAP ATTEMPT {attempt + 1} START ===")
                logger.info(self.driver.page_source)
                logger.info(f"=== PAGE SOURCE BEFORE TAP ATTEMPT {attempt + 1} END ===\n")

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
                    logger.info("\n=== PAGE SOURCE AFTER SUCCESSFUL TAP START ===")
                    logger.info(self.driver.page_source)
                    logger.info("=== PAGE SOURCE AFTER SUCCESSFUL TAP END ===\n")
                    toolbar_visible = True
                    break

                except Exception as e:
                    logger.error(f"Error checking toolbar visibility: {e}")
                    if attempt < max_attempts - 1:
                        logger.info("Toolbar did not appear, trying again...")
                    else:
                        logger.error("Failed to make toolbar visible after all attempts")
                        logger.info("\n=== PAGE SOURCE AFTER FAILED ATTEMPTS START ===")
                        logger.info(self.driver.page_source)
                        logger.info("=== PAGE SOURCE AFTER FAILED ATTEMPTS END ===\n")
                        return False

            if not toolbar_visible:
                logger.error("Could not make toolbar visible")
                logger.info("\n=== FINAL PAGE SOURCE START ===")
                logger.info(self.driver.page_source)
                logger.info("=== FINAL PAGE SOURCE END ===\n")
                return False

            # Now that toolbar is visible, click the close book button
            try:
                strategy, locator = READING_TOOLBAR_IDENTIFIERS[0]  # Get close book button identifier
                close_book_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((strategy, locator))
                )
                close_book_button.click()
                logger.info("Clicked close book button")
                return True
            except Exception as e:
                logger.error(f"Error clicking close book button: {e}")
                return False

        except Exception as e:
            logger.error(f"Error making toolbar visible: {e}")
            logger.info("Could not make toolbar visible")
            return False
