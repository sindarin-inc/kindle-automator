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

    def _perform_hook_scroll(
        self,
        center_x: int,
        scroll_start_y: int,
        scroll_end_y: int,
        total_duration_ms: int,
    ):
        """
        Performs a scroll gesture that starts fast and decelerates towards the end
        to achieve precise positioning without inertia.
        Uses W3C Actions with ActionBuilder.
        """
        # Get ActionBuilder from ActionChains
        action_builder = ActionChains(self.driver).w3c_actions

        # Add a new pointer input source of type touch and get the PointerInput object
        # POINTER_TOUCH is 'touch'
        finger = action_builder.add_pointer_input(POINTER_TOUCH, "finger")

        # Sequence of actions for the 'finger'
        # These methods on 'finger' (PointerInput) will add actions to the 'action_builder'

        # 1. Move pointer to start position (instantaneous)
        finger.create_pointer_move(duration=0, x=center_x, y=scroll_start_y)
        # 2. Press down (button=0 is typically the main touch/mouse button)
        finger.create_pointer_down(button=0)
        # 3. Small pause (duration is in seconds for create_pause)
        finger.create_pause(0.01)  # 10ms

        if scroll_start_y == scroll_end_y:
            # If there's no vertical movement, just perform a press for the specified duration
            # The initial 10ms pause is already accounted for.
            # Remaining duration for the press itself.
            press_duration_s = max(0, (total_duration_ms - 10) / 1000.0)
            if press_duration_s > 0:
                finger.create_pause(press_duration_s)
        else:
            # Multi-segment scroll for deceleration using 5 segments
            # Ratios: distance [0.30, 0.25, 0.20, 0.15, 0.10]
            # Ratios: time     [0.10, 0.15, 0.20, 0.25, 0.30]

            # Calculate durations for each segment (ensure they sum to total_duration_ms - 10ms pause)
            effective_total_duration_ms = total_duration_ms - 10  # Account for the initial 10ms pause

            duration1_ms = int(round(effective_total_duration_ms * 0.10))
            duration2_ms = int(round(effective_total_duration_ms * 0.15))
            duration3_ms = int(round(effective_total_duration_ms * 0.20))
            duration4_ms = int(round(effective_total_duration_ms * 0.25))
            # duration5_ms takes the remainder to ensure sum is correct
            duration5_ms = (
                effective_total_duration_ms - duration1_ms - duration2_ms - duration3_ms - duration4_ms
            )

            # Ensure all durations are non-negative
            duration1_ms = max(0, duration1_ms)
            duration2_ms = max(0, duration2_ms)
            duration3_ms = max(0, duration3_ms)
            duration4_ms = max(0, duration4_ms)
            duration5_ms = max(0, duration5_ms)

            delta_y = scroll_end_y - scroll_start_y

            # Calculate target y-coordinates for each segment
            y1_target = scroll_start_y + 0.30 * delta_y
            y2_target = scroll_start_y + (0.30 + 0.25) * delta_y  # Cumulative distance
            y3_target = scroll_start_y + (0.30 + 0.25 + 0.20) * delta_y
            y4_target = scroll_start_y + (0.30 + 0.25 + 0.20 + 0.15) * delta_y
            # y5_target is scroll_end_y

            # Perform the scroll segments
            # Segment 1
            finger.create_pointer_move(duration=duration1_ms, x=center_x, y=int(round(y1_target)))
            # Segment 2
            finger.create_pointer_move(duration=duration2_ms, x=center_x, y=int(round(y2_target)))
            # Segment 3
            finger.create_pointer_move(duration=duration3_ms, x=center_x, y=int(round(y3_target)))
            # Segment 4
            finger.create_pointer_move(duration=duration4_ms, x=center_x, y=int(round(y4_target)))
            # Segment 5
            finger.create_pointer_move(duration=duration5_ms, x=center_x, y=scroll_end_y)

        # Release the pointer
        finger.create_pointer_up(button=0)

        try:
            # Perform all actions defined in the ActionBuilder
            action_builder.perform()
        except Exception as e:
            logger.error(f"Error performing scroll: {e}")
            store_page_source(self.driver, "scroll_error")

    def _log_page_summary(self, page_number, new_titles, total_found):
        """Log a concise summary of books found on current page.

        Args:
            page_number: Current page number
            new_titles: List of new book titles found on this page
            total_found: Total number of unique books found so far
        """
        logger.info(f"Page {page_number}: Found {len(new_titles)} new books, total {total_found}")
        if new_titles:
            separator = "\n\t\t\t"
            joined_titles = f"{separator}".join(new_titles)
            logger.info(f"New titles: {separator}{joined_titles}")

    def _extract_book_info(self, container):
        """Extract book metadata from a container element.

        Args:
            container: Book container element or synthetic wrapper

        Returns:
            dict: Book info with title, author, size, progress fields
        """
        book_info = {"title": None, "progress": None, "size": None, "author": None}

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
                            logger.error(f"Unexpected error finding {field} in title container: {e}")

                except NoSuchElementException:
                    continue
                except StaleElementReferenceException:
                    logger.debug(f"Stale element reference when finding {field}, will retry on next scroll")
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error finding {field}: {e}")
                    continue

        # Extract author from content-desc if still missing
        if not book_info["author"]:
            try:
                content_desc = container.get_attribute("content-desc")
                if content_desc:
                    self._extract_author_from_content_desc(book_info, content_desc)
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
                    logger.info(f"Book partially obscured: '{title_text}' at y={top}-{bottom}")

            except Exception as e:
                logger.debug(f"Error processing container {i}: {e}")
                continue

        # If we found partially visible books, use the first one
        if partially_visible_books:
            first_partial = partially_visible_books[0]
            logger.info(f"Using partially visible book as scroll reference: '{first_partial['title']}'")
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
        """Perform smart scroll to position reference container at 10% from top.

        Args:
            ref_container: Dict with element and position info
            screen_size: Dict with screen dimensions
        """
        start_y = ref_container["top"]
        end_y = screen_size["height"] * 0.1  # 10% from top

        # Verify start point is below end point by a reasonable amount
        if start_y - end_y < 100:
            logger.warning("Scroll distance too small, using default scroll")
            self._default_page_scroll(screen_size["height"] * 0.8, screen_size["height"] * 0.2)
        else:
            logger.info(f"Smart scrolling: moving y={start_y} to y={end_y}")
            self._perform_hook_scroll(
                screen_size["width"] // 2,
                start_y,
                end_y,
                1001,
            )

    def _default_page_scroll(self, start_y, end_y):
        """Wrapper for default page scroll operation.

        Args:
            start_y: Starting Y coordinate
            end_y: Ending Y coordinate
        """
        screen_size = self.driver.get_window_size()
        self._perform_hook_scroll(
            screen_size["width"] // 2,
            start_y,
            end_y,
            1001,
        )

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
                    logger.error(f"Error finding book button by content-desc: {e}")

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
                logger.error(f"Error trying alternative methods to find button: {e}")

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
                logger.error("Failed to exit book selection mode")
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
                self._log_page_summary(
                    page_count, [b["title"] for b in current_double_check_batch], len(books_list)
                )

                # Send additional books via callback if available
                if callback and current_double_check_batch:
                    callback(current_double_check_batch)

                return True
            else:
                logger.info("Double-check confirms no new books, stopping scroll")
                # Send completion notification via callback if available
                if callback:
                    callback(None, done=True, total_books=len(books_list))
                return False
        except Exception as e:
            logger.error(f"Error during double-check for titles: {e}")
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
                logger.error(f"Unexpected error finding button for {book_info['title']}: {e}")
                continue

        return False, None, None

    def _update_collections(self, book_info, seen_titles, books_list, new_books_batch, new_titles_on_page):
        """Update book collections with centralized deduping and batching logic.

        Args:
            book_info: Book info dict to add
            seen_titles: Set of titles already seen
            books_list: Main list of all books
            new_books_batch: Current batch for callback
            new_titles_on_page: List of new titles found on this page

        Returns:
            bool: True if book was newly added, False if already seen
        """
        if book_info["title"] and book_info["title"] not in seen_titles:
            seen_titles.add(book_info["title"])
            books_list.append(book_info)
            new_books_batch.append(book_info)
            new_titles_on_page.append(book_info["title"])
            return True
        else:
            if book_info["title"]:
                logger.info(f"Already seen book ({len(seen_titles)} found): {book_info['title']}")
            return False

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
            # Look specifically for title elements
            title_elements = self.driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title")

            # Convert these title elements to containers
            containers = self._convert_title_elements(title_elements)

            # Also log RecyclerView info for debugging
            try:
                recycler_view = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/recycler_view")
                all_items = recycler_view.find_elements(AppiumBy.XPATH, ".//*")
            except Exception as e:
                logger.error(f"Error getting RecyclerView info: {e}")

        except Exception as e:
            logger.error(f"Error finding direct title elements: {e}")

        # FALLBACK: If we couldn't find titles directly, try the old button approach
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
                logger.error(f"Error processing title '{title.text}': {e}")

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
            "toolbar_top": screen_size["height"]
            * 0.85,  # Books whose bottom is below this are considered obscured
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
        """
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
                            logger.info(f"Skipping partially obscured book: '{potential_title}'")
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
                                book_info, seen_titles, books, new_books_batch, new_titles_on_page
                            )
                            if was_new:
                                books_added_in_current_page_processing = True
                        else:
                            logger.debug(f"Container has no book info, skipping: {book_info}")

                    except StaleElementReferenceException:
                        logger.debug("Stale element reference, skipping container")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing container: {e}")
                        continue

                # Log a summary of this page's findings
                self._log_page_summary(page_count, new_titles_on_page, len(books))

                # Send new books via callback if available
                if callback and new_books_batch:
                    callback(new_books_batch)

                # Decision for the UPCOMING scroll's hook is based on whether THIS page's MAIN pass found anything.
                use_hook_for_current_scroll = books_added_in_current_page_processing

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
                        break  # No new books found, stop scrolling

                # At this point, if nothing new was found after our double-check, or if we're seeing exactly the same books, stop
                if not any_new_books_this_iteration or seen_titles == previous_titles:
                    logger.info("No progress in finding new books, stopping scroll")
                    # Send completion notification via callback if available
                    if callback:
                        callback(None, done=True, total_books=len(books))
                    break

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
                return self._final_result_handling(
                    target_title, books, seen_titles, title_match_func, callback
                )

            return books

        except Exception as e:
            logger.error(f"Error scrolling through library: {e}")

            # Send error via callback if available
            if callback:
                callback(None, error=str(e))

            if target_title:
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
            logger.error(f"Error exiting book selection mode: {e}")
            return False

    def scroll_to_list_top(self):
        """Scroll to the top of the All list by toggling between Downloaded and All."""
        try:
            # First check if we're in book selection mode and exit if needed
            if self.is_in_book_selection_mode():
                logger.info("In book selection mode, exiting before scrolling")
                if not self.exit_book_selection_mode():
                    logger.error("Failed to exit book selection mode, cannot scroll properly")
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
                logger.error("Could not find Downloaded or All toggle buttons")
                return False

        except Exception as e:
            logger.error(f"Error scrolling to top of list: {e}")
            return False
