import time
import traceback
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
from views.core.logger import logger
from views.library.view_strategies import (
    LIBRARY_TAB_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_IDENTIFIERS,
    BOTTOM_NAV_IDENTIFIERS,
    LIBRARY_VIEW_IDENTIFIERS,
    GRID_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
    BOOK_TITLE_IDENTIFIERS,
    BOOK_AUTHOR_IDENTIFIERS,
    BOOK_TITLE_ELEMENT_ID,
    BOOK_AUTHOR_ELEMENT_ID,
    EMPTY_LIBRARY_IDENTIFIERS,
    BOOK_METADATA_IDENTIFIERS,
)
from views.library.interaction_strategies import (
    LIBRARY_TAB_STRATEGIES,
    VIEW_OPTIONS_BUTTON_STRATEGIES,
    LIST_VIEW_OPTION_STRATEGIES,
    MENU_CLOSE_STRATEGIES,
    VIEW_OPTIONS_DONE_STRATEGIES,
    SAFE_TAP_AREAS,
)
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS
from typing import Optional, List
from selenium.webdriver.remote.webelement import WebElement
import logging

logger = logging.getLogger(__name__)


class LibraryHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _is_library_tab_selected(self):
        """Check if the library tab is currently selected."""
        logger.info("Checking if library tab is selected...")

        # First try the selection strategies
        for strategy in LIBRARY_TAB_SELECTION_IDENTIFIERS:
            try:
                if len(strategy) == 3:  # Complex strategy with child elements
                    by, value, child_checks = strategy
                    tab = self.driver.find_element(by, value)

                    # Check child elements
                    for child_by, child_value, attr, expected in child_checks.values():
                        child = tab.find_element(child_by, child_value)
                        if child.get_attribute(attr) == expected:
                            logger.info(f"Found library tab with '{attr}' in {child_by}")
                            return True
                else:  # Simple strategy
                    by, value = strategy
                    self.driver.find_element(by, value)
                    logger.info(f"Found library tab with strategy: {by}")
                    return True
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue

        # If we're here, check if we're in the library view by looking for library-specific elements
        try:
            for strategy, locator in LIBRARY_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"Found library view element: {locator}")
                    return True
                except:
                    continue
        except Exception as e:
            logger.debug(f"Library view check failed: {e}")

        logger.info("Library tab is not selected")
        return False

    def _is_view_options_menu_open(self):
        """Check if the view options menu is open."""
        try:
            self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/view_options_menu")
            return True
        except:
            return False

    def _find_bottom_navigation(self):
        """Find the bottom navigation bar."""
        for strategy, locator in BOTTOM_NAV_IDENTIFIERS:
            try:
                nav = self.driver.find_element(strategy, locator)
                logger.info(f"Found bottom navigation using {strategy}")
                return nav
            except Exception as e:
                logger.debug(f"Bottom nav strategy failed - {strategy}: {e}")
                continue
        return None

    def navigate_to_library(self):
        """Navigate to the library tab"""
        try:
            # Check if view options menu is open and close it if needed
            if self._is_view_options_menu_open():
                logger.info("View options menu is open, closing it first")
                if not self._close_menu():
                    logger.error("Failed to close view options menu")
                    return False
                time.sleep(0.5)  # Wait for menu to close

            # First check if library tab is already selected
            if self._is_library_tab_selected():
                logger.info("Already on library tab")
                return True

            # Try to find the library tab directly using identifiers
            for strategy, locator in LIBRARY_TAB_IDENTIFIERS:
                try:
                    library_tab = self.driver.find_element(strategy, locator)
                    logger.info(f"Found Library tab using {strategy}")
                    library_tab.click()
                    logger.info("Clicked Library tab")
                    time.sleep(1)  # Wait for tab switch animation
                    return True
                except Exception as e:
                    logger.debug(f"Library tab identifier failed - {strategy}: {e}")
                    continue

            # Try to find the bottom navigation bar
            nav = self._find_bottom_navigation()
            if nav:
                logger.info("Found bottom navigation bar")
                # Try each library tab strategy within the navigation bar
                for strategy, locator in LIBRARY_TAB_STRATEGIES:
                    try:
                        library_tab = nav.find_element(strategy, locator)
                        logger.info(f"Found Library tab using {strategy}")
                        library_tab.click()
                        logger.info("Clicked Library tab")
                        time.sleep(1)  # Wait for tab switch animation
                        return True
                    except Exception as e:
                        logger.debug(f"Strategy {strategy} failed: {e}")
                        continue

            logger.error("Failed to find Library tab with any strategy")
            return False
        except Exception as e:
            logger.error(f"Error navigating to library: {e}")
            return False

    def _is_grid_view(self):
        """Check if currently in grid view"""
        try:
            for strategy, locator in GRID_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"Grid view detected via {strategy}: {locator}")
                    return True
                except Exception as e:
                    logger.debug(f"Grid view strategy failed - {strategy}: {locator} - {e}")
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking grid view: {e}")
            return False

    def _is_list_view(self):
        """Check if currently in list view"""
        try:
            for strategy, locator in LIST_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"List view detected via {strategy}: {locator}")
                    return True
                except Exception as e:
                    logger.debug(f"List view strategy failed - {strategy}: {locator} - {e}")
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking list view: {e}")
            return False

    def switch_to_list_view(self):
        """Switch to list view if not already in it"""
        try:
            # First check if we're already in list view
            if self._is_list_view():
                logger.info("Already in list view")
                return True

            # Click view options button
            for strategy, locator in VIEW_OPTIONS_BUTTON_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    button.click()
                    logger.info("Clicked view options button")
                    time.sleep(0.5)  # Short wait for menu animation
                    break
                except Exception:
                    continue

            # Click list view option
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    option = self.driver.find_element(strategy, locator)
                    option.click()
                    logger.info("Clicked list view option")
                    time.sleep(0.5)  # Short wait for selection to register
                    break
                except Exception:
                    continue

            # Click DONE button
            try:
                done_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"
                )
                done_button.click()
                logger.info("Clicked DONE button")
            except Exception as e:
                logger.error(f"Failed to click DONE button: {e}")
                return False

            # Wait for list view to appear with timeout
            try:
                logger.info("Waiting for list view to appear...")
                WebDriverWait(self.driver, 2).until(
                    lambda x: any(
                        x.find_element(strategy, locator) is not None
                        for strategy, locator in LIST_VIEW_IDENTIFIERS
                    )
                )
                logger.info("Successfully switched to list view")
                return True
            except Exception as e:
                logger.error(f"Timed out waiting for list view: {e}")
                # Get page source for debugging
                logger.info("\n=== PAGE SOURCE AFTER VIEW SWITCH ===")
                logger.info(self.driver.page_source)
                logger.info("=== END PAGE SOURCE ===\n")
                return False

        except Exception as e:
            logger.error(f"Error switching to list view: {e}")
            return False

    def _close_menu(self):
        """Close any open menu by tapping outside."""
        try:
            # Try each safe tap area
            for x, y in SAFE_TAP_AREAS:
                try:
                    self.driver.tap([(x, y)])
                    logger.info(f"Tapped at ({x}, {y}) to close menu")
                    time.sleep(0.5)  # Wait for menu animation
                    if not self._is_view_options_menu_open():
                        return True
                except Exception as e:
                    logger.debug(f"Failed to tap at ({x}, {y}): {e}")
                    continue

            # If tapping didn't work, try clicking dismiss buttons
            for strategy, locator in MENU_CLOSE_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    button.click()
                    logger.info(f"Clicked dismiss button using {strategy}")
                    return True
                except Exception as e:
                    logger.debug(f"Failed to click dismiss button: {e}")
                    continue

            return False
        except Exception as e:
            logger.error(f"Error closing menu: {e}")
            return False

    def get_book_titles(self):
        """Get a list of all books in the library with their metadata."""
        try:
            # Ensure we're in the library view
            if not self.navigate_to_library():
                logger.error("Failed to navigate to library")
                return []

            # Wait for library content to load
            time.sleep(2)

            # Log page source for debugging
            logger.info("=== LIBRARY PAGE SOURCE START ===")
            logger.info(self.driver.page_source)
            logger.info("=== LIBRARY PAGE SOURCE END ===")

            # Initialize list to store book information
            books = []

            # First find all containers
            containers = []
            for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"]:
                try:
                    found_containers = self.driver.find_elements(container_strategy, container_locator)
                    if found_containers:
                        containers = found_containers
                        logger.debug(f"Found {len(containers)} book containers")
                        break
                except Exception as e:
                    logger.debug(f"Failed to find containers with {container_strategy}: {e}")
                    continue

            # Process each container
            for container in containers:
                try:
                    book_info = {"title": None, "progress": None, "size": None, "author": None}

                    # Extract metadata using strategies
                    for field in ["title", "progress", "size", "author"]:
                        for strategy, locator in BOOK_METADATA_IDENTIFIERS[field]:
                            try:
                                elements = container.find_elements(strategy, locator)
                                if elements:
                                    book_info[field] = elements[0].text
                                    logger.debug(f"Found {field}: {book_info[field]}")
                                    break
                            except Exception as e:
                                logger.debug(f"Failed to find {field} with {strategy}: {e}")
                                continue

                    if book_info["title"]:  # Only add books that have at least a title
                        books.append(book_info)

                except Exception as e:
                    logger.error(f"Error extracting book info: {e}")
                    continue

            logger.info(f"Found {len(books)} books using xpath")
            return books

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            return []

    def list_books(self):
        """List all books in the library"""
        # TODO: Implement book listing functionality
        pass

    def _normalize_title(self, title: str) -> str:
        """Normalize a title by removing all characters except alphanumeric and spaces."""
        # First convert to lowercase
        normalized = title.lower()
        # Keep only alphanumeric characters and spaces
        normalized = "".join(c for c in normalized if c.isalnum() or c.isspace())
        # Replace multiple spaces with single space and strip
        normalized = " ".join(normalized.split())
        return normalized

    def find_book(self, book_title: str) -> bool:
        """Find and click a book button by title. If the book isn't downloaded, initiate download and wait for completion."""
        try:
            # Normalize the input title
            normalized_book_title = self._normalize_title(book_title)
            logger.info(f"Looking for book: {book_title}")
            logger.info(f"Normalized book title: {normalized_book_title}")

            for strategy, locator in BOOK_TITLE_IDENTIFIERS:
                buttons = self.driver.find_elements(strategy, locator)
                logger.info(f"Found {len(buttons)} book buttons")

                for button in buttons:
                    try:
                        title_elem = button.find_element(AppiumBy.ID, BOOK_TITLE_ELEMENT_ID)
                        title_text = title_elem.text.strip()
                        normalized_title_text = self._normalize_title(title_text)
                        logger.info(f"Found title text: {title_text}")
                        logger.info(f"Normalized title text: {normalized_title_text}")

                        if normalized_title_text == normalized_book_title:
                            # Check if the book is downloaded
                            content_desc = button.get_attribute("content-desc")
                            logger.info(f"Book content description: {content_desc}")

                            if "Book downloaded" not in content_desc:
                                logger.info("Book is not downloaded yet, initiating download...")
                                button.click()
                                logger.info("Clicked book to start download")

                                # Wait for download to complete (up to 60 seconds)
                                max_attempts = 60
                                for attempt in range(max_attempts):
                                    try:
                                        # Re-find the button since the page might have refreshed
                                        button = self.driver.find_element(strategy, locator)
                                        content_desc = button.get_attribute("content-desc")
                                        logger.info(
                                            f"Checking download status (attempt {attempt + 1}/{max_attempts})"
                                        )

                                        if "Book downloaded" in content_desc:
                                            logger.info("Book has finished downloading")
                                            # Click again to open now that it's downloaded
                                            button.click()
                                            logger.info("Clicked book button after download")
                                            return True

                                        time.sleep(1)  # Wait 1 second between checks
                                    except Exception as e:
                                        logger.error(f"Error checking download status: {e}")
                                        time.sleep(1)
                                        continue

                                logger.error("Timed out waiting for book to download")
                                return False

                            logger.info(f"Found downloaded book: {title_text}")
                            button.click()
                            logger.info("Clicked book button")
                            return True
                    except Exception as e:
                        logger.error(f"Error getting book title: {e}")
                        continue

            logger.info(f"Book not found: {book_title}")
            return False
        except Exception as e:
            logger.error(f"Error finding book: {e}")
            return False

    def open_book(self, book_title: str) -> bool:
        """Open a book in the library.

        Args:
            book_title (str): The title of the book to open

        Returns:
            bool: True if the book was found and opened, False otherwise
        """
        try:
            # Find and click the book button
            if not self.find_book(book_title):
                logger.error(f"Failed to find book: {book_title}")
                return False

            logger.info(f"Successfully opened book: {book_title}")
            return True
        except Exception as e:
            logger.error(f"Error opening book: {e}")
            return False

    def handle_library_sign_in(self):
        """Handle the library sign in state by clicking the sign in button."""
        logger.info("Handling library sign in - checking if already signed in...")
        try:
            # Check if we're already signed in by looking for library root view AND checking that sign in button is NOT present
            has_library_root = False
            has_sign_in_button = False

            # Check for library root view
            for strategy, locator in LIBRARY_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    has_library_root = True
                    break
                except Exception:
                    continue

            # Check for sign in button
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    self.driver.find_element(strategy, locator)
                    has_sign_in_button = True
                    break
                except Exception:
                    continue

            # If we have library root but no sign in button, we're signed in
            if has_library_root and not has_sign_in_button:
                logger.info("Already signed in - library view found without sign in button")
                return True

            logger.info("Not signed in - clicking sign in button...")
            # Try each strategy to find and click the sign in button
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    logger.info(f"Found sign in button using strategy: {strategy}")
                    button.click()
                    logger.info("Successfully clicked sign in button")

                    # Wait for WebView to load
                    logger.info("Waiting for sign in WebView to load...")
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((AppiumBy.CLASS_NAME, "android.webkit.WebView"))
                    )
                    time.sleep(1)  # Short wait for WebView content to load

                    # Wait for email input field
                    logger.info("Waiting for email input field...")
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(EMAIL_VIEW_IDENTIFIERS[0])
                    )
                    return True
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
                    continue

            logger.error("Failed to find or click sign in button with any strategy")
            return False
        except Exception as e:
            logger.error(f"Error handling library sign in: {e}")
            return False

    def _dump_library_view(self):
        """Dump the library view for debugging"""
        try:
            screenshot_path = os.path.join(self.screenshots_dir, "library_view.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved library view screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save library view screenshot: {e}")
