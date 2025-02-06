import logging
import os
import time
import traceback

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from server.logging_config import store_page_source
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS
from views.library.interaction_strategies import (
    LIBRARY_TAB_STRATEGIES,
    LIST_VIEW_OPTION_STRATEGIES,
    MENU_CLOSE_STRATEGIES,
    SAFE_TAP_AREAS,
    VIEW_OPTIONS_BUTTON_STRATEGIES,
)
from views.library.view_strategies import (
    BOOK_METADATA_IDENTIFIERS,
    BOTTOM_NAV_IDENTIFIERS,
    GRID_VIEW_IDENTIFIERS,
    LIBRARY_TAB_CHILD_SELECTION_STRATEGIES,
    LIBRARY_TAB_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_IDENTIFIERS,
    LIBRARY_VIEW_DETECTION_STRATEGIES,
    LIBRARY_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
    READER_DRAWER_LAYOUT_IDENTIFIERS,
    VIEW_OPTIONS_DONE_BUTTON_STRATEGIES,
    WEBVIEW_IDENTIFIERS,
)
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES

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
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
                        logger.info(f"Found library tab with strategy: {by}")
                        return True
            except NoSuchElementException:
                continue

        # If we're here, check if we're in the library view by looking for library-specific elements
        try:
            for strategy, locator in LIBRARY_VIEW_DETECTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found library view element: {locator}")
                        # Also check for selected child elements
                        try:
                            # Check both child elements are selected
                            all_selected = True
                            for child_strategy, child_locator in LIBRARY_TAB_CHILD_SELECTION_STRATEGIES:
                                child = self.driver.find_element(child_strategy, child_locator)
                                if not child.is_displayed():
                                    all_selected = False
                                    break
                            if all_selected:
                                logger.info("Found library tab child elements selected")
                                return True
                        except:
                            pass
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
                    # Verify we're in library view
                    if self._is_library_tab_selected():
                        logger.info("Successfully switched to library tab")
                        return True
                except Exception as e:
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
                        # Verify we're in library view
                        if self._is_library_tab_selected():
                            logger.info("Successfully switched to library tab")
                            return True
                    except Exception as e:
                        logger.debug(f"Strategy {strategy} failed: {e}")
                        continue

            # If we're here, try checking if we're already in the library view
            for strategy, locator in LIBRARY_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found library view element: {locator}")
                        return True
                except:
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
                    return True
                except NoSuchElementException:
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
            for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                try:
                    done_button = self.driver.find_element(strategy, locator)
                    done_button.click()
                    logger.info("Clicked DONE button")
                    break
                except Exception as e:
                    logger.debug(f"Failed to click DONE button with strategy {strategy}: {e}")
                    continue

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
            except TimeoutException:
                logger.error(f"Timed out waiting for list view")
                # Get page source for debugging
                filepath = store_page_source(self.driver.page_source, "unknown_timeout")
                logger.info(f"Stored unknown timeout page source at: {filepath}")
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

    def _scroll_through_library(self, target_title: str = None):
        """Scroll through library collecting book info, optionally looking for a specific title.

        Args:
            target_title: Optional title to search for. If provided, returns early when found.

        Returns:
            If target_title provided: (found_container, found_button, book_info) or (None, None, None)
            If no target_title: List of book info dictionaries
        """
        try:
            # Get screen size for scrolling
            screen_size = self.driver.get_window_size()
            start_y = screen_size["height"] * 0.8
            end_y = screen_size["height"] * 0.2

            # Initialize tracking variables
            books = []
            seen_titles = set()
            normalized_target = self._normalize_title(target_title) if target_title else None

            while True:
                # Log page source for debugging
                filepath = store_page_source(self.driver.page_source, "library_view")
                logger.info(f"Stored library view page source at: {filepath}")

                # Find all containers on current screen
                containers = []
                for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"]:
                    try:
                        found_containers = self.driver.find_elements(container_strategy, container_locator)
                        if found_containers:
                            containers = found_containers
                            logger.debug(f"Found {len(containers)} book containers on current screen")
                            break
                    except Exception as e:
                        logger.debug(f"Failed to find containers with {container_strategy}: {e}")
                        continue

                # Store titles from previous scroll position
                previous_titles = set(seen_titles)
                new_books_found = False

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
                                        break
                                except Exception as e:
                                    logger.debug(f"Failed to find {field} with {strategy}: {e}")
                                    continue

                        if book_info["title"]:
                            normalized_title = self._normalize_title(book_info["title"])

                            # If we're looking for a specific book
                            if normalized_target and normalized_title == normalized_target:
                                # Find the button and parent container for download status
                                for strategy, locator in BOOK_METADATA_IDENTIFIERS["title"]:
                                    try:
                                        button = container.find_element(strategy, locator)
                                        logger.info(
                                            f"Found button: {button.get_attribute('content-desc')} looking for parent container"
                                        )

                                        # Try to find the parent RelativeLayout using XPath
                                        try:
                                            # First try finding the direct parent RelativeLayout
                                            parent_container = container.find_element(
                                                AppiumBy.XPATH,
                                                ".//android.widget.RelativeLayout[android.widget.TextView[@text='"
                                                + book_info["title"]
                                                + "']]",
                                            )
                                        except NoSuchElementException:
                                            # If that fails, try finding any ancestor RelativeLayout
                                            try:
                                                parent_container = container.find_element(
                                                    AppiumBy.XPATH,
                                                    "//android.widget.RelativeLayout[.//android.widget.TextView[@text='"
                                                    + book_info["title"]
                                                    + "']]",
                                                )
                                            except NoSuchElementException:
                                                # If that fails too, just use the container itself
                                                parent_container = container

                                        content_desc = parent_container.get_attribute("content-desc")
                                        if not content_desc or content_desc == "null":
                                            # If no content-desc, try the immediate parent
                                            try:
                                                temp_parent = parent_container.find_element(
                                                    AppiumBy.XPATH, ".."
                                                )
                                                temp_desc = temp_parent.get_attribute("content-desc")
                                                if temp_desc and temp_desc != "null":
                                                    parent_container = temp_parent
                                                    content_desc = temp_desc
                                            except Exception:
                                                pass

                                        if content_desc:
                                            logger.info(
                                                f"Found target book: {book_info['title']} {content_desc}"
                                            )
                                            return parent_container, button, book_info
                                        else:
                                            # If we still don't have content-desc, return what we have
                                            logger.warning(
                                                "Could not find container with content-desc, using fallback"
                                            )
                                            return parent_container, button, book_info

                                    except NoSuchElementException as e:
                                        logger.error(f"Found title but couldn't get container elements: {e}")
                                        continue

                            # Only add book if we haven't seen this title before
                            if book_info["title"] not in seen_titles:
                                books.append(book_info)
                                seen_titles.add(book_info["title"])
                                logger.info(f"Found book: {book_info['title']}")
                                new_books_found = True
                        else:
                            logger.info(f"Container has no book info, skipping: {book_info}")

                    except Exception as e:
                        logger.error(f"Error extracting book info: {e}")
                        continue

                # If we didn't find any new books, we've reached the end
                if not new_books_found:
                    logger.info("No new books found on this screen, stopping scroll")
                    break

                # Scroll down for next iteration
                try:
                    self.driver.swipe(
                        screen_size["width"] // 2,
                        start_y,
                        screen_size["width"] // 2,
                        end_y,
                        600,  # Duration in ms
                    )
                    logger.debug("Scrolled down for more books")
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Failed to scroll: {e}")
                    break

            if target_title:
                logger.info(f"Book not found after searching entire list: {target_title}")
                return None, None, None

            logger.info(f"Found total of {len(books)} unique books")
            return books

        except Exception as e:
            logger.error(f"Error scrolling through library: {e}")
            return [] if not target_title else (None, None, None)

    def get_book_titles(self):
        """Get a list of all books in the library with their metadata."""
        try:
            # Ensure we're in the library view
            if not self.navigate_to_library():
                logger.error("Failed to navigate to library")
                return []

            # Scroll to top of list
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            return self._scroll_through_library()

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            return []

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
            # Scroll to top first
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Search for the book
            parent_container, button, book_info = self._scroll_through_library(book_title)
            if not parent_container:
                return False

            # Check download status and handle download if needed
            content_desc = parent_container.get_attribute("content-desc")
            logger.info(f"Book content description: {content_desc} {parent_container}")
            store_page_source(self.driver.page_source, "library_view_book_info")

            if "Book not downloaded" in content_desc:
                logger.info("Book is not downloaded yet, initiating download...")
                button.click()
                logger.info("Clicked book to start download")

                # Wait for download to complete (up to 60 seconds)
                max_attempts = 60
                for attempt in range(max_attempts):
                    try:
                        # Re-find the parent container since the page might have refreshed
                        parent_container = self.driver.find_element(
                            AppiumBy.XPATH,
                            f"//android.widget.RelativeLayout[.//android.widget.TextView[@text='{book_info['title']}']]",
                        )
                        content_desc = parent_container.get_attribute("content-desc")
                        logger.info(f"Checking download status (attempt {attempt + 1}/{max_attempts})")
                        store_page_source(self.driver.page_source, "library_view_downloading")

                        if "Book downloaded" in content_desc:
                            logger.info("Book has finished downloading")
                            parent_container.click()
                            logger.info("Clicked book button after download")
                            return True

                        time.sleep(1)
                    except Exception as e:
                        logger.error(f"Error checking download status: {e}")
                        time.sleep(1)
                        continue

                logger.error("Timed out waiting for book to download")
                return False

            logger.info(f"Found downloaded book: {book_info['title']}")
            button.click()
            logger.info("Clicked book button")
            return True

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

            logger.info(f"Successfully clicked book: {book_title}")

            # Wait for reading view to load
            try:
                logger.info("Waiting for reading view to load...")
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(READER_DRAWER_LAYOUT_IDENTIFIERS[0])
                )
                logger.info("Reading view loaded")
                return True
            except Exception as e:
                filepath = store_page_source(self.driver.page_source, "unknown_library_timeout")
                logger.info(f"Stored unknown library timeout page source at: {filepath}")
                logger.error(f"Failed to wait for reading view: {e}")
                return False

        except Exception as e:
            traceback.print_exc()
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
                        EC.presence_of_element_located(WEBVIEW_IDENTIFIERS[0])
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

    def scroll_to_list_top(self):
        """Scroll to the top of the All list by toggling between Downloaded and All."""
        try:
            logger.info("Attempting to scroll to top of list by toggling filters...")

            # First try to find the Downloaded button
            try:
                downloaded_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/kindle_downloaded_toggle_downloaded"
                )
                downloaded_button.click()
                logger.info("Clicked Downloaded button")
                time.sleep(0.5)  # Short wait for filter to apply

                # Now find and click the All button
                all_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/kindle_downloaded_toggle_all"
                )
                all_button.click()
                logger.info("Clicked All button")
                time.sleep(0.5)  # Short wait for filter to apply

                return True

            except NoSuchElementException:
                logger.error("Could not find Downloaded or All toggle buttons")
                return False

        except Exception as e:
            logger.error(f"Error scrolling to top of list: {e}")
            return False
