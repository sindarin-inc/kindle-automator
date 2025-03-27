import logging
import os
import re
import time
import traceback
from typing import Dict, List, Optional, Tuple, Union

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
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
    BOOK_AUTHOR_IDENTIFIERS,
    BOOK_CONTAINER_RELATIONSHIPS,
    BOOK_METADATA_IDENTIFIERS,
    BOTTOM_NAV_IDENTIFIERS,
    CONTENT_DESC_STRATEGIES,
    GRID_VIEW_IDENTIFIERS,
    LIBRARY_ELEMENT_DETECTION_STRATEGIES,
    LIBRARY_TAB_CHILD_SELECTION_STRATEGIES,
    LIBRARY_TAB_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_STRATEGIES,
    LIBRARY_VIEW_DETECTION_STRATEGIES,
    LIBRARY_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
    READER_DRAWER_LAYOUT_IDENTIFIERS,
    VIEW_OPTIONS_DONE_BUTTON_STRATEGIES,
    VIEW_OPTIONS_MENU_STRATEGIES,
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
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "failed_library_tab")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "failed_library_tab.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}")
            return False
        except Exception as e:
            logger.error(f"Error navigating to library: {e}")
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "library_navigation_error")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "library_navigation_error.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}")
            return False

    def _is_grid_view(self):
        """Check if currently in grid view"""
        try:
            # First check for grid view identifiers
            for strategy, locator in GRID_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"Grid view detected via {strategy}: {locator}")
                    return True
                except NoSuchElementException:
                    # Expected failure, continue silently without logging
                    continue
                except StaleElementReferenceException:
                    # UI state changed, continue silently without logging
                    continue
                except Exception as e:
                    # Only log unexpected errors
                    logger.debug(f"Unexpected error checking grid view with {strategy}: {e}")
                    continue

            # Second check - look for GridView element directly
            try:
                self.driver.find_element(AppiumBy.CLASS_NAME, "android.widget.GridView")
                logger.info("Grid view detected via GridView class")
                return True
            except NoSuchElementException:
                # Expected failure, don't log
                pass
            except Exception as e:
                # Only log unexpected errors
                logger.debug(f"Unexpected error checking for GridView class: {e}")

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

            # If we're in grid view, we need to open the view options menu
            if self._is_grid_view():
                logger.info("Currently in grid view, switching to list view")

                # Store page source for debugging
                filepath = store_page_source(self.driver.page_source, "grid_view_detected")
                logger.info(f"Stored grid view page source at: {filepath}")

                # Click view options button
                button_clicked = False
                for strategy, locator in VIEW_OPTIONS_BUTTON_STRATEGIES:
                    try:
                        button = self.driver.find_element(strategy, locator)
                        button.click()
                        logger.info(f"Clicked view options button using {strategy}: {locator}")
                        time.sleep(1)  # Increased wait for menu animation
                        button_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click view options button with strategy {strategy}: {e}")
                        continue

                if not button_clicked:
                    logger.error("Failed to click any view options button")
                    return False

                # Verify the menu is open
                menu_open = False
                try:
                    for strategy, locator in VIEW_OPTIONS_MENU_STATE_STRATEGIES:
                        try:
                            self.driver.find_element(strategy, locator)
                            menu_open = True
                            logger.info(f"View options menu is open, detected via {strategy}: {locator}")
                            break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking if menu is open: {e}")

                if not menu_open:
                    logger.error("View options menu did not open properly")
                    return False

                # Click list view option
                list_option_clicked = False
                for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                    try:
                        option = self.driver.find_element(strategy, locator)
                        option.click()
                        logger.info(f"Clicked list view option using {strategy}: {locator}")
                        time.sleep(1)  # Increased wait for selection to register
                        list_option_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click list view option with strategy {strategy}: {e}")
                        continue

                if not list_option_clicked:
                    logger.error("Failed to click list view option")
                    return False

                # Click DONE button
                done_clicked = False
                for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                    try:
                        done_button = self.driver.find_element(strategy, locator)
                        done_button.click()
                        logger.info(f"Clicked DONE button using {strategy}: {locator}")
                        done_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click DONE button with strategy {strategy}: {e}")
                        continue

                if not done_clicked:
                    logger.error("Failed to click DONE button")
                    return False

                # Wait longer for list view to appear
                try:
                    logger.info("Waiting for list view to appear...")
                    WebDriverWait(self.driver, 5).until(
                        lambda x: any(
                            self.try_find_element(x, strategy, locator)
                            for strategy, locator in LIST_VIEW_IDENTIFIERS
                        )
                    )
                    logger.info("Successfully switched to list view")
                    return True
                except TimeoutException:
                    logger.error("Timed out waiting for list view")
                    # Get page source for debugging
                    filepath = store_page_source(self.driver.page_source, "list_view_timeout")
                    logger.info(f"Stored list view timeout page source at: {filepath}")
                    return False
            else:
                logger.warning("Neither in grid view nor list view, unable to determine current state")
                filepath = store_page_source(self.driver.page_source, "unknown_view_state")
                logger.info(f"Stored unknown view state page source at: {filepath}")
                return False

        except Exception as e:
            logger.error(f"Error switching to list view: {e}")
            traceback.print_exc()
            return False

    def try_find_element(self, driver, strategy, locator):
        """Safe wrapper to find element without raising exception"""
        try:
            return driver.find_element(strategy, locator) is not None
        except:
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

                # Find all book containers on current screen
                # First find all book buttons in the recycler view
                book_buttons = []
                try:
                    # Use the container strategy from BOOK_METADATA_IDENTIFIERS
                    container_strategy, container_locator = BOOK_METADATA_IDENTIFIERS["container"][0]
                    book_buttons = self.driver.find_elements(container_strategy, container_locator)
                    logger.debug(f"Found {len(book_buttons)} book buttons on current screen")
                except Exception as e:
                    logger.debug(f"Failed to find book buttons: {e}")

                # If no book buttons found, try the old container approach as fallback
                if not book_buttons:
                    containers = []
                    for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"][1:]:
                        try:
                            found_containers = self.driver.find_elements(
                                container_strategy, container_locator
                            )
                            if found_containers:
                                containers = found_containers
                                logger.debug(f"Found {len(containers)} book containers on current screen")
                                break
                        except Exception as e:
                            logger.debug(f"Failed to find containers with {container_strategy}: {e}")
                            continue
                else:
                    containers = book_buttons

                # Store titles from previous scroll position
                previous_titles = set(seen_titles)
                new_books_found = False

                # Process each container
                for container in containers:
                    try:
                        book_info = {"title": None, "progress": None, "size": None, "author": None}

                        # Extract metadata using strategies
                        for field in ["title", "progress", "size", "author"]:
                            # Try to find elements directly in the container first
                            for strategy, locator in BOOK_METADATA_IDENTIFIERS[field]:
                                try:
                                    # For direct elements, use find_element with a relative XPath
                                    relative_locator = (
                                        f".{locator}" if strategy == AppiumBy.XPATH else locator
                                    )
                                    elements = container.find_elements(strategy, relative_locator)
                                    if elements:
                                        # logger.info(f"Found {field}: {elements[0].text}")
                                        book_info[field] = elements[0].text
                                        break
                                    else:
                                        # If not found directly, try finding within title container
                                        try:
                                            # Use the title_container strategy from BOOK_CONTAINER_RELATIONSHIPS
                                            (
                                                title_container_strategy,
                                                title_container_locator,
                                            ) = BOOK_CONTAINER_RELATIONSHIPS["title_container"]
                                            title_container = container.find_element(
                                                title_container_strategy, title_container_locator
                                            )
                                            elements = title_container.find_elements(
                                                strategy, relative_locator
                                            )
                                            if elements:
                                                logger.info(
                                                    f"Found {field} in title container: {elements[0].text}"
                                                )
                                                book_info[field] = elements[0].text
                                                break
                                        except NoSuchElementException:
                                            # Expected exception when element not found, don't log
                                            pass
                                        except Exception as e:
                                            # Only log unexpected exceptions
                                            logger.error(
                                                f"Unexpected error finding {field} in title container: {e}"
                                            )

                                        # Only log at debug level that we didn't find the element
                                        # logger.debug(f"No {field} found with {strategy}: {locator}")
                                except NoSuchElementException:
                                    # Expected exception when element not found, don't log
                                    continue
                                except Exception as e:
                                    # Only log unexpected exceptions
                                    logger.error(f"Unexpected error finding {field}: {e}")
                                    continue

                        # If we still don't have author, try to extract from content-desc
                        if not book_info["author"] and container.get_attribute("content-desc"):
                            content_desc = container.get_attribute("content-desc")
                            logger.debug(f"Content desc: {content_desc}")

                            # Try each pattern in the content-desc strategies
                            for pattern in CONTENT_DESC_STRATEGIES["patterns"]:
                                try:
                                    # Split the content-desc by the specified delimiter
                                    parts = content_desc.split(pattern["split_by"])

                                    # Skip this pattern if the content-desc contains any skip terms
                                    if "skip_if_contains" in pattern and any(
                                        skip_term in content_desc for skip_term in pattern["skip_if_contains"]
                                    ):
                                        continue

                                    # Get the author part based on the index
                                    if len(parts) > abs(pattern["author_index"]):
                                        potential_author = parts[pattern["author_index"]]

                                        # Apply any processing function
                                        if "process" in pattern:
                                            potential_author = pattern["process"](potential_author)

                                        # Apply cleanup rules
                                        for rule in CONTENT_DESC_STRATEGIES["cleanup_rules"]:
                                            potential_author = re.sub(
                                                rule["pattern"], rule["replace"], potential_author
                                            )

                                        # Skip if the potential author contains non-author terms
                                        non_author_terms = CONTENT_DESC_STRATEGIES["non_author_terms"]
                                        if any(
                                            non_author in potential_author.lower()
                                            for non_author in non_author_terms
                                        ):
                                            continue

                                        # Skip if the potential author is empty after cleanup
                                        potential_author = potential_author.strip()
                                        if not potential_author:
                                            continue

                                        # logger.info(f"Extracted author from content-desc: {potential_author}")
                                        book_info["author"] = potential_author
                                        break
                                except Exception as e:
                                    # Only log at debug level for content-desc parsing errors
                                    logger.debug(f"Error parsing content-desc with pattern {pattern}: {e}")
                                    continue

                        if book_info["title"]:
                            # If we're looking for a specific book
                            if normalized_target and self._title_match(book_info["title"], target_title):
                                # Find the button and parent container for download status
                                for strategy, locator in BOOK_METADATA_IDENTIFIERS["title"]:
                                    try:
                                        button = container.find_element(strategy, locator)
                                        logger.info(
                                            f"Found button: {button.get_attribute('content-desc')} looking for parent container"
                                        )

                                        # Try to find the parent RelativeLayout using XPath
                                        try:
                                            # Use the parent_by_title strategy from BOOK_CONTAINER_RELATIONSHIPS
                                            (
                                                parent_strategy,
                                                parent_locator_template,
                                            ) = BOOK_CONTAINER_RELATIONSHIPS["parent_by_title"]
                                            parent_locator = parent_locator_template.format(
                                                title=self._xpath_literal(book_info["title"])
                                            )
                                            parent_container = container.find_element(
                                                parent_strategy, parent_locator
                                            )
                                        except NoSuchElementException:
                                            # If that fails, try finding any ancestor RelativeLayout
                                            try:
                                                # Use the ancestor_by_title strategy from BOOK_CONTAINER_RELATIONSHIPS
                                                (
                                                    ancestor_strategy,
                                                    ancestor_locator_template,
                                                ) = BOOK_CONTAINER_RELATIONSHIPS["ancestor_by_title"]
                                                ancestor_locator = ancestor_locator_template.format(
                                                    title=self._xpath_literal(book_info["title"])
                                                )
                                                parent_container = container.find_element(
                                                    ancestor_strategy, ancestor_locator
                                                )
                                            except NoSuchElementException:
                                                logger.debug(
                                                    f"Could not find parent container for {book_info['title']}"
                                                )
                                                continue

                                        # Only return a match if titles actually match
                                        if self._title_match(book_info["title"], target_title):
                                            logger.info(f"Found match for '{target_title}'")
                                            return parent_container, button, book_info
                                        else:
                                            # Continue searching rather than returning a false match
                                            continue
                                    except NoSuchElementException:
                                        logger.debug(f"Could not find button for {book_info['title']}")
                                        continue
                                    except StaleElementReferenceException:
                                        logger.debug(
                                            f"Stale element reference when finding button for {book_info['title']}"
                                        )
                                        continue
                                    except Exception as e:
                                        logger.error(
                                            f"Unexpected error finding button for {book_info['title']}: {e}"
                                        )
                                        continue

                            # Add book to list if not already seen
                            if book_info["title"] not in seen_titles:
                                seen_titles.add(book_info["title"])
                                books.append(book_info)
                                new_books_found = True
                                logger.info(f"Found book: {book_info}")
                        else:
                            logger.info(f"Container has no book info, skipping: {book_info}")
                    except StaleElementReferenceException:
                        logger.debug("Stale element reference, skipping container")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing container: {e}")
                        continue

                # If we've found no new books on this screen, we're done scrolling
                if not new_books_found:
                    logger.info("No new books found on this screen, stopping scroll")
                    break

                # If we've found the same books as before, we're at the end
                if seen_titles == previous_titles:
                    logger.info("Same books as previous scroll, stopping")
                    break

                # Scroll down to see more books
                self.driver.swipe(screen_size["width"] // 2, start_y, screen_size["width"] // 2, end_y, 1000)
                time.sleep(1)  # Wait for scroll to complete

            logger.info(f"Found total of {len(books)} unique books")

            # If we were looking for a specific book but didn't find it
            if target_title:
                # Check if this book was found but we couldn't grab the container
                found_matching_title = False
                for book in books:
                    if book.get("title") and self._title_match(book["title"], target_title):
                        found_matching_title = True
                        logger.info(
                            f"Book title matched using _title_match: '{book['title']}' -> '{target_title}'"
                        )
                        try:
                            # Try to find the book button directly by content-desc
                            buttons = self.driver.find_elements(
                                AppiumBy.XPATH,
                                f"//android.widget.Button[contains(@content-desc, '{book['title'].split()[0]}')]",
                            )
                            if buttons:
                                logger.info(f"Found {len(buttons)} buttons matching first word of title")
                                parent_container = buttons[0]
                                return parent_container, buttons[0], book
                        except Exception as e:
                            logger.error(f"Error finding book button by content-desc: {e}")

                if not found_matching_title:
                    logger.warning(f"Book not found after searching entire library: {target_title}")
                    logger.info(f"Available titles: {', '.join(seen_titles)}")
                return None, None, None

            return books

        except Exception as e:
            logger.error(f"Error scrolling through library: {e}")
            if target_title:
                return None, None, None
            return []

    def check_for_sign_in_button(self):
        """Check if the sign-in button is present in the library view.

        Returns:
            bool: True if sign-in button is present, False otherwise
        """
        from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES

        try:
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    if button.is_displayed():
                        logger.info(f"Found sign-in button in library view using {strategy}")
                        return True
                except NoSuchElementException:
                    continue

            # Also check by ID based on the XML
            try:
                button = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in")
                if button.is_displayed():
                    logger.info("Found sign-in button by ID")
                    return True
            except NoSuchElementException:
                pass

            # Check for empty library logged out container
            try:
                container = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/empty_library_logged_out"
                )
                if container.is_displayed():
                    logger.info("Found empty library logged out container")
                    return True
            except NoSuchElementException:
                pass

            logger.info("No sign-in button detected in library view")
            return False

        except Exception as e:
            logger.error(f"Error checking for sign-in button: {e}")
            return False

    def handle_library_sign_in(self):
        """Handle sign-in when in library view with sign-in button.

        This method clicks the sign-in button when detected in the library view,
        which should transition to the authentication flow.

        Returns:
            bool: True if successfully clicked sign-in button, False otherwise
        """
        from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES

        try:
            logger.info("Attempting to handle library sign-in...")

            # Check for and click sign-in button using strategies
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    if button.is_displayed():
                        logger.info(f"Found and clicking sign-in button using {strategy}")
                        button.click()
                        time.sleep(1)  # Wait for navigation
                        return True
                except NoSuchElementException:
                    continue

            # Try by ID based on XML
            try:
                button = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in")
                if button.is_displayed():
                    logger.info("Found and clicking sign-in button by ID")
                    button.click()
                    time.sleep(1)  # Wait for navigation
                    return True
            except NoSuchElementException:
                pass

            logger.error("Could not find sign-in button to click")
            return False

        except Exception as e:
            logger.error(f"Error handling library sign-in: {e}")
            return False

    def get_book_titles(self):
        """Get a list of all books in the library with their metadata."""
        try:
            # Ensure we're in the library view
            if not self.navigate_to_library():
                logger.error("Failed to navigate to library")
                return []

            # Check if we need to sign in
            if self.check_for_sign_in_button():
                logger.warning("Library view shows sign-in button - authentication required")
                return None  # Return None to indicate authentication needed

            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    return []
                logger.info("Successfully switched to list view")

            # Scroll to top of list
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            return self._scroll_through_library()

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            return []

    def _normalize_title(self, title: str) -> str:
        """
        Normalize a title for comparison.
        Instead of removing all non-alphanumeric chars, we'll keep more characters
        and focus on substring matching rather than exact matching.
        """
        if not title:
            return ""
        # First convert to lowercase
        normalized = title.lower()
        # Replace special characters with spaces
        for char in ",:;\"'!@#$%^&*()[]{}_+-=<>?/\\|~`":
            normalized = normalized.replace(char, " ")
        # Replace multiple spaces with single space and strip
        normalized = " ".join(normalized.split())
        return normalized

    def _title_match(self, title1: str, title2: str) -> bool:
        """
        Check if titles match exactly after normalization.
        Since we're getting titles from the same source, we should require exact matches.
        """
        if not title1 or not title2:
            return False

        # For exact matching, normalize both titles and compare
        norm1 = self._normalize_title(title1)
        norm2 = self._normalize_title(title2)

        # Only return true for exact matches after normalization
        return norm1 == norm2

    def find_book(self, book_title: str) -> bool:
        """Find and click a book button by title. If the book isn't downloaded, initiate download and wait for completion."""
        try:
            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    return False
                logger.info("Successfully switched to list view")

            # Scroll to top first
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Search for the book
            parent_container, button, book_info = self._scroll_through_library(book_title)
            if not parent_container:
                return False

            # Check download status and handle download if needed
            content_desc = parent_container.get_attribute("content-desc")
            logger.info(f"Book content description: {content_desc}")
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
                        # Using @text attribute for exact matching
                        xpath = f"//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text='{book_info['title']}' ]]"
                        parent_container = self.driver.find_element(AppiumBy.XPATH, xpath)
                        content_desc = parent_container.get_attribute("content-desc")
                        logger.info(
                            f"Checking download status (attempt {attempt + 1}/{max_attempts}): {content_desc}"
                        )

                        if "Book downloaded" in content_desc:
                            logger.info("Book has finished downloading")
                            time.sleep(1)  # Short wait for UI to stabilize
                            parent_container.click()
                            logger.info("Clicked book button after download")

                            # Check if we successfully left the library view
                            try:
                                self.driver.find_element(
                                    AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                                )
                                logger.warning(
                                    "Still in library view after clicking downloaded book, trying again..."
                                )
                                time.sleep(1)
                                parent_container.click()
                                logger.info("Clicked book again")
                            except NoSuchElementException:
                                logger.info("Successfully left library view")

                            return True

                        # If we see an error in the content description, abort
                        if any(error in content_desc.lower() for error in ["error", "failed"]):
                            logger.error(f"Download failed: {content_desc}")
                            return False

                        time.sleep(1)
                    except Exception as e:
                        logger.error(f"Error checking download status: {e}")
                        time.sleep(1)
                        continue

                logger.error("Timed out waiting for book to download")
                return False

            # For already downloaded books, just click and verify
            logger.info(f"Found downloaded book: {book_info['title']}")
            button.click()
            logger.info("Clicked book button")

            # Wait a moment for any animations
            time.sleep(1)

            # Verify the click worked by checking we're no longer in library view
            try:
                self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                logger.error("Still in library view after clicking book")
                # Try clicking one more time
                button.click()
                time.sleep(1)
            except NoSuchElementException:
                logger.info("Successfully left library view")
                pass

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

    def _xpath_literal(self, s):
        """
        Create a valid XPath literal for a string that may contain both single and double quotes.
        Using a more robust implementation that handles special characters better.
        """
        if not s:
            return "''"

        # Use resource-id-based XPath instead of text-based when apostrophes are present
        if "'" in s:
            # Use a partial text match instead that doesn't include the apostrophe
            # Split the string at apostrophes and use contains() for each part
            parts = s.split("'")
            conditions = []

            for part in parts:
                if part:  # Only add non-empty parts
                    conditions.append(f"contains(., '{part}')")

            # Join all conditions with 'and'
            if conditions:
                return " and ".join(conditions)
            else:
                return "true()"  # Fallback if there are no valid parts
        else:
            # For strings without apostrophes, use the simple approach
            return f"'{s}'"
