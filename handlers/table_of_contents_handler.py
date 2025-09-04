"""
Table of Contents handler for Kindle Automator.

This module provides functionality to access and navigate the Table of Contents
in the Kindle app.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from handlers.about_book_popover_handler import AboutBookPopoverHandler
from server.logging_config import store_page_source
from views.reading.interaction_strategies import (
    FOOTER_PAGE_NUMBER_TAP_TARGET,
    PAGE_POSITION_TEXT,
)
from views.reading.view_strategies import (
    CHAPTER_ITEM_IDENTIFIERS,
    CHAPTER_PAGE_NUMBER_IDENTIFIERS,
    PAGE_NAVIGATION_ZONES,
    PAGE_POSITION_POPOVER_IDENTIFIERS,
    READING_PROGRESS_IDENTIFIERS,
    READING_TOOLBAR_IDENTIFIERS,
    TABLE_OF_CONTENTS_BUTTON_IDENTIFIERS,
    TABLE_OF_CONTENTS_CLOSE_BUTTON_IDENTIFIERS,
    TABLE_OF_CONTENTS_LIST_IDENTIFIERS,
    TABLE_OF_CONTENTS_VIEW_IDENTIFIERS,
)

logger = logging.getLogger(__name__)


class TableOfContentsHandler:
    """Handler for Table of Contents operations in the Kindle app."""

    def __init__(self, automator):
        """Initialize the Table of Contents handler.

        Args:
            automator: The Kindle Automator instance.
        """
        self.automator = automator
        self.driver = automator.driver

    def get_table_of_contents(self, title: Optional[str] = None) -> Tuple[Dict, int]:
        """Get the table of contents for the current book.

        Args:
            title: Optional book title to ensure we're in the correct book.

        Returns:
            Tuple of (response_data, status_code)
        """
        try:
            # First check if we're already in the Table of Contents view
            if self._is_table_of_contents_open():
                logger.info("Already in Table of Contents view")
                # Skip directly to collecting chapters
                chapters = self._collect_all_chapters()

                # Close the Table of Contents to get back to popover
                if not self._close_table_of_contents():
                    logger.warning("Failed to close Table of Contents cleanly")

                # After closing ToC, we should be back at the page position popover
                # Wait for popover to be visible again
                try:
                    WebDriverWait(self.driver, 1).until(
                        lambda d: any(
                            d.find_element(s, l).is_displayed()
                            for s, l in PAGE_POSITION_POPOVER_IDENTIFIERS
                            if self._safe_find_element(s, l)
                        )
                    )
                except TimeoutException:
                    pass
                current_position = self._get_popover_page_position()
                if not current_position:
                    # Try normal page position as fallback
                    current_position = self._get_current_page_position()

                logger.info(f"Got position after closing ToC: {current_position}")

                # Close the popover and hide reading controls by tapping center
                self._hide_reading_controls()

                response_data = {
                    "success": True,
                    "position": current_position or {"note": "Position not available"},
                    "chapters": chapters,
                    "chapter_count": len(chapters),
                }

                return response_data, 200

            # First check for and dismiss the About Book popover if present
            about_book_handler = AboutBookPopoverHandler(self.driver)
            if about_book_handler.is_popover_present():
                logger.info("About Book popover detected - dismissing it")
                about_book_handler.dismiss_popover()
                # Wait for popover to be dismissed
                try:
                    WebDriverWait(self.driver, 1).until(lambda d: not about_book_handler.is_popover_present())
                except TimeoutException:
                    pass

            # Check if we're in reading view
            if not self.automator.state_machine.is_reading_view():
                if title:
                    logger.info(f"Not in reading view, attempting to open book: {title}")
                    # Try to open the book
                    if not self._open_book_if_needed(title):
                        return {"error": f"Failed to open book: {title}"}, 500
                else:
                    return {"error": "Not in reading view. Please provide title parameter."}, 400

            # Make sure we have the reading controls visible
            if not self._ensure_reading_controls_visible():
                return {"error": "Failed to show reading controls"}, 500

            # Get current page position before opening ToC
            current_position = self._get_current_page_position()
            logger.info(f"Current position: {current_position}")

            # Open the page position popover
            if not self._open_page_position_popover():
                return {"error": "Failed to open page position popover"}, 500

            # Get page position from the popover
            popover_position = self._get_popover_page_position()
            if popover_position:
                logger.info(f"Page position from popover: {popover_position}")
            else:
                popover_position = current_position

            # Store page source for debugging
            store_page_source(self.driver.page_source, "page_position_popover")

            # Click the Table of Contents button
            if not self._open_table_of_contents():
                return {"error": "Failed to open Table of Contents"}, 500

            # Store page source for ToC view
            store_page_source(self.driver.page_source, "table_of_contents_view")

            # Scroll to top of ToC list
            self._scroll_to_top_of_toc()

            # Collect all chapters
            chapters = self._collect_all_chapters()

            # Close the Table of Contents
            if not self._close_table_of_contents():
                logger.warning("Failed to close Table of Contents cleanly")

            # After closing ToC, we should be back at the page position popover
            # Wait for popover to be visible again
            try:
                WebDriverWait(self.driver, 1).until(
                    lambda d: any(
                        self._safe_find_element(s, l) and d.find_element(s, l).is_displayed()
                        for s, l in PAGE_POSITION_POPOVER_IDENTIFIERS
                    )
                )
            except TimeoutException:
                pass
            final_position = self._get_popover_page_position()
            if final_position:
                logger.info(f"Got updated position from popover after ToC: {final_position}")
            else:
                # Use the position we got earlier as fallback
                final_position = popover_position or current_position

            # Hide reading controls by tapping center
            self._hide_reading_controls()

            response_data = {
                "success": True,
                "position": final_position,
                "chapters": chapters,
                "chapter_count": len(chapters),
            }

            return response_data, 200

        except Exception as e:
            logger.error(f"Error getting table of contents: {e}", exc_info=True)
            # Try to recover by closing any open dialogs
            try:
                self._close_table_of_contents()
                self._hide_reading_controls()
            except:
                pass
            return {"error": str(e)}, 500

    def _open_book_if_needed(self, title: str) -> bool:
        """Open a book if not already in reading view.

        Args:
            title: The book title to open.

        Returns:
            bool: True if book was opened successfully or already open.
        """
        try:
            # Get current state
            current_state = self.automator.state_machine.update_current_state()
            logger.info(f"Current state: {current_state}")

            # Check if we're already reading this book
            profile = self.automator.profile_manager.get_current_profile()
            sindarin_email = profile.get("email") if profile else None

            if sindarin_email and hasattr(self.automator, "server_ref") and self.automator.server_ref:
                current_book = self.automator.server_ref.get_current_book(sindarin_email)
                if current_book and current_book.lower() == title.lower():
                    logger.info(f"Already reading book: {title}")
                    return True

            # Transition to library
            from views.core.app_state import AppState

            if self.automator.state_machine.transition_to_library() != AppState.LIBRARY:
                logger.error("Failed to transition to library")
                return False

            # Open the book
            logger.info(f"Opening book: {title}")
            if not self.automator.state_machine.library_handler.open_book(title):
                logger.error(f"Failed to open book: {title}")
                return False

            # Wait for book to open by checking for reading view
            try:
                WebDriverWait(self.driver, 3).until(lambda d: self.automator.state_machine.is_reading_view())
            except TimeoutException:
                logger.warning("Timeout waiting for reading view after opening book")

            # Verify we're in reading view
            if not self.automator.state_machine.is_reading_view():
                logger.error("Not in reading view after opening book")
                return False

            return True

        except Exception as e:
            logger.error(f"Error opening book: {e}", exc_info=True)
            return False

    def _ensure_reading_controls_visible(self) -> bool:
        """Ensure the reading controls (toolbar) are visible.

        Returns:
            bool: True if controls are visible or were made visible.
        """
        try:
            # Check if controls are already visible
            for strategy, locator in READING_TOOLBAR_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.debug("Reading controls already visible")
                        return True
                except NoSuchElementException:
                    continue

            # Tap center to show controls
            window_size = self.driver.get_window_size()
            center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
            center_y = window_size["height"] // 2
            self.driver.tap([(center_x, center_y)])
            logger.debug("Tapped center to show controls")

            # Wait for controls to appear
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
            logger.debug("Reading controls now visible")
            return True

        except TimeoutException:
            logger.error("Timeout waiting for reading controls")
            return False
        except Exception as e:
            logger.error(f"Error ensuring reading controls visible: {e}", exc_info=True)
            return False

    def _get_current_page_position(self) -> Optional[Dict]:
        """Get the current page position from the footer.

        Returns:
            Dict with page info or None if not found.
        """
        try:
            for strategy, locator in READING_PROGRESS_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        text = element.text.strip()
                        logger.debug(f"Found progress text: {text}")

                        # Parse the text (e.g., "Page 82 of 287 • 28%")
                        import re

                        page_match = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
                        percent_match = re.search(r"(\d+)%", text)

                        result = {}
                        if page_match:
                            result["current_page"] = int(page_match.group(1))
                            result["total_pages"] = int(page_match.group(2))
                        if percent_match:
                            result["percentage"] = int(percent_match.group(1))

                        return result if result else None
                except NoSuchElementException:
                    continue

            return None

        except Exception as e:
            logger.error(f"Error getting current page position: {e}", exc_info=True)
            return None

    def _open_page_position_popover(self) -> bool:
        """Open the page position popover by tapping the footer page number.

        Returns:
            bool: True if popover was opened successfully.
        """
        try:
            # First check if popover is already visible
            for strategy, locator in PAGE_POSITION_POPOVER_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info("Page position popover is already visible")
                        return True
                except NoSuchElementException:
                    continue

            # If not visible, try to open it
            # Find and tap the footer page number
            for strategy, locator in FOOTER_PAGE_NUMBER_TAP_TARGET:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        element.click()
                        logger.info("Tapped footer page number to open popover")
                        break
                except NoSuchElementException:
                    continue
            else:
                logger.error("Could not find footer page number to tap")
                return False

            # Wait for popover to appear
            def popover_visible(driver):
                for strategy, locator in PAGE_POSITION_POPOVER_IDENTIFIERS:
                    try:
                        element = driver.find_element(strategy, locator)
                        if element.is_displayed():
                            return True
                    except NoSuchElementException:
                        continue
                return False

            WebDriverWait(self.driver, 3).until(popover_visible)
            logger.info("Page position popover is now visible")
            return True

        except TimeoutException:
            logger.error("Timeout waiting for page position popover")
            return False
        except Exception as e:
            logger.error(f"Error opening page position popover: {e}", exc_info=True)
            return False

    def _get_popover_page_position(self) -> Optional[Dict]:
        """Get the page position from the popover.

        Returns:
            Dict with page info or None if not found.
        """
        try:
            for strategy, locator in PAGE_POSITION_TEXT:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        text = element.text.strip()
                        logger.debug(f"Found popover position text: {text}")

                        # Parse the text
                        import re

                        page_match = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
                        location_match = re.search(r"Location\s+(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
                        percent_match = re.search(r"(\d+)%", text)

                        result = {}
                        if page_match:
                            result["current_page"] = int(page_match.group(1))
                            result["total_pages"] = int(page_match.group(2))
                        if location_match:
                            result["current_location"] = int(location_match.group(1))
                            result["total_locations"] = int(location_match.group(2))
                        if percent_match:
                            result["percentage"] = int(percent_match.group(1))

                        return result if result else None
                except NoSuchElementException:
                    continue

            return None

        except Exception as e:
            logger.error(f"Error getting popover page position: {e}", exc_info=True)
            return None

    def _open_table_of_contents(self) -> bool:
        """Open the Table of Contents from the page position popover.

        Returns:
            bool: True if ToC was opened successfully.
        """
        try:
            # Find and tap the Table of Contents button
            for strategy, locator in TABLE_OF_CONTENTS_BUTTON_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        element.click()
                        logger.info("Tapped Table of Contents button")
                        break
                except NoSuchElementException:
                    continue
            else:
                logger.error("Could not find Table of Contents button")
                return False

            # Wait for ToC view to appear (with proper polling)
            def toc_visible(driver):
                for strategy, locator in TABLE_OF_CONTENTS_VIEW_IDENTIFIERS:
                    try:
                        element = driver.find_element(strategy, locator)
                        if element.is_displayed():
                            return True
                    except NoSuchElementException:
                        continue
                return False

            # Use 2 second timeout with 0.1 second polling interval for faster response
            WebDriverWait(self.driver, 2, poll_frequency=0.1).until(toc_visible)
            logger.info("Table of Contents is now visible")
            return True

        except TimeoutException:
            logger.error("Timeout waiting for Table of Contents")
            return False
        except Exception as e:
            logger.error(f"Error opening Table of Contents: {e}", exc_info=True)
            return False

    def _is_table_of_contents_open(self) -> bool:
        """Check if the Table of Contents view is currently open.

        Returns:
            bool: True if ToC is open, False otherwise.
        """
        try:
            # Check for ToC view elements
            for strategy, locator in TABLE_OF_CONTENTS_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Table of Contents is open (found: {locator})")
                        return True
                except NoSuchElementException:
                    continue

            # Also check for ToC list identifiers as backup
            for strategy, locator in TABLE_OF_CONTENTS_LIST_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Table of Contents is open (found list: {locator})")
                        return True
                except NoSuchElementException:
                    continue

            return False
        except Exception as e:
            logger.error(f"Error checking if ToC is open: {e}", exc_info=True)
            return False

    def _add_chapter_if_new(
        self, chapters: List[Dict], seen_chapters: set, title_text: str, page_text: str = None
    ) -> bool:
        """Add a chapter to the list if it's new.

        Args:
            chapters: List of chapters to add to
            seen_chapters: Set of already seen chapter titles
            title_text: Chapter title
            page_text: Optional page number as string

        Returns:
            bool: True if chapter was added, False if already seen
        """
        if not title_text or title_text in seen_chapters:
            return False

        chapter = {"title": title_text}
        if page_text and page_text.isdigit():
            chapter["page"] = int(page_text)
            logger.info(f"Found page {page_text} for chapter '{title_text}'")

        chapters.append(chapter)
        seen_chapters.add(title_text)
        page_str = f"(p. {chapter.get('page')})" if chapter.get("page") else ""
        logger.info(f"Added chapter: {chapter['title']} {page_str}")
        return True

    def _scroll_toc_in_direction(self, direction: str = "up", num_swipes: int = 3):
        """Scroll the Table of Contents in a specific direction.

        Args:
            direction: "up" to scroll to top, "down" to scroll to bottom
            num_swipes: Number of swipes to perform
        """
        try:
            # Find the ToC list to ensure it's displayed
            toc_list = None
            for strategy, locator in TABLE_OF_CONTENTS_LIST_IDENTIFIERS:
                try:
                    toc_list = self.driver.find_element(strategy, locator)
                    if toc_list.is_displayed():
                        break
                except NoSuchElementException:
                    continue

            if not toc_list:
                logger.warning("Could not find ToC list to scroll")
                return

            # Get window dimensions for swipe
            window_size = self.driver.get_window_size()
            start_x = window_size["width"] // 2

            if direction == "up":
                # Swipe down to scroll up (to top)
                start_y = int(window_size["height"] * 0.3)
                end_y = int(window_size["height"] * 0.8)
            else:
                # Swipe up to scroll down (to bottom)
                start_y = int(window_size["height"] * 0.8)
                end_y = int(window_size["height"] * 0.3)

            # Perform swipes
            for i in range(num_swipes):
                self.driver.swipe(start_x, start_y, start_x, end_y, duration=300)
                # Wait for scroll to complete by checking if elements are stable
                if i < num_swipes - 1:  # Don't wait after last swipe
                    try:
                        WebDriverWait(self.driver, 0.2).until(
                            lambda d: len(
                                d.find_elements(AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title")
                            )
                            > 0
                        )
                    except TimeoutException:
                        pass

            logger.info(f"Scrolled {direction} in Table of Contents ({num_swipes} swipes)")

        except Exception as e:
            logger.error(f"Error scrolling {direction} in ToC: {e}", exc_info=True)

    def _scroll_to_top_of_toc(self):
        """Scroll to the top of the Table of Contents list."""
        self._scroll_toc_in_direction("up", num_swipes=3)

    def _collect_all_chapters(self) -> List[Dict]:
        """Collect all chapters from the Table of Contents.

        Returns:
            List of chapter dictionaries with title and optional page number.
        """
        chapters = []
        seen_chapters = set()

        try:
            # Find the ToC list
            toc_list = None
            for strategy, locator in TABLE_OF_CONTENTS_LIST_IDENTIFIERS:
                try:
                    toc_list = self.driver.find_element(strategy, locator)
                    if toc_list.is_displayed():
                        logger.info(f"Found ToC list using {strategy}={locator}")
                        break
                    else:
                        logger.debug(f"Found ToC list element but not displayed: {locator}")
                except NoSuchElementException:
                    logger.debug(f"ToC list element not found: {locator}")
                    continue
                except Exception as e:
                    logger.debug(f"Error finding ToC list element {locator}: {e}")
                    continue

            if not toc_list:
                logger.warning("Could not find ToC list - trying direct element search")
                # Fall back to directly searching for chapter elements without the list container

            # Scroll and collect chapters
            window_size = self.driver.get_window_size()
            start_x = window_size["width"] // 2
            start_y = int(window_size["height"] * 0.7)
            end_y = int(window_size["height"] * 0.3)

            no_new_chapters_count = 0
            max_scrolls = 20  # Prevent infinite scrolling

            for scroll_count in range(max_scrolls):
                # Get visible chapter items by finding pairs of title and position elements
                new_chapters_found = False

                # Find all chapter titles and positions - work even without the list container
                try:
                    # Get all list items in the ToC (each item contains a title and possibly a page number)
                    # Try to find the parent containers that hold both title and position
                    list_items = []

                    # First try to find view containers which hold both title and position
                    try:
                        list_items = self.driver.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/toc_entry_view_container"
                        )
                        if list_items:
                            logger.info(f"Found {len(list_items)} ToC entry view containers")
                    except:
                        pass

                    # Fallback to finding all visible title elements and their parent containers
                    if not list_items:
                        title_elements = self.driver.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"
                        )
                        logger.info(f"Found {len(title_elements)} title elements")

                        for title_elem in title_elements:
                            try:
                                if not title_elem.is_displayed():
                                    continue

                                title_text = title_elem.text.strip()
                                page_text = None

                                # Try to find position element as sibling
                                try:
                                    parent = title_elem.find_element(AppiumBy.XPATH, "..")
                                    grandparent = parent.find_element(AppiumBy.XPATH, "..")
                                    position_elem = grandparent.find_element(
                                        AppiumBy.ID, "com.amazon.kindle:id/toc_entry_position"
                                    )
                                    if position_elem and position_elem.is_displayed():
                                        page_text = position_elem.text.strip()
                                except (NoSuchElementException, Exception):
                                    pass

                                if self._add_chapter_if_new(chapters, seen_chapters, title_text, page_text):
                                    new_chapters_found = True

                            except Exception as e:
                                logger.warning(f"Error processing title element: {e}")
                                continue
                    else:
                        # Process view container items
                        for item in list_items:
                            try:
                                # Find title within this container
                                title_elem = item.find_element(
                                    AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"
                                )
                                if not title_elem.is_displayed():
                                    continue

                                title_text = title_elem.text.strip()
                                page_text = None

                                # Try to find position within the end_align_items container
                                try:
                                    end_align_container = item.find_element(
                                        AppiumBy.ID, "com.amazon.kindle:id/toc_entry_end_align_items"
                                    )
                                    position_elem = end_align_container.find_element(
                                        AppiumBy.ID, "com.amazon.kindle:id/toc_entry_position"
                                    )
                                    if position_elem and position_elem.is_displayed():
                                        page_text = position_elem.text.strip()
                                except (NoSuchElementException, Exception):
                                    pass

                                if self._add_chapter_if_new(chapters, seen_chapters, title_text, page_text):
                                    new_chapters_found = True

                            except Exception as e:
                                logger.warning(f"Error processing ToC entry: {e}")
                                continue

                except Exception as e:
                    logger.warning(f"Error finding chapter elements: {e}", exc_info=True)
                    # Fallback to XPATH search - same logic as above
                    logger.info("Using XPATH fallback to find chapters")

                if not new_chapters_found:
                    no_new_chapters_count += 1
                    if no_new_chapters_count >= 3:
                        logger.info("No new chapters found after 3 scrolls, assuming end of list")
                        break
                else:
                    no_new_chapters_count = 0

                # Scroll down to see more chapters
                if scroll_count < max_scrolls - 1:
                    self.driver.swipe(start_x, start_y, start_x, end_y, duration=300)
                    # Wait for scroll to settle by checking for elements
                    try:
                        WebDriverWait(self.driver, 0.2).until(
                            lambda d: len(
                                d.find_elements(AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title")
                            )
                            > 0
                        )
                    except TimeoutException:
                        pass

            logger.info(f"Collected {len(chapters)} chapters from Table of Contents")

        except Exception as e:
            logger.error(f"Error collecting chapters: {e}", exc_info=True)

        return chapters

    def _close_table_of_contents(self) -> bool:
        """Close the Table of Contents view.

        Returns:
            bool: True if ToC was closed successfully.
        """
        try:
            # Find and tap the close button
            for strategy, locator in TABLE_OF_CONTENTS_CLOSE_BUTTON_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        element.click()
                        logger.info("Tapped ToC close button")
                        # Wait for ToC to close
                        try:
                            WebDriverWait(self.driver, 1).until(
                                lambda d: not self._is_table_of_contents_open()
                            )
                        except TimeoutException:
                            pass
                        return True
                except NoSuchElementException:
                    continue

            # If no close button found, try tapping outside or using back
            logger.warning("No close button found, trying back gesture")
            self.driver.back()
            # Wait for ToC to close
            try:
                WebDriverWait(self.driver, 1).until(lambda d: not self._is_table_of_contents_open())
            except TimeoutException:
                pass
            return True

        except Exception as e:
            logger.error(f"Error closing Table of Contents: {e}", exc_info=True)
            return False

    def _hide_reading_controls(self):
        """Hide the reading controls by tapping the center of the screen."""
        try:
            window_size = self.driver.get_window_size()
            center_x = int(window_size["width"] * PAGE_NAVIGATION_ZONES["center"])
            center_y = window_size["height"] // 2
            self.driver.tap([(center_x, center_y)])
            logger.debug("Tapped center to hide controls")
            # Wait for controls to disappear
            try:
                WebDriverWait(self.driver, 0.5).until(
                    lambda d: not any(
                        self._safe_find_element(s, l) and d.find_element(s, l).is_displayed()
                        for s, l in READING_TOOLBAR_IDENTIFIERS
                    )
                )
            except TimeoutException:
                pass
        except Exception as e:
            logger.error(f"Error hiding reading controls: {e}", exc_info=True)

    def _safe_find_element(self, strategy, locator):
        """Safely find an element without raising exceptions.

        Returns:
            Element if found, None otherwise
        """
        try:
            return self.driver.find_element(strategy, locator)
        except NoSuchElementException:
            return None

    def _try_find_and_click_chapter(self, chapter_name: str, normalized_requested: str) -> bool:
        """Try to find and click a chapter without scrolling.

        Args:
            chapter_name: Original chapter name
            normalized_requested: Normalized version for comparison

        Returns:
            bool: True if chapter was found and clicked
        """
        try:
            # Find all ToC entry containers
            list_items = self.driver.find_elements(
                AppiumBy.ID, "com.amazon.kindle:id/toc_entry_view_container"
            )

            if not list_items:
                # Fallback to finding title elements directly
                title_elements = self.driver.find_elements(
                    AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"
                )

                for title_elem in title_elements:
                    try:
                        if not title_elem.is_displayed():
                            continue

                        title_text = title_elem.text.strip()
                        # Normalize the chapter title for comparison
                        normalized_title = (
                            "".join(c for c in title_text if c.isalnum() or c.isspace()).lower().strip()
                        )

                        # Check for exact normalized match only
                        if normalized_requested == normalized_title:
                            logger.info(f"Found matching chapter immediately: {title_text}")
                            title_elem.click()
                            return True
                    except Exception as e:
                        logger.debug(f"Error checking title element: {e}")
                        continue
            else:
                # Process container items
                for item in list_items:
                    try:
                        title_elem = item.find_element(AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title")
                        if not title_elem.is_displayed():
                            continue

                        title_text = title_elem.text.strip()
                        # Normalize the chapter title for comparison
                        normalized_title = (
                            "".join(c for c in title_text if c.isalnum() or c.isspace()).lower().strip()
                        )

                        # Check for exact normalized match only
                        if normalized_requested == normalized_title:
                            logger.info(f"Found matching chapter immediately: {title_text}")
                            # Click the entire container item for better reliability
                            item.click()
                            return True
                    except Exception as e:
                        logger.debug(f"Error checking container item: {e}")
                        continue

            return False

        except Exception as e:
            logger.debug(f"Error in quick chapter find: {e}")
            return False

    def navigate_to_chapter(self, chapter_name: str, target_page: Optional[int] = None) -> Dict:
        """Navigate to a specific chapter from the table of contents.

        Args:
            chapter_name: The name of the chapter to navigate to.
            target_page: Optional page number of the target chapter to optimize scrolling.

        Returns:
            Dict with success status and optional error message.
        """
        try:
            logger.info(f"Attempting to navigate to chapter: {chapter_name}, target page: {target_page}")

            # Normalize the requested chapter name for comparison
            normalized_requested = (
                "".join(c for c in chapter_name if c.isalnum() or c.isspace()).lower().strip()
            )

            # Check if we're in reading view
            if not self.automator.state_machine.is_reading_view():
                return {"success": False, "error": "Not in reading view"}

            # Ensure reading controls are visible
            if not self._ensure_reading_controls_visible():
                return {"success": False, "error": "Failed to show reading controls"}

            # Get current page position before opening TOC (if we have target page)
            current_page = None
            if target_page is not None:
                page_info = self._get_current_page_position()
                if page_info and "current_page" in page_info:
                    current_page = page_info["current_page"]
                    logger.info(f"Current page: {current_page}, Target page: {target_page}")

            # Open page position popover
            if not self._open_page_position_popover():
                return {"success": False, "error": "Failed to open page position popover"}

            # Open Table of Contents
            if not self._open_table_of_contents():
                return {"success": False, "error": "Failed to open Table of Contents"}

            # Store page source for debugging
            store_page_source(self.driver.page_source, "toc_navigation_view")

            # OPTIMIZATION: Try to find chapter immediately without scrolling first
            found_chapter = False

            # First check if chapter is already visible (before scrolling to top)
            logger.info("Checking if chapter is immediately visible without scrolling...")
            found_chapter = self._try_find_and_click_chapter(chapter_name, normalized_requested)

            if found_chapter:
                logger.info("Chapter found immediately without scrolling")
            else:
                # Decide scroll strategy based on page numbers
                scroll_strategy = "both"  # default: search from top then bottom

                if target_page is not None and current_page is not None:
                    if target_page > current_page:
                        # Target is after current page, try scrolling down first
                        scroll_strategy = "down_first"
                        logger.info(
                            f"Target page {target_page} > current {current_page}, scrolling down first"
                        )
                    elif target_page < current_page:
                        # Target is before current page, search while scrolling up
                        scroll_strategy = "up_first"
                        logger.info(
                            f"Target page {target_page} < current {current_page}, searching while scrolling up"
                        )
                else:
                    # No page info, default to scrolling to top
                    logger.info("No page info available, defaulting to top-first search")
                    scroll_strategy = "up_first"

                # Window dimensions for scrolling
                window_size = self.driver.get_window_size()
                start_x = window_size["width"] // 2

                # Search for chapter with smart scrolling
                max_scrolls_per_direction = 15

                def search_in_direction(direction: str, max_scrolls: int) -> bool:
                    """Search for chapter while scrolling in a direction."""
                    if direction == "down":
                        start_y = int(window_size["height"] * 0.7)
                        end_y = int(window_size["height"] * 0.3)
                    else:  # up
                        start_y = int(window_size["height"] * 0.3)
                        end_y = int(window_size["height"] * 0.7)

                    for scroll_count in range(max_scrolls):
                        # Try to find and click chapter
                        if self._try_find_and_click_chapter(chapter_name, normalized_requested):
                            logger.info(f"Chapter found after {scroll_count} {direction} scrolls")
                            return True

                        # Scroll to see more chapters
                        if scroll_count < max_scrolls - 1:
                            self.driver.swipe(start_x, start_y, start_x, end_y, duration=300)
                            # Wait for scroll to settle
                            try:
                                WebDriverWait(self.driver, 0.2).until(
                                    lambda d: len(
                                        d.find_elements(AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title")
                                    )
                                    > 0
                                )
                            except TimeoutException:
                                pass
                    return False

                # Execute search based on strategy
                if scroll_strategy == "down_first":
                    # Try scrolling down first
                    logger.info("Searching while scrolling down...")
                    found_chapter = search_in_direction("down", max_scrolls_per_direction)

                    if not found_chapter:
                        # Didn't find it going down, scroll to top and search down
                        logger.info("Not found scrolling down, scrolling to top...")
                        self._scroll_to_top_of_toc()
                        found_chapter = search_in_direction("down", max_scrolls_per_direction)

                elif scroll_strategy == "up_first":
                    # Search while scrolling up towards the top
                    logger.info("Searching while scrolling up...")
                    found_chapter = search_in_direction("up", max_scrolls_per_direction)

                    if not found_chapter:
                        # If not found while scrolling up, we're probably at top now
                        # Search down from here
                        logger.info("Not found scrolling up, searching down from top...")
                        found_chapter = search_in_direction("down", max_scrolls_per_direction)

                else:  # "both"
                    # Default behavior - scroll to top and search
                    logger.info("Using default search from top...")
                    self._scroll_to_top_of_toc()
                    found_chapter = search_in_direction("down", max_scrolls_per_direction)

            if not found_chapter:
                logger.warning(f"Chapter '{chapter_name}' not found in Table of Contents")
                # Close ToC to recover
                self._close_table_of_contents()
                self._hide_reading_controls()
                return {"success": False, "error": f"Chapter '{chapter_name}' not found in Table of Contents"}

            # Wait for navigation to complete by checking for reading view
            try:
                # Wait for ToC to close and reading view to be visible
                WebDriverWait(self.driver, 2).until(lambda d: not self._is_table_of_contents_open())
                logger.info("ToC closed automatically")
            except TimeoutException:
                logger.info("ToC didn't close automatically")

            # ToC should close automatically after chapter selection
            # but check and close if still open
            if self._is_table_of_contents_open():
                logger.info("ToC still open after chapter selection, closing it")
                self._close_table_of_contents()

            # Hide any remaining controls
            self._hide_reading_controls()

            # Get current position after navigation
            position = self._get_current_page_position()

            return {
                "success": True,
                "navigated_to": chapter_name,
                "position": position or {"note": "Position not available"},
            }

        except Exception as e:
            logger.error(f"Error navigating to chapter: {e}", exc_info=True)
            # Try to recover
            try:
                if self._is_table_of_contents_open():
                    self._close_table_of_contents()
                self._hide_reading_controls()
            except:
                pass
            return {"success": False, "error": str(e)}
