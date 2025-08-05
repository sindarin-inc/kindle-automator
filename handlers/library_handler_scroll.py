import logging
import math
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple, Union

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.interaction import POINTER_TOUCH
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from server.logging_config import store_page_source
from server.utils.ansi_colors import BRIGHT_CYAN, BRIGHT_GREEN, BRIGHT_YELLOW, RESET
from views.common.scroll_strategies import SmartScroller
from views.library.view_strategies import (
    BOOK_CONTAINER_RELATIONSHIPS,
    BOOK_METADATA_IDENTIFIERS,
    CONTENT_DESC_STRATEGIES,
)

logger = logging.getLogger(__name__)


class LibraryHandlerScroll:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        # Initialize the smart scroller
        self.scroller = SmartScroller(driver)
        # Store partial matches for later retrieval
        self.partial_matches = []

    def _log_page_summary(self, page_number, new_books, total_found):
        """Log a concise summary of books found on current page.

        Args:
            page_number: Current page number
            new_books: List of new book info dicts or titles found on this page
            total_found: Total number of unique books found so far
        """
        # Get the filter book count and user email from the database if available
        filter_book_count = None
        user_email = None
        try:
            profile_manager = self.driver.automator.profile_manager
            filter_book_count = profile_manager.get_style_setting("filter_book_count")
            user_email = profile_manager.sindarin_email
        except Exception:
            pass  # Silently ignore if we can't get the filter count or email

        # Build the page info string with colors
        user_prefix = f"{BRIGHT_CYAN}[{user_email}]{RESET} " if user_email else ""
        if filter_book_count:
            expected_pages = math.ceil(filter_book_count / 10)  # Assuming ~10 books per page
            page_info = f"{user_prefix}{BRIGHT_YELLOW}Page {page_number}/{expected_pages}:{RESET} Found {BRIGHT_GREEN}{len(new_books)}{RESET} new books, total {BRIGHT_GREEN}{total_found}/{filter_book_count}{RESET}"
        else:
            page_info = f"{user_prefix}{BRIGHT_YELLOW}Page {page_number}:{RESET} Found {BRIGHT_GREEN}{len(new_books)}{RESET} new books, total {BRIGHT_GREEN}{total_found}{RESET}"

        if new_books:
            separator = "\n\t\t\t"
            # Handle both book info dicts and plain title strings
            book_entries = []
            for book in new_books:
                if isinstance(book, dict):
                    title = book.get("title", "Unknown")
                    author = book.get("author")
                    if author:
                        book_entries.append(f"{title} / {author}")
                    else:
                        book_entries.append(title)
                else:
                    # Fallback for plain string titles
                    book_entries.append(str(book))
            joined_entries = f"{separator}".join(book_entries)
            logger.info(f"{page_info}:{separator}{joined_entries}")
        else:
            logger.info(page_info)

    def _extract_book_info(self, container):
        """Extract book metadata from a container element.

        Args:
            container: Book container element or synthetic wrapper

        Returns:
            dict: Book info with title, author, size, progress fields
        """
        book_info = {"title": None, "progress": None, "size": None, "author": None}

        # Store page source once per session for debugging author extraction
        if not hasattr(self, "_debug_page_source_stored"):
            self._debug_page_source_stored = True
            logger.info("Storing page source for author extraction debugging")
            store_page_source(self.driver.page_source, "author_extraction_debug")

        # Handle synthetic wrappers
        if isinstance(container, dict) and container.get("is_synthetic"):
            book_info["title"] = container["title_text"]

            # Try to extract author from content-desc
            try:
                escaped_text = book_info["title"].replace("'", "\\'")
                buttons = self.driver.find_elements(
                    AppiumBy.XPATH,
                    f"//android.widget.Button[@content-desc='{escaped_text}']",
                )
                if buttons:
                    button = buttons[0]
                    content_desc = button.get_attribute("content-desc")

                    if content_desc:
                        self._extract_author_from_content_desc(book_info, content_desc)
            except Exception:
                pass

            return book_info

        # Extract metadata using strategies for regular containers
        for field in ["title", "progress", "size", "author"]:
            for strategy_index, (strategy, locator) in enumerate(BOOK_METADATA_IDENTIFIERS[field]):
                try:
                    relative_locator = f".{locator}" if strategy == AppiumBy.XPATH else locator
                    elements = container.find_elements(strategy, relative_locator)

                    if elements:
                        book_info[field] = elements[0].text
                        break
                    else:
                        # Try finding within title container
                        try:
                            title_container_strategy, title_container_locator = BOOK_CONTAINER_RELATIONSHIPS[
                                "title_container"
                            ]
                            title_container = container.find_element(
                                title_container_strategy, title_container_locator
                            )
                            elements = title_container.find_elements(strategy, relative_locator)
                            if elements:
                                book_info[field] = elements[0].text
                                break
                        except NoSuchElementException:
                            pass
                        except Exception as e:
                            logger.error(
                                f"Unexpected error finding {field} in title container: {e}", exc_info=True
                            )

                except NoSuchElementException:
                    continue
                except StaleElementReferenceException:
                    logger.debug(f"Stale element reference when finding {field}, will retry on next scroll")
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error finding {field}: {e}", exc_info=True)
                    continue

        # Extract author from content-desc if still missing
        if not book_info["author"]:
            try:
                content_desc = container.get_attribute("content-desc")
                if content_desc:
                    self._extract_author_from_content_desc(book_info, content_desc)
                else:
                    logger.debug("No content-desc attribute found")
            except StaleElementReferenceException:
                logger.debug("Stale element reference when getting content-desc, skipping")
            except Exception as e:
                logger.debug(f"Error getting content-desc: {e}")

        return book_info

    def _find_scroll_reference(self, containers, screen_size):
        """Find which element should anchor the next smart scroll.

        Args:
            containers: List of book container elements
            screen_size: Dict with screen dimensions

        Returns:
            dict: Reference container info (element, top, title) or None
        """
        if not containers or len(containers) < 2:
            return None

        # Find books that are partially visible due to the bottom toolbar
        toolbar_top = screen_size["height"] * 0.85
        partially_visible_books = []

        for i, container in enumerate(containers):
            try:
                title_text = container.text
                loc = container.location
                s = container.size
                top = loc["y"]
                bottom = top + s["height"]

                # Check if book is partially obscured by the toolbar
                if bottom > toolbar_top:
                    partially_visible_books.append(
                        {"element": container, "title": title_text, "top": top, "bottom": bottom}
                    )

            except Exception as e:
                logger.debug(f"Error processing container {i}: {e}")
                continue

        # If we found partially visible books, use the first one
        if partially_visible_books:
            first_partial = partially_visible_books[0]
            # logger.info(f"Using partially visible book as scroll reference: '{first_partial['title']}'")
            return first_partial

        # Fall back to last fully visible book
        for i in range(len(containers) - 1, -1, -1):
            try:
                container = containers[i]
                loc = container.location
                s = container.size
                bottom = loc["y"] + s["height"]

                if bottom <= toolbar_top:
                    return {"element": container, "top": loc["y"], "title": container.text}
            except Exception:
                continue

        # Default to last container
        if containers:
            try:
                last = containers[-1]
                return {"element": last, "top": last.location["y"], "title": last.text}
            except Exception:
                pass

        return None

    def _perform_smart_scroll(self, ref_container, screen_size):
        """Perform smart scroll to position reference container properly.

        Args:
            ref_container: Dict with element and position info
            screen_size: Dict with screen dimensions
        """
        # Determine target position based on whether this is a partially visible book
        # For partially visible books at bottom, scroll them to just below the top toolbar
        # The top toolbar appears to end around 20% of screen height based on the logs
        if "bottom" in ref_container and ref_container["bottom"] > screen_size["height"] * 0.85:
            # This is a partially visible book at the bottom
            # Position it at 22% from top to ensure it's fully visible below the toolbar
            target_position = 0.22
        else:
            # For other books, use a safer 20% position to avoid cutting off at top
            target_position = 0.20

        # Use the common SmartScroller to scroll the reference container to target position
        self.scroller.scroll_to_position(ref_container["element"], target_position)

    def _default_page_scroll(self, start_y, end_y):
        """Wrapper for default page scroll operation.

        Args:
            start_y: Starting Y coordinate
            end_y: Ending Y coordinate
        """
        # Use the common SmartScroller for default page scroll
        self.scroller.scroll_down()

    def _final_result_handling(self, target_title, books, seen_titles, title_match_func, callback):
        """Handle final result logic for target title searches.

        Args:
            target_title: Target title that was searched for
            books: List of all found books
            seen_titles: Set of all seen titles
            title_match_func: Function to check title matches
            callback: Callback function for notifications

        Returns:
            tuple: (parent_container, button, book_info) if found, or (None, None, None)
        """
        # Check if this book was found but we couldn't grab the container
        found_matching_title = False
        matched_book = None

        for book in books:
            if book.get("title") and title_match_func(book["title"], target_title):
                found_matching_title = True
                matched_book = book
                logger.info(f"Book title matched using title_match: '{book['title']}' -> '{target_title}'")

                try:
                    # Try to find the book button directly by content-desc
                    escaped_title = book["title"].replace("'", "\\'")
                    buttons = self.driver.find_elements(
                        AppiumBy.XPATH,
                        f"//android.widget.Button[@content-desc='{escaped_title}']",
                    )
                    if buttons:
                        logger.info(f"Found {len(buttons)} buttons matching first word of title")
                        parent_container = buttons[0]
                        return parent_container, buttons[0], book
                except StaleElementReferenceException:
                    logger.debug(f"Stale element reference when finding book button for '{book['title']}'")
                except Exception as e:
                    logger.error(f"Error finding book button by content-desc: {e}", exc_info=True)

        # Try alternative approaches if we found a match but couldn't get the button
        if found_matching_title and matched_book:
            logger.info("Found matching title but couldn't find button by content-desc, trying alternatives")
            try:
                title_text = matched_book["title"]
                # Try by exact title
                escaped_title = title_text.replace("'", "\\'")
                xpath = f"//android.widget.Button[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text='{escaped_title}']]"
                buttons = self.driver.find_elements(AppiumBy.XPATH, xpath)
                if buttons:
                    logger.info("Found button via title contains match")
                    return buttons[0], buttons[0], matched_book

                # Try with just the first word
                first_word = title_text.split()[0]
                if len(first_word) >= 3:
                    xpath = f"//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text='{title_text}']"
                    title_elements = self.driver.find_elements(AppiumBy.XPATH, xpath)
                    if title_elements:
                        logger.info(f"Found title element with first word '{first_word}'")
                        parent = title_elements[0].find_element(AppiumBy.XPATH, "./../../..")
                        return parent, title_elements[0], matched_book
            except Exception as e:
                logger.error(f"Error trying alternative methods to find button: {e}", exc_info=True)

        if not found_matching_title:
            logger.warning(f"Book not found after searching entire library: {target_title}")
            logger.info(f"Available titles: {', '.join(seen_titles)}")

            # Send error via callback if available
            if callback:
                callback(None, error=f"Book not found: {target_title}")

        return None, None, None

    def _maybe_exit_selection_mode(self):
        """Check and exit book selection mode if active.

        Returns:
            bool: True if was in selection mode and exited, False otherwise
        """
        if self.is_in_book_selection_mode():
            logger.warning("Detected book selection mode during scrolling")
            if self.exit_book_selection_mode():
                logger.info("Successfully exited book selection mode")
                return True
            else:
                logger.error("Failed to exit book selection mode", exc_info=True)
                return True  # Return True to indicate mode was detected
        return False

    def _double_check_titles(self, seen_titles, books_list, page_count, new_titles_on_page, callback):
        """Second-pass scan for any titles still missing after normal processing.

        Args:
            seen_titles: Set of already seen titles
            books_list: Main list of all books
            page_count: Current page number
            new_titles_on_page: List of new titles found on this page
            callback: Callback function for new books

        Returns:
            bool: True if new titles were found, False otherwise
        """
        try:
            title_elements = self.driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title")
            current_screen_titles = [el.text for el in title_elements]

            # If all these titles are already seen, then we can safely stop
            new_unseen_titles = [t for t in current_screen_titles if t and t not in seen_titles]
            if new_unseen_titles:
                logger.info(f"Double-check found {len(new_unseen_titles)} additional unseen titles")

                # Add these titles to our seen set and create simple book entries for them
                current_double_check_batch = []
                for new_title in new_unseen_titles:
                    seen_titles.add(new_title)
                    book_info = {
                        "title": new_title,
                        "progress": None,
                        "size": None,
                        "author": None,
                    }
                    books_list.append(book_info)
                    current_double_check_batch.append(book_info)
                    new_titles_on_page.append(new_title)

                # Log summary for double-check findings
                self._log_page_summary(page_count, current_double_check_batch, len(books_list))

                # Send additional books via callback if available
                if callback and current_double_check_batch:
                    callback(current_double_check_batch)

                return True
            else:
                logger.info("Double-check confirms no new books, stopping scroll")
                # Send completion notification via callback if available
                if callback:
                    callback(None, done=True, total_books=len(books_list))

                # Save scroll book count to database
                try:
                    from server.utils.request_utils import get_sindarin_email

                    sindarin_email = get_sindarin_email()
                    if sindarin_email:
                        self.driver.automator.profile_manager.save_style_setting(
                            "scroll_book_count", len(books_list)
                        )
                        logger.info(f"Saved scroll book count to database: {len(books_list)}")
                except Exception as e:
                    logger.error(f"Error saving scroll book count: {e}", exc_info=True)

                return False
        except Exception as e:
            logger.error(f"Error during double-check for titles: {e}", exc_info=True)
            return False

    def _try_match_target(self, book_info, container, target_title, title_match_func):
        """Try to match current book against target title.

        Args:
            book_info: Book info dict
            container: Book container element or synthetic wrapper dict
            target_title: Target title to match
            title_match_func: Function to check if titles match

        Returns:
            tuple: (matched: bool, parent_container, button) or (False, None, None)
        """
        if not book_info["title"] or not title_match_func(book_info["title"], target_title):
            return False, None, None

        # Handle synthetic wrappers
        if isinstance(container, dict) and container.get("is_synthetic"):
            # For synthetic wrappers, we already know there's a match
            # Try to find the actual button element
            try:
                escaped_title = book_info["title"].replace("'", "\\'")
                buttons = self.driver.find_elements(
                    AppiumBy.XPATH,
                    f"//android.widget.Button[@content-desc='{escaped_title}']",
                )
                if buttons:
                    button = buttons[0]
                    return True, button, button
                else:
                    # Use the element from the wrapper as fallback
                    element = container.get("element")
                    if element:
                        return True, element, element
            except Exception as e:
                logger.debug(f"Error finding button for synthetic wrapper: {e}")
                return False, None, None

        # Find the button and parent container for regular containers
        for strategy, locator in BOOK_METADATA_IDENTIFIERS["title"]:
            try:
                button = container.find_element(strategy, locator)
                logger.info(
                    f"Found button: {button.get_attribute('content-desc')} looking for parent container"
                )

                # Try to find the parent RelativeLayout using XPath
                try:
                    parent_strategy, parent_locator_template = BOOK_CONTAINER_RELATIONSHIPS["parent_by_title"]
                    escaped_title = book_info["title"].replace("'", "\\'")
                    parent_locator = parent_locator_template.format(title=escaped_title)
                    parent_container = container.find_element(parent_strategy, parent_locator)
                except NoSuchElementException:
                    # If that fails, try finding any ancestor RelativeLayout
                    try:
                        ancestor_strategy, ancestor_locator_template = BOOK_CONTAINER_RELATIONSHIPS[
                            "ancestor_by_title"
                        ]
                        escaped_title = book_info["title"].replace("'", "\\'")
                        ancestor_locator = ancestor_locator_template.format(title=escaped_title)
                        parent_container = container.find_element(ancestor_strategy, ancestor_locator)
                    except NoSuchElementException:
                        logger.debug(f"Could not find parent container for {book_info['title']}")
                        continue

                # Double-check titles match
                if title_match_func(book_info["title"], target_title):
                    logger.info(f"Found match for '{target_title}'")
                    return True, parent_container, button
                else:
                    continue

            except NoSuchElementException:
                logger.debug(f"Could not find button for {book_info['title']}")
                continue
            except StaleElementReferenceException:
                logger.debug(f"Stale element reference when finding button for {book_info['title']}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error finding button for {book_info['title']}: {e}", exc_info=True)
                continue

        return False, None, None

    def _update_collections(
        self, book_info, seen_titles, books_list, new_books_batch, new_titles_on_page, target_title=None
    ):
        """Update book collections with centralized deduping and batching logic.

        Args:
            book_info: Book info dict to add
            seen_titles: Set of titles already seen
            books_list: Main list of all books
            new_books_batch: Current batch for callback
            new_titles_on_page: List of new titles found on this page
            target_title: Optional target title we're searching for (for partial match collection)

        Returns:
            bool: True if book was newly added, False if already seen
        """
        if book_info["title"] and book_info["title"] not in seen_titles:
            seen_titles.add(book_info["title"])
            books_list.append(book_info)
            new_books_batch.append(book_info)
            new_titles_on_page.append(book_info["title"])

            # If we're searching for a target title, check for partial matches
            if target_title:
                title = book_info["title"]
                # Check if target title is part of this book's title or vice versa
                if target_title.lower() in title.lower() or title.lower() in target_title.lower():
                    # Store this as a partial match
                    self.partial_matches.append((None, None, book_info))
                    logger.info(f"Stored partial match: '{title}' for target '{target_title}'")

            return True
        else:
            if book_info["title"]:
                logger.info(f"Already seen book ({len(seen_titles)} found): {book_info['title'][:15]}...")
            return False

    def get_partial_matches(self):
        """Get any partial matches collected during scrolling.

        Returns:
            list: List of tuples (parent_container, button, book_info) representing partial matches
        """
        return self.partial_matches

    def _extract_author_from_content_desc(self, book_info, content_desc):
        """Extract author information from content description attribute.

        Args:
            book_info: Book info dict to update
            content_desc: Content description string
        """
        for pattern in CONTENT_DESC_STRATEGIES["patterns"]:
            try:
                parts = content_desc.split(pattern["split_by"])

                if "skip_if_contains" in pattern and any(
                    skip_term in content_desc for skip_term in pattern["skip_if_contains"]
                ):
                    continue

                if len(parts) > abs(pattern["author_index"]):
                    potential_author = parts[pattern["author_index"]]

                    if "process" in pattern:
                        potential_author = pattern["process"](potential_author)

                    for rule in CONTENT_DESC_STRATEGIES["cleanup_rules"]:
                        potential_author = re.sub(
                            rule["pattern"],
                            rule["replace"],
                            potential_author,
                        )

                    non_author_terms = CONTENT_DESC_STRATEGIES["non_author_terms"]
                    if not any(non_author in potential_author.lower() for non_author in non_author_terms):
                        potential_author = potential_author.strip()
                        if potential_author:
                            book_info["author"] = potential_author
                            break
            except Exception:
                continue

    def _is_partially_obscured(self, element, toolbar_top):
        """Check if an element is partially obscured by the bottom toolbar.

        Args:
            element: WebElement or dict with element property
            toolbar_top: Y-coordinate where the toolbar begins

        Returns:
            bool: True if element is partially obscured, False otherwise
        """
        try:
            # Determine the actual element for geometry checks
            element_for_geometry = None

            if isinstance(element, dict) and element.get("is_synthetic"):
                element_for_geometry = element.get("element")
            elif hasattr(element, "location") and hasattr(element, "size"):
                element_for_geometry = element

            if element_for_geometry:
                try:
                    loc = element_for_geometry.location
                    s = element_for_geometry.size
                    container_bottom = loc["y"] + s["height"]

                    if container_bottom > toolbar_top:
                        return True
                except (NoSuchElementException, StaleElementReferenceException):
                    logger.debug("Could not get geometry to check if obscured, processing.")
                except AttributeError:
                    logger.debug("Element missing geometry attributes (location/size), processing.")
                except Exception as e:
                    logger.warning(f"Error checking if element is obscured: {e}, processing.")

        except Exception as e:
            logger.warning(f"Error in obscured check: {e}")

        return False

    def _collect_visible_containers(self):
        """Gather all candidate book containers on the current viewport.

        Returns:
            list: Container objects (buttons, elements, or synthetic wrappers)
        """
        containers = []

        try:
            # Find ALL direct children of RecyclerView that have content-desc (both Button and RelativeLayout)
            # This handles mixed layouts where some books are buttons and some are relative layouts
            book_containers = self.driver.find_elements(
                AppiumBy.XPATH,
                "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']/*[@content-desc]",
            )

            logger.info(f"Found {len(book_containers)} book containers with content-desc")
            if book_containers:
                containers = book_containers
            else:
                # Look specifically for title elements as fallback
                title_elements = self.driver.find_elements(
                    AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                )
                logger.info(f"Found {len(title_elements)} title elements as fallback")

                # Convert these title elements to containers
                containers = self._convert_title_elements(title_elements)

        except Exception as e:
            logger.error(f"Error finding book containers: {e}", exc_info=True)

        # FALLBACK: If we couldn't find containers, try the old approach
        if not containers:
            containers = self._fallback_container_discovery()

        return containers

    def _fallback_container_discovery(self):
        """Execute the old button/other locator strategy when primary title search fails.

        Returns:
            list: Found containers or empty list
        """
        containers = []
        logger.info("No title elements found directly, falling back to button approach")

        try:
            # Use the container strategy from BOOK_METADATA_IDENTIFIERS
            container_strategy, container_locator = BOOK_METADATA_IDENTIFIERS["container"][0]
            book_buttons = self.driver.find_elements(container_strategy, container_locator)
            logger.info(f"Fallback found {len(book_buttons)} book buttons")
            containers = book_buttons
        except Exception as e:
            logger.debug(f"Failed to find book buttons: {e}")

            # Last resort: try the old container approach
            for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"][1:]:
                try:
                    found_containers = self.driver.find_elements(container_strategy, container_locator)
                    if found_containers:
                        containers = found_containers
                        logger.debug(f"Last resort found {len(containers)} book containers")
                        break
                except Exception as e:
                    logger.debug(f"Failed to find containers with {container_strategy}: {e}")
                    continue

        return containers

    def _convert_title_elements(self, title_elements):
        """Convert title elements to synthetic container wrappers.

        Args:
            title_elements: List of WebElement objects representing titles

        Returns:
            list: Container objects (either actual buttons or synthetic wrappers)
        """
        containers = []

        for i, title in enumerate(title_elements):
            try:
                # Safely get the title text to handle potential stale elements
                try:
                    title_text = title.text
                except StaleElementReferenceException:
                    logger.debug(f"Stale element reference when getting title text for element {i}, skipping")
                    continue

                # Create a book "wrapper" for each title element
                book_wrapper = {"element": title, "title_text": title_text, "is_synthetic": True}

                # Now try to find the actual container through a direct query
                try:
                    # Try to find button containing this title text
                    escaped_text = title.text.replace("'", "\\'")
                    button = self.driver.find_element(
                        AppiumBy.XPATH,
                        f"//android.widget.Button[@content-desc='{escaped_text}']",
                    )
                    # If found, use the actual button
                    containers.append(button)
                    # Use debug level instead of info for container details
                except StaleElementReferenceException:
                    logger.debug(
                        f"Stale element reference when finding button for '{escaped_text}', skipping"
                    )
                    # Use our synthetic wrapper as fallback
                    containers.append(book_wrapper)
                except Exception:
                    # If can't find actual container, use our synthetic wrapper
                    containers.append(book_wrapper)
            except Exception as e:
                logger.error(f"Error processing title '{title.text}': {e}", exc_info=True)

        return containers

    def _get_screen_metrics(self):
        """Return screen metrics for scrolling calculations.

        Returns:
            dict: Contains screen_size, start_y, end_y, and toolbar_top
        """
        screen_size = self.driver.get_window_size()
        return {
            "screen_size": screen_size,
            "start_y": screen_size["height"] * 0.8,
            "end_y": screen_size["height"] * 0.2,
            "toolbar_top": (
                screen_size["height"] * 0.85
            ),  # Books whose bottom is below this are considered obscured
        }

    def _scroll_through_library(self, target_title: str = None, title_match_func=None, callback=None):
        """Scroll through library collecting book info, optionally looking for a specific title.

        Args:
            target_title: Optional title to search for. If provided, returns early when found.
            title_match_func: Function to check if titles match
            callback: Optional callback function to receive books as they're found.
                     The callback should accept a list of book dictionaries.

        Returns:
            If target_title provided: (found_container, found_button, book_info) or (None, None, None)
            If no target_title: List of book info dictionaries
            If callback provided: List may still be returned, but books are also sent to callback as found

        Note:
            When searching with target_title, partial matches will be collected and stored
            in the self.partial_matches list. These can be retrieved after the search if no
            exact match is found.
        """
        # Clear partial matches at the start of each search
        self.partial_matches = []
        try:
            # Get screen metrics
            metrics = self._get_screen_metrics()
            screen_size = metrics["screen_size"]
            start_y = metrics["start_y"]
            end_y = metrics["end_y"]
            toolbar_top = metrics["toolbar_top"]

            # Initialize tracking variables
            books = []
            seen_titles = set()
            # No normalization needed for exact matching
            page_count = 0
            use_hook_for_current_scroll = True
            consecutive_identical_screen_iterations = 0
            IDENTICAL_SCREEN_THRESHOLD = 10

            while True:
                page_count += 1

                # Collect all visible containers
                containers = self._collect_visible_containers()

                # Store titles from previous scroll position
                previous_titles = set(seen_titles)
                books_added_in_current_page_processing = False
                new_titles_on_page = []
                new_books_batch = []

                # Process each container
                for container in containers:
                    try:
                        # Check if container is partially obscured
                        if self._is_partially_obscured(container, toolbar_top):
                            potential_title = "Unknown"
                            try:
                                if isinstance(container, dict) and container.get("is_synthetic"):
                                    potential_title = container.get("title_text", potential_title)
                                elif hasattr(container, "text"):
                                    potential_title = container.text
                            except Exception:
                                pass
                            continue

                        # Extract book info
                        book_info = self._extract_book_info(container)

                        if book_info["title"]:
                            # Check for target title match if searching
                            if target_title:
                                matched, parent_container, button = self._try_match_target(
                                    book_info, container, target_title, title_match_func
                                )
                                if matched:
                                    return parent_container, button, book_info

                            # Update collections
                            was_new = self._update_collections(
                                book_info,
                                seen_titles,
                                books,
                                new_books_batch,
                                new_titles_on_page,
                                target_title,
                            )
                            if was_new:
                                books_added_in_current_page_processing = True

                    except StaleElementReferenceException:
                        logger.debug("Stale element reference, skipping container")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing container: {e}", exc_info=True)
                        continue

                # Log a summary of this page's findings
                self._log_page_summary(page_count, new_books_batch, len(books))

                # Send new books via callback if available
                if callback and new_books_batch:
                    callback(new_books_batch)

                # Decision for the UPCOMING scroll's hook is based on whether THIS page's MAIN pass found anything.
                use_hook_for_current_scroll = books_added_in_current_page_processing

                # Check if all titles processed on this page are identical
                if new_titles_on_page and len(new_titles_on_page) > 1 and len(set(new_titles_on_page)) == 1:
                    consecutive_identical_screen_iterations += 1
                    logger.info(
                        f"All {len(new_titles_on_page)} titles on page are identical: '{new_titles_on_page[0]}' "
                        f"(iteration {consecutive_identical_screen_iterations}/{IDENTICAL_SCREEN_THRESHOLD})"
                    )
                else:
                    consecutive_identical_screen_iterations = 0

                # If we've found no new books on this screen (via main processing), we need to double-check
                # Also, determine if any new books overall were found in this iteration (main pass + double_check)
                any_new_books_this_iteration = books_added_in_current_page_processing

                if not books_added_in_current_page_processing:  # If main pass found nothing new
                    found_new_titles = self._double_check_titles(
                        seen_titles, books, page_count, new_titles_on_page, callback
                    )
                    if found_new_titles:
                        any_new_books_this_iteration = True
                    else:
                        if consecutive_identical_screen_iterations < IDENTICAL_SCREEN_THRESHOLD:
                            break  # No new books found, stop scrolling
                        else:
                            logger.info(
                                f"All titles identical but haven't reached threshold ({consecutive_identical_screen_iterations}/{IDENTICAL_SCREEN_THRESHOLD}), continuing scroll"
                            )

                # At this point, if nothing new was found after our double-check, or if we're seeing exactly the same books, stop
                if not any_new_books_this_iteration or seen_titles == previous_titles:
                    if consecutive_identical_screen_iterations < IDENTICAL_SCREEN_THRESHOLD:
                        logger.info("No progress in finding new books, stopping scroll")
                        # Send completion notification via callback if available
                        if callback:
                            callback(None, done=True, total_books=len(books))

                        # Save scroll book count to database
                        try:
                            from server.utils.request_utils import get_sindarin_email

                            sindarin_email = get_sindarin_email()
                            if sindarin_email:
                                self.driver.automator.profile_manager.save_style_setting(
                                    "scroll_book_count", len(books)
                                )
                                logger.info(f"Saved scroll book count to database: {len(books)}")
                        except Exception as e:
                            logger.error(f"Error saving scroll book count: {e}", exc_info=True)

                        break
                    else:
                        logger.info(
                            f"No progress but all titles identical ({consecutive_identical_screen_iterations}/{IDENTICAL_SCREEN_THRESHOLD}), continuing scroll"
                        )

                # Find scroll reference and perform scrolling
                book_containers = self.driver.find_elements(
                    AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                )

                ref_container = self._find_scroll_reference(book_containers, screen_size)
                if ref_container:
                    self._perform_smart_scroll(ref_container, screen_size)
                else:
                    self._default_page_scroll(start_y, end_y)

                # Check for and handle selection mode after scroll
                self._maybe_exit_selection_mode()

            logger.info(f"Found total of {len(books)} unique books")

            # Handle final results for target title searches
            if target_title:
                result = self._final_result_handling(
                    target_title, books, seen_titles, title_match_func, callback
                )
                # If no exact match found, we might have partial matches stored
                if result[0] is None and self.partial_matches:
                    logger.info(
                        f"No exact match for '{target_title}', but {len(self.partial_matches)} partial matches found"
                    )
                return result

            return books

        except Exception as e:
            # Import and check if this is an Appium error
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise

            logger.error(f"Error scrolling through library: {e}", exc_info=True)

            # Send error via callback if available
            if callback:
                callback(None, error=str(e))

            if target_title:
                # Log any partial matches we might have found before the error
                if self.partial_matches:
                    logger.info(f"Found {len(self.partial_matches)} partial matches before error")
                return None, None, None
            return []

    def is_in_book_selection_mode(self):
        """Check if we're in book selection mode (when a book title is long-clicked).

        In this mode, a "DONE" button appears in the top left corner of the screen.

        Returns:
            bool: True if in selection mode, False otherwise
        """
        try:
            # Check for the "DONE" button that appears when a book is selected
            done_button = self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/action_mode_close_button"
            )
            if done_button.is_displayed() and done_button.text == "DONE":
                logger.info("Detected book selection mode with DONE button visible")
                return True
            return False
        except NoSuchElementException:
            return False
        except Exception as e:
            logger.debug(f"Error checking book selection mode: {e}")
            return False

    def exit_book_selection_mode(self):
        """Exit book selection mode by clicking the DONE button.

        Returns:
            bool: True if successfully exited selection mode, False otherwise
        """
        try:
            if not self.is_in_book_selection_mode():
                logger.debug("Not in book selection mode, nothing to exit")
                return True

            # Find and click the DONE button
            done_button = self.driver.find_element(
                AppiumBy.ID, "com.amazon.kindle:id/action_mode_close_button"
            )
            done_button.click()
            logger.info("Clicked DONE button to exit book selection mode")

            # Wait a moment for selection mode to exit
            time.sleep(0.5)

            # Verify we're no longer in selection mode
            if not self.is_in_book_selection_mode():
                logger.info("Successfully exited book selection mode")
                return True
            else:
                logger.warning("Still in book selection mode after clicking DONE")
                return False
        except Exception as e:
            logger.error(f"Error exiting book selection mode: {e}", exc_info=True)
            return False

    def scroll_to_list_top(self):
        """Scroll to the top of the All list by toggling between Downloaded and All."""
        try:
            # First check if we're in book selection mode and exit if needed
            if self.is_in_book_selection_mode():
                logger.info("In book selection mode, exiting before scrolling")
                if not self.exit_book_selection_mode():
                    logger.error("Failed to exit book selection mode, cannot scroll properly", exc_info=True)
                    return False
                logger.info("Successfully exited book selection mode, continuing with scroll")

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
                logger.error("Could not find Downloaded or All toggle buttons", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"Error scrolling to top of list: {e}", exc_info=True)
            return False
