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

                # Try to get current position (might not be available in ToC view)
                current_position = self._get_current_page_position()

                # Close the Table of Contents
                if not self._close_table_of_contents():
                    logger.warning("Failed to close Table of Contents cleanly")

                # Hide reading controls by tapping center
                self._hide_reading_controls()

                response_data = {
                    "success": True,
                    "position": current_position or {"note": "Position not available from ToC view"},
                    "chapters": chapters,
                    "chapter_count": len(chapters),
                }

                return response_data, 200

            # First check for and dismiss the About Book popover if present
            about_book_handler = AboutBookPopoverHandler(self.driver)
            if about_book_handler.is_popover_present():
                logger.info("About Book popover detected - dismissing it")
                about_book_handler.dismiss_popover()
                time.sleep(0.5)

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

            # Hide reading controls by tapping center
            self._hide_reading_controls()

            response_data = {
                "success": True,
                "position": popover_position or current_position,
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

            # Wait for book to open
            time.sleep(2)

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
            time.sleep(0.5)

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
                        time.sleep(0.5)
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

            # Use 5 second timeout with 0.2 second polling interval
            WebDriverWait(self.driver, 5, poll_frequency=0.2).until(toc_visible)
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

    def _scroll_to_top_of_toc(self):
        """Scroll to the top of the Table of Contents list."""
        try:
            # Find the ToC list
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

            # Scroll to top using swipe gestures
            window_size = self.driver.get_window_size()
            start_x = window_size["width"] // 2
            start_y = int(window_size["height"] * 0.3)
            end_y = int(window_size["height"] * 0.8)

            # Perform multiple swipes to ensure we're at the top
            for _ in range(3):
                self.driver.swipe(start_x, start_y, start_x, end_y, duration=500)
                time.sleep(0.2)

            logger.info("Scrolled to top of Table of Contents")

        except Exception as e:
            logger.error(f"Error scrolling to top of ToC: {e}", exc_info=True)

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
                    # Get all chapter titles
                    title_elements = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"
                    )
                    # Get all page positions
                    position_elements = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/toc_entry_position"
                    )

                    logger.info(
                        f"Scroll {scroll_count}: Found {len(title_elements)} title elements and {len(position_elements)} position elements"
                    )

                    # Process the elements (they should be in pairs)
                    for i, title_elem in enumerate(title_elements):
                        try:
                            if not title_elem.is_displayed():
                                continue

                            title_text = title_elem.text.strip()
                            if not title_text or title_text in seen_chapters:
                                continue

                            # Create chapter entry
                            chapter = {"title": title_text}

                            # Try to get the corresponding page position
                            if i < len(position_elements):
                                position_elem = position_elements[i]
                                if position_elem.is_displayed():
                                    page_text = position_elem.text.strip()
                                    if page_text.isdigit():
                                        chapter["page"] = int(page_text)

                            chapters.append(chapter)
                            seen_chapters.add(title_text)
                            new_chapters_found = True
                            logger.info(f"Added chapter: {chapter}")

                        except Exception as e:
                            logger.warning(f"Error processing chapter element: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Error finding chapter elements: {e}", exc_info=True)
                    # Fallback to XPATH search
                    try:
                        title_elements = self.driver.find_elements(
                            AppiumBy.XPATH,
                            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/toc_entry_title']",
                        )
                        position_elements = self.driver.find_elements(
                            AppiumBy.XPATH,
                            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/toc_entry_position']",
                        )

                        logger.info(
                            f"XPATH fallback: Found {len(title_elements)} titles and {len(position_elements)} positions"
                        )

                        for i, title_elem in enumerate(title_elements):
                            try:
                                if not title_elem.is_displayed():
                                    continue

                                text = title_elem.text.strip()
                                if not text or text in seen_chapters:
                                    continue

                                chapter = {"title": text}

                                # Try to get the corresponding page position
                                if i < len(position_elements):
                                    position_elem = position_elements[i]
                                    if position_elem.is_displayed():
                                        page_text = position_elem.text.strip()
                                        if page_text.isdigit():
                                            chapter["page"] = int(page_text)

                                chapters.append(chapter)
                                seen_chapters.add(text)
                                new_chapters_found = True
                                logger.info(f"Added chapter via XPATH: {chapter}")

                            except Exception as e:
                                logger.debug(f"Error processing XPATH chapter element: {e}")
                                continue
                    except Exception as e:
                        logger.warning(f"XPATH fallback also failed: {e}")

                if not new_chapters_found:
                    no_new_chapters_count += 1
                    if no_new_chapters_count >= 3:
                        logger.info("No new chapters found after 3 scrolls, assuming end of list")
                        break
                else:
                    no_new_chapters_count = 0

                # Scroll down to see more chapters
                if scroll_count < max_scrolls - 1:
                    self.driver.swipe(start_x, start_y, start_x, end_y, duration=500)
                    time.sleep(0.3)

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
                        time.sleep(0.5)
                        return True
                except NoSuchElementException:
                    continue

            # If no close button found, try tapping outside or using back
            logger.warning("No close button found, trying back gesture")
            self.driver.back()
            time.sleep(0.5)
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
            time.sleep(0.3)
        except Exception as e:
            logger.error(f"Error hiding reading controls: {e}", exc_info=True)
