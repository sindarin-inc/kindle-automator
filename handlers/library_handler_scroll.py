import logging
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

    def _log_page_summary(self, page_number, new_titles, total_found):
        """Log a concise summary of books found on current page.

        Args:
            page_number: Current page number
            new_titles: List of new book titles found on this page
            total_found: Total number of unique books found so far
        """
        logger.info(f"Page {page_number}: Found {len(new_titles)} new books, total {total_found}")
        if new_titles:
            titles_str = ", ".join(new_titles[:5])
            if len(new_titles) > 5:
                titles_str += f" and {len(new_titles) - 5} more"
            logger.info(f"New titles: {titles_str}")

    def _scroll_through_library(self, target_title: str = None, title_match_func=None):
        """Scroll through library collecting book info, optionally looking for a specific title.

        Args:
            target_title: Optional title to search for. If provided, returns early when found.
            title_match_func: Function to check if titles match

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
            page_count = 0

            while True:
                page_count += 1
                # Log page source for debugging
                filepath = store_page_source(self.driver.page_source, "library_view")

                # Find all book containers on current screen
                # PRIMARY APPROACH: First directly find all title elements
                containers = []
                try:
                    # Look specifically for title elements
                    title_elements = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                    )

                    # Convert these title elements to containers without detailed logging
                    for i, title in enumerate(title_elements):
                        try:
                            # Create a book "wrapper" for each title element
                            book_wrapper = {"element": title, "title_text": title.text, "is_synthetic": True}

                            # Now try to find the actual container through a direct query
                            try:
                                # Try to find button containing this title text
                                escaped_text = title.text.replace("'", "\\'")
                                button = self.driver.find_element(
                                    AppiumBy.XPATH,
                                    f"//android.widget.Button[contains(@content-desc, '{escaped_text}')]",
                                )
                                # If found, use the actual button
                                containers.append(button)
                                # Use debug level instead of info for container details
                            except Exception:
                                # If can't find actual container, use our synthetic wrapper
                                containers.append(book_wrapper)
                        except Exception as e:
                            logger.error(f"Error processing title '{title.text}': {e}")

                    # Also log RecyclerView info for debugging
                    try:
                        recycler_view = self.driver.find_element(
                            AppiumBy.ID, "com.amazon.kindle:id/recycler_view"
                        )
                        all_items = recycler_view.find_elements(AppiumBy.XPATH, ".//*")
                    except Exception as e:
                        logger.error(f"Error getting RecyclerView info: {e}")

                except Exception as e:
                    logger.error(f"Error finding direct title elements: {e}")

                # FALLBACK APPROACH: If we couldn't find titles directly, try the old button approach
                if not containers:
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
                        for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"][
                            1:
                        ]:
                            try:
                                found_containers = self.driver.find_elements(
                                    container_strategy, container_locator
                                )
                                if found_containers:
                                    containers = found_containers
                                    logger.debug(f"Last resort found {len(containers)} book containers")
                                    break
                            except Exception as e:
                                logger.debug(f"Failed to find containers with {container_strategy}: {e}")
                                continue

                # Store titles from previous scroll position
                previous_titles = set(seen_titles)
                new_books_found = False
                new_titles_on_page = []  # Track titles found on this page

                # Process each container
                for container in containers:
                    try:
                        book_info = {"title": None, "progress": None, "size": None, "author": None}

                        # Log container attributes for debugging
                        try:
                            # Handle both regular containers and our synthetic wrappers
                            if (
                                isinstance(container, dict)
                                and "is_synthetic" in container
                                and container["is_synthetic"]
                            ):
                                # This is a synthetic wrapper - we only have the title
                                # Pre-fill the book title since we already know it
                                book_info["title"] = container["title_text"]

                                # Add the book directly to books list if not already there
                                if book_info["title"] not in seen_titles:
                                    seen_titles.add(book_info["title"])
                                    books.append(book_info)
                                    new_books_found = True
                                    new_titles_on_page.append(book_info["title"])

                                # Set a flag to skip the rest of processing for this container
                                skip_rest_of_processing = True
                            else:
                                # This is a regular container element
                                skip_rest_of_processing = False
                        except Exception as e:
                            logger.error(f"Error getting container attributes: {e}")

                        # Skip metadata extraction if this is a synthetic container that we already processed
                        if "skip_rest_of_processing" in locals() and skip_rest_of_processing:
                            continue  # Skip to the next container

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
                            # logger.debug(f"Content desc: {content_desc}")

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
                            if normalized_target and title_match_func(book_info["title"], target_title):
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
                                        if title_match_func(book_info["title"], target_title):
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
                                new_titles_on_page.append(book_info["title"])
                            else:
                                logger.info(
                                    f"Already seen book ({len(seen_titles)} found): {book_info['title']}"
                                )
                        else:
                            logger.info(f"Container has no book info, skipping: {book_info}")
                    except StaleElementReferenceException:
                        logger.debug("Stale element reference, skipping container")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing container: {e}")
                        continue

                # Log a summary of this page's findings
                self._log_page_summary(page_count, new_titles_on_page, len(books))

                # If we've found no new books on this screen, we need to double-check
                if not new_books_found:
                    logger.info("No new books found on this screen, doing a double-check")
                    # Double-check by directly looking for titles that might not have been processed
                    try:
                        title_elements = self.driver.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                        )
                        current_screen_titles = [el.text for el in title_elements]

                        # If all these titles are already seen, then we can safely stop
                        new_unseen_titles = [t for t in current_screen_titles if t and t not in seen_titles]
                        if new_unseen_titles:
                            logger.info(
                                f"Double-check found {len(new_unseen_titles)} additional unseen titles"
                            )

                            # Add these titles to our seen set and create simple book entries for them
                            for new_title in new_unseen_titles:
                                seen_titles.add(new_title)
                                books.append(
                                    {"title": new_title, "progress": None, "size": None, "author": None}
                                )
                                new_titles_on_page.append(new_title)

                            # Update the summary with newly found titles
                            self._log_page_summary(page_count, new_titles_on_page, len(books))

                            # Update our flag since we found new books
                            new_books_found = True
                        else:
                            logger.info("Double-check confirms no new books, stopping scroll")
                            break
                    except Exception as e:
                        logger.error(f"Error during double-check for titles: {e}")
                        break

                # At this point, if nothing new was found after our double-check, or if we're seeing exactly the same books, stop
                if not new_books_found or seen_titles == previous_titles:
                    logger.info("No progress in finding new books, stopping scroll")
                    break

                # Scroll down to see more books
                # Don't log visible elements before scrolling to reduce noise

                # Find the bottom-most book container for smart scrolling
                try:
                    # Get all book containers currently visible
                    book_containers = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                    )

                    if book_containers and len(book_containers) >= 2:
                        logger.info(f"Found {len(book_containers)} book containers for smart scrolling")

                        # Get the bottom-most container (last in the list)
                        bottom_container = book_containers[-1]

                        # Get the second-from-bottom container as a fallback
                        second_bottom_container = book_containers[-2]

                        # Get location and size of the bottom container
                        location = bottom_container.location
                        size = bottom_container.size

                        # Calculate the y-coordinate of the bottom of this container
                        bottom_y = location["y"] + size["height"]
                        logger.info(f"Bottom-most container at y={bottom_y}, title='{bottom_container.text}'")

                        # Check if the bottom container is partially off-screen
                        if bottom_y > screen_size["height"]:
                            logger.info(
                                "Bottom container extends beyond screen, using second-from-bottom instead"
                            )
                            location = second_bottom_container.location
                            size = second_bottom_container.size
                            bottom_y = location["y"] + size["height"]
                            logger.info(
                                f"Using second-from-bottom container at y={bottom_y}, title='{second_bottom_container.text}'"
                            )

                        # Calculate smart scrolling coordinates with safety bounds
                        # Start from current position of bottom container
                        smart_start_y = min(
                            bottom_y - 10, screen_size["height"] - 20
                        )  # Ensure within screen bounds
                        # End at top of screen with small margin
                        smart_end_y = screen_size["height"] * 0.1

                        # Verify start point is below end point by a reasonable amount
                        if smart_start_y - smart_end_y < 100:
                            logger.warning("Scroll distance too small, using default scroll")
                            self.driver.swipe(
                                screen_size["width"] // 2, start_y, screen_size["width"] // 2, end_y, 1000
                            )
                        else:
                            # Perform smart scroll - move bottom container to top
                            self.driver.swipe(
                                screen_size["width"] // 2,
                                smart_start_y,
                                screen_size["width"] // 2,
                                smart_end_y,
                                1000,
                            )
                            logger.info(f"Performed smart scroll from y={smart_start_y} to y={smart_end_y}")
                    else:
                        logger.warning(
                            f"Not enough book containers found for smart scrolling ({len(book_containers) if book_containers else 0}), using default scroll"
                        )
                        # Fallback to default scroll behavior
                        self.driver.swipe(
                            screen_size["width"] // 2, start_y, screen_size["width"] // 2, end_y, 1000
                        )
                except Exception as e:
                    logger.error(f"Error during smart scrolling: {e}, falling back to default scroll")
                    # Fallback to default scroll behavior
                    self.driver.swipe(
                        screen_size["width"] // 2, start_y, screen_size["width"] // 2, end_y, 1000
                    )

            logger.info(f"Found total of {len(books)} unique books")

            # If we were looking for a specific book but didn't find it
            if target_title:
                # Check if this book was found but we couldn't grab the container
                found_matching_title = False
                for book in books:
                    if book.get("title") and title_match_func(book["title"], target_title):
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

    def _normalize_title(self, title: str) -> str:
        """
        Normalize a title for comparison while preserving important characters.
        This version is more selective about which characters to replace with spaces,
        keeping some punctuation that might be important for matching.
        """
        if not title:
            return ""

        # First convert to lowercase
        normalized = title.lower()

        # Replace less essential characters with spaces
        # Note: we're keeping apostrophes and colons intact for special handling
        for char in ',;"!@#$%^&*()[]{}_+=<>?/\\|~`':
            normalized = normalized.replace(char, " ")

        # Handle apostrophes specially - keep them but add spaces around them
        # This helps with matching parts before/after apostrophes
        if "'" in normalized:
            normalized = normalized.replace("'", " ' ")

        # Handle colons specially - keep them but add spaces around them
        if ":" in normalized:
            normalized = normalized.replace(":", " : ")

        # Replace multiple spaces with single space and strip
        normalized = " ".join(normalized.split())

        return normalized

    def _xpath_literal(self, s):
        """
        Create a valid XPath literal for a string that may contain both single and double quotes.
        Using a more robust implementation that handles special characters better.
        """
        if not s:
            return "''"

        # For titles with apostrophes, use a more reliable approach
        if "'" in s:
            # Log that we're handling a title with an apostrophe
            logger.info(f"Creating XPath for title with apostrophe: '{s}'")

            # Strategy 1: Use a combination of contains() for parts before and after apostrophe
            parts = s.split("'")
            conditions = []

            # Create conditions for non-empty parts, focusing on distinctive words
            for part in parts:
                if part:
                    # For each part, clean it up and use meaningful words for matching
                    clean_part = part.strip()
                    words = clean_part.split()

                    if words:
                        # Take the longest words (likely most distinctive) up to 3 words
                        sorted_words = sorted(words, key=len, reverse=True)
                        distinctive_words = sorted_words[: min(3, len(sorted_words))]

                        for word in distinctive_words:
                            if len(word) >= 3:  # Only use words of reasonable length for matching
                                safe_word = word.replace("'", "").replace('"', "")
                                conditions.append(f"contains(., '{safe_word}')")

            # Strategy 2: Also try matching with the text before the apostrophe
            if parts and parts[0]:
                first_part = parts[0].strip()
                if first_part and len(first_part) >= 3:
                    conditions.append(f"starts-with(normalize-space(.), '{first_part}')")

            # Strategy 3: Alternative for titles that have format "X : Y's Z"
            # Extract the parts around the colon if present
            if ":" in s:
                colon_parts = s.split(":")
                for colon_part in colon_parts:
                    clean_part = colon_part.strip()
                    if clean_part and len(clean_part) >= 5:  # Only use substantial parts
                        # Remove apostrophes for safer matching
                        safe_part = clean_part.replace("'", "").replace('"', "")
                        first_words = " ".join(safe_part.split()[:2])  # First two words
                        if first_words and len(first_words) >= 5:
                            conditions.append(f"contains(., '{first_words}')")

            # Join conditions with 'or' to be more lenient
            if conditions:
                xpath_expr = " or ".join(conditions)
                logger.info(f"Generated XPath expression: {xpath_expr}")
                return xpath_expr
            else:
                # Last resort: try to match any substantial part of the title
                words = s.replace("'", " ").split()
                substantial_words = [w for w in words if len(w) >= 5]

                if substantial_words:
                    word_conditions = [f"contains(., '{word}')" for word in substantial_words[:3]]
                    xpath_expr = " or ".join(word_conditions)
                    logger.info(f"Using substantial word fallback: {xpath_expr}")
                    return xpath_expr

                logger.warning(f"Failed to create reliable XPath for '{s}', using default")
                return "true()"  # Last resort fallback
        else:
            # For strings without apostrophes, use the simple approach
            return f"'{s}'"
