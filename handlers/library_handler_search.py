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

logger = logging.getLogger(__name__)


class LibraryHandlerSearch:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

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

    def _title_match(self, title1: str, title2: str) -> bool:
        """
        Check if titles match, with special handling for titles with apostrophes or colons.
        More lenient matching for titles with special characters.
        """
        if not title1 or not title2:
            return False

        # For exact matching, normalize both titles and compare
        norm1 = self._normalize_title(title1)
        norm2 = self._normalize_title(title2)

        # Log the normalized titles for debugging
        logger.info(f"Comparing titles: '{norm1}' with '{norm2}'")

        # First, try exact match
        if norm1 == norm2:
            logger.info("Exact match found")
            return True

        # For books with apostrophes or other special characters, try more lenient matching strategies
        if "'" in title1 or "'" in title2 or ":" in title1 or ":" in title2:
            logger.info("Title contains special characters, using more lenient matching")

            # Strategy 1: Check if one contains the other (common when titles are truncated)
            if norm1 in norm2 or norm2 in norm1:
                logger.info(f"Lenient containment match successful between '{norm1}' and '{norm2}'")
                return True

            # Strategy 2: Split by apostrophe and check parts
            for title, norm, other_norm in [(title1, norm1, norm2), (title2, norm2, norm1)]:
                if "'" in title:
                    parts = title.split("'")
                    for part in parts:
                        clean_part = part.strip()
                        if clean_part and len(clean_part) >= 3 and clean_part.lower() in other_norm:
                            logger.info(
                                f"Apostrophe part match successful with '{clean_part.lower()}' in '{other_norm}'"
                            )
                            return True

            # Strategy 3: Split by colon and check parts
            for title, norm, other_norm in [(title1, norm1, norm2), (title2, norm2, norm1)]:
                if ":" in title:
                    parts = title.split(":")
                    for part in parts:
                        clean_part = part.strip()
                        if clean_part and len(clean_part) >= 5 and clean_part.lower() in other_norm:
                            logger.info(
                                f"Colon part match successful with '{clean_part.lower()}' in '{other_norm}'"
                            )
                            return True

            # Strategy 4: Compare significant words in both titles
            words1 = set(w.lower() for w in norm1.split() if len(w) >= 4)
            words2 = set(w.lower() for w in norm2.split() if len(w) >= 4)

            # Check if there's substantial word overlap
            common_words = words1.intersection(words2)
            if len(common_words) >= 2 or (len(common_words) >= 1 and len(words1) <= 3 and len(words2) <= 3):
                logger.info(f"Word overlap match successful with common words: {common_words}")
                return True

            # Strategy 5: Check for distinctive words or phrases
            distinctive_phrases = []

            # Add key distinctive phrases from each title
            for title in [title1, title2]:
                # Get phrases that might be distinctive
                if ":" in title:
                    for part in title.split(":"):
                        clean_part = part.strip().lower()
                        if clean_part and len(clean_part) >= 5:
                            distinctive_phrases.append(clean_part)

                # Add the first part of each title as a distinctive phrase
                words = title.strip().split()
                if len(words) >= 2:
                    first_two_words = " ".join(words[:2]).lower()
                    distinctive_phrases.append(first_two_words)

            # Check if any distinctive phrase appears in both titles
            for phrase in distinctive_phrases:
                if phrase in norm1.lower() and phrase in norm2.lower() and len(phrase) >= 5:
                    logger.info(f"Distinctive phrase match with '{phrase}'")
                    return True

        # No match found with any strategy
        return False

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

    def _check_book_visible_on_screen(self, book_title: str):
        """Check if a book is already visible on the current screen without scrolling.

        Args:
            book_title (str): The title of the book to check for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            logger.info(f"Checking if '{book_title}' is visible on current screen")
            store_page_source(self.driver.page_source, "check_book_visible")

            # Store a matched title element and info for fallback if we can't find the button right away
            matched_title_element = None
            matched_title_text = None

            # Look directly for buttons in the recycler view - more reliable approach
            book_buttons = self.driver.find_elements(
                AppiumBy.XPATH,
                "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']/android.widget.Button",
            )

            if book_buttons:
                logger.info(f"Found {len(book_buttons)} book buttons on current screen")

                # First check buttons directly by content-desc
                for button in book_buttons:
                    try:
                        content_desc = button.get_attribute("content-desc") or ""
                        logger.info(f"Book button content-desc: {content_desc}")

                        # Check if our target book title is in the content-desc
                        if book_title.lower() in content_desc.lower():
                            logger.info(f"Found button with matching content-desc: {content_desc}")

                            # Extract book info from content-desc
                            parts = content_desc.split(",")
                            book_info = {"title": parts[0].strip()}
                            if len(parts) > 1:
                                book_info["author"] = parts[1].strip()

                            return button, button, book_info

                        # Also try child elements if we didn't match content-desc
                        title_elements = button.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                        )

                        for title_element in title_elements:
                            title_text = title_element.text
                            logger.info(f"Found title element in button: {title_text}")

                            if self._title_match(title_text, book_title):
                                logger.info(f"Found matching title: '{title_text}' for '{book_title}'")
                                # Store this match in case we need to return to it
                                matched_title_element = title_element
                                matched_title_text = title_text
                                return button, button, {"title": title_text}
                    except Exception as e:
                        logger.debug(f"Error processing button: {e}")
                        continue

            # If we didn't find any matching buttons, try the original approach
            # Find all title elements currently visible on the screen
            title_elements = self.driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title")

            if not title_elements:
                logger.info("No title elements found on current screen")
                return None

            logger.info(f"Found {len(title_elements)} title elements on current screen")

            # Check each title to see if it matches our target book
            for title_element in title_elements:
                try:
                    title_text = title_element.text
                    logger.info(f"Checking title element: '{title_text}'")

                    # Check if this title matches our target book
                    if self._title_match(title_text, book_title):
                        logger.info(f"Found matching title: '{title_text}' for '{book_title}'")
                        # Store the match for fallback if needed
                        matched_title_element = title_element
                        matched_title_text = title_text

                        # Try to find the parent button in different ways
                        try:
                            # Try direct parent lookup
                            parent = title_element.find_element(AppiumBy.XPATH, "./../../..")
                            if parent.get_attribute("class") == "android.widget.Button":
                                logger.info("Found parent button via direct path")
                                return parent, parent, {"title": title_text}
                        except Exception:
                            pass

                        try:
                            # Try by exact title match
                            title_escaped = title_text.replace("'", "\\'").replace('"', '\\"')
                            xpath = f"//android.widget.Button[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text='{title_escaped}']]"
                            button = self.driver.find_element(AppiumBy.XPATH, xpath)
                            logger.info("Found button via exact title match")
                            return button, button, {"title": title_text}
                        except Exception:
                            pass

                        try:
                            # Try a more lenient approach with contains
                            first_word = title_text.split()[0].replace("'", "\\'").replace('"', '\\"')
                            if len(first_word) >= 3:  # Only use reasonably distinctive first words
                                xpath = f"//android.widget.Button[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and contains(@text, '{first_word}')]]"
                                button = self.driver.find_element(AppiumBy.XPATH, xpath)
                                logger.info(f"Found button via first word match: {first_word}")
                                return button, button, {"title": title_text}
                        except Exception:
                            pass

                        # Don't return yet, keep trying other titles first
                except Exception as e:
                    logger.debug(f"Error processing title element: {e}")
                    continue

            # If we get here and we have a matched title but couldn't find the button,
            # use the title element as a fallback
            if matched_title_element and matched_title_text:
                logger.warning(
                    "Found matching title but could not locate the parent button - trying with title's parent"
                )
                try:
                    parent = matched_title_element.find_element(AppiumBy.XPATH, "./..")
                    return parent, matched_title_element, {"title": matched_title_text}
                except Exception as e:
                    logger.error(f"Error finding title's parent: {e}")
                    # Last resort - return the title element itself
                    return matched_title_element, matched_title_element, {"title": matched_title_text}

            logger.info("Target book not found on current screen")
            return None

        except Exception as e:
            logger.error(f"Error checking if book is visible on screen: {e}")
            traceback.print_exc()
            return None

    def _find_book_by_partial_match(self, book_title: str, scroll_through_library_func=None):
        """
        Fallback method to find a book by attempting various partial matching strategies.
        Used when normal title matching fails.

        Args:
            book_title (str): The book title to search for
            scroll_through_library_func: Function to call to scroll through library

        Returns:
            Tuple of (parent_container, button, book_info) or (None, None, None)
        """
        logger.info(f"Attempting to find book by partial matching: '{book_title}'")

        try:
            # Try to find books with similar titles first
            all_books = scroll_through_library_func()

            # Save list of available titles for debugging
            book_titles = [book.get("title", "") for book in all_books if book.get("title")]
            logger.info(f"Found {len(book_titles)} books in library: {book_titles}")

            # Try different matching strategies
            for book in all_books:
                if not book.get("title"):
                    continue

                title = book.get("title")
                logger.info(f"Comparing with book: '{title}'")

                # 1. Check if target title is part of this book's title or vice versa
                if book_title.lower() in title.lower() or title.lower() in book_title.lower():
                    logger.info(f"Found potential match by containment: '{title}'")

                    # Try to find the book element
                    try:
                        # First try with ID and partial text matching
                        xpath = f"//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and contains(@text, '{title.split()[0]}')]"
                        elements = self.driver.find_elements(AppiumBy.XPATH, xpath)

                        if elements:
                            logger.info(f"Found {len(elements)} potential matching elements")
                            # Find the parent container
                            for element in elements:
                                try:
                                    # Get the parent container (usually 2 levels up)
                                    parent = element.find_element(AppiumBy.XPATH, "../..")

                                    # Verify this is the right book
                                    if title.split()[0].lower() in element.text.lower():
                                        logger.info(f"Confirmed match for '{title}'")
                                        return parent, element, book
                                except Exception as e:
                                    logger.debug(f"Error finding parent: {e}")
                                    continue
                    except Exception as e:
                        logger.debug(f"Error during element search: {e}")
                        continue

            # If no matches found yet, try more aggressive matching with distinctive words
            logger.info("Trying more aggressive word-based matching")

            # Extract distinctive words from the target title (longer words likely more unique)
            target_words = [w.lower() for w in book_title.split() if len(w) >= 4]
            target_words.sort(key=len, reverse=True)  # Sort by length, longest first

            if target_words:
                logger.info(f"Using distinctive words for matching: {target_words[:3]}")

                # Try to find books containing these distinctive words
                for word in target_words[:3]:  # Try up to 3 most distinctive words
                    if len(word) < 4:  # Skip short words
                        continue

                    try:
                        # Search by distinctive word
                        xpath = f"//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and contains(@text, '{word}')]"
                        elements = self.driver.find_elements(AppiumBy.XPATH, xpath)

                        if elements:
                            logger.info(f"Found {len(elements)} elements containing '{word}'")

                            # Check each element
                            for element in elements:
                                try:
                                    element_text = element.text
                                    logger.info(f"Checking element with text: '{element_text}'")

                                    # Get the parent container
                                    parent = element.find_element(AppiumBy.XPATH, "../..")

                                    # Create a book info dict
                                    book_info = {"title": element_text}

                                    # Extract author if possible
                                    try:
                                        author_element = parent.find_element(
                                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_author"
                                        )
                                        book_info["author"] = author_element.text
                                    except:
                                        pass

                                    logger.info(f"Found potential match by word '{word}': {book_info}")
                                    return parent, element, book_info
                                except Exception as e:
                                    logger.debug(f"Error processing element: {e}")
                                    continue
                    except Exception as e:
                        logger.debug(f"Error searching for word '{word}': {e}")
                        continue

            # If we got here, no matching book was found
            logger.warning(f"No matching book found for '{book_title}' using partial matching strategies")
            return None, None, None

        except Exception as e:
            logger.error(f"Error in partial book matching: {e}")
            traceback.print_exc()
            return None, None, None

    def _search_for_book(self, book_title: str):
        """Use the search box to find a book by title.

        Args:
            book_title (str): The title of the book to search for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            logger.info(f"Attempting to find book '{book_title}' using search box")

            # Find and click the search box
            try:
                # Take a screenshot and save page source before search
                store_page_source(self.driver.page_source, "before_search")
                self.driver.save_screenshot(os.path.join(self.screenshots_dir, "before_search.png"))

                search_box = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_box")
                logger.info("Found search box, clicking it")
                search_box.click()
                time.sleep(1)  # Wait for search interface to appear

                # Take a screenshot after clicking search box
                store_page_source(self.driver.page_source, "after_search_click")
                self.driver.save_screenshot(os.path.join(self.screenshots_dir, "after_search_click.png"))

                # Now the search input field should be visible and active
                # Based on the XML analysis, we know the exact ID for the search field
                search_field = None
                try:
                    search_field = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
                    logger.info("Found search input field with ID: com.amazon.kindle:id/search_query")
                except NoSuchElementException:
                    logger.debug("Could not find search field with ID com.amazon.kindle:id/search_query")

                    # Fallback to other potential IDs
                    search_field_ids = [
                        "com.amazon.kindle:id/search_src_text",
                        "com.amazon.kindle:id/search_edit_text",
                        "android:id/search_src_text",
                        "com.amazon.kindle:id/search_text_field",
                    ]

                    for field_id in search_field_ids:
                        try:
                            search_field = self.driver.find_element(AppiumBy.ID, field_id)
                            logger.info(f"Found search input field with ID: {field_id}")
                            break
                        except NoSuchElementException:
                            continue

                # If we still couldn't find the search field by ID, try XPath
                if not search_field:
                    try:
                        # Try to find by class name EditText that has a hint or text containing "search"
                        search_field = self.driver.find_element(
                            AppiumBy.XPATH,
                            "//android.widget.EditText[contains(@content-desc, 'search') or contains(@text, 'search') or contains(@hint, 'search') or contains(@resource-id, 'search')]",
                        )
                        logger.info("Found search input field by XPath")
                    except NoSuchElementException:
                        logger.error("Could not find search input field")
                        return None

                # Clear any existing text and enter the book title
                search_field.clear()
                search_field.send_keys(book_title)
                logger.info(f"Entered book title in search field: '{book_title}'")

                # Save screenshot after entering text
                store_page_source(self.driver.page_source, "after_search_text_entry")
                self.driver.save_screenshot(os.path.join(self.screenshots_dir, "after_search_text_entry.png"))

                # Press Enter/Search key on the keyboard
                self.driver.press_keycode(66)  # Android keycode for Enter/Search
                logger.info("Pressed Enter to execute search")

                # Give time for search results to load
                time.sleep(2)

                # Save screenshot and page source with search results
                store_page_source(self.driver.page_source, "search_results")
                self.driver.save_screenshot(os.path.join(self.screenshots_dir, "search_results.png"))

                # Check for search results
                # Based on XML analysis, search results are displayed in a grid view
                logger.info("Looking for search results in the grid view")

                # First try to find the grid container
                try:
                    grid_container = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/grid_search_result"
                    )
                    logger.info("Found grid search result container")
                except NoSuchElementException:
                    grid_container = None
                    logger.debug("Could not find grid search result container")

                # If we couldn't find the grid container, try to find the grid view
                if not grid_container:
                    try:
                        grid_container = self.driver.find_element(
                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_cover_container"
                        )
                        logger.info("Found grid book cover container")
                    except NoSuchElementException:
                        logger.debug("Could not find lib_book_cover_container")

                # Based on the XML analysis, we need to try different approaches

                # Approach 1: Try to find the grid_search_result container
                try:
                    grid_search_container = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/grid_search_result"
                    )
                    logger.info("Found grid_search_result container")

                    # Now find the badgeable_cover button inside it
                    try:
                        book_button = grid_search_container.find_element(
                            AppiumBy.ID, "com.amazon.kindle:id/badgeable_cover"
                        )
                        logger.info("Found badgeable_cover button inside grid_search_result")

                        # Get its content-desc to check if it's the right book
                        content_desc = book_button.get_attribute("content-desc") or ""
                        logger.info(f"Book button content-desc: {content_desc}")

                        # Check if this is the right book
                        if book_title.lower() in content_desc.lower():
                            logger.info(f"Found matching book in search results: '{book_title}'")

                            # Create book info dictionary from content-desc
                            parts = content_desc.split(",")
                            book_info = {"title": parts[0].strip()}
                            if len(parts) > 1:
                                book_info["author"] = parts[1].strip()

                            # Return the result - use the grid_search_container as the clickable element
                            return grid_search_container, grid_search_container, book_info
                    except NoSuchElementException:
                        logger.debug("Could not find badgeable_cover inside grid_search_result")
                except NoSuchElementException:
                    logger.debug("Could not find grid_search_result container")

                # Approach 2: Check if there's a "Recent searches" item with our book title
                try:
                    # Look for a TextView that contains our book title in the recent searches
                    recent_search_items = self.driver.find_elements(
                        AppiumBy.XPATH, f"//android.widget.TextView[contains(@text, '{book_title}')]"
                    )

                    if recent_search_items:
                        for item in recent_search_items:
                            try:
                                item_text = item.text
                                logger.info(f"Found recent search item: {item_text}")

                                # If this is our book, find its parent view
                                if book_title.lower() in item_text.lower():
                                    logger.info(f"Found matching recent search: '{item_text}'")

                                    # Find the parent view that's clickable
                                    try:
                                        parent_view = item.find_element(
                                            AppiumBy.XPATH, "./ancestor::*[@clickable='true'][1]"
                                        )
                                        logger.info("Found clickable parent for recent search item")

                                        # Create simple book info
                                        book_info = {"title": item_text}

                                        # Click the item to search for it
                                        parent_view.click()
                                        logger.info(f"Clicked on recent search item: {item_text}")

                                        # Wait for search results to load
                                        time.sleep(2)

                                        # Now look for the actual search result - this is recursive but should only happen once
                                        return self._search_for_book(book_title)
                                    except Exception as parent_e:
                                        logger.debug(
                                            f"Error finding or clicking parent view for recent search: {parent_e}"
                                        )
                            except Exception as e:
                                logger.debug(f"Error processing recent search item: {e}")
                    else:
                        logger.debug("No matching recent search items found")
                except Exception as e:
                    logger.debug(f"Error checking recent searches: {e}")

                # Approach 3: Try to find any badgeable_cover button
                try:
                    book_buttons = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/badgeable_cover"
                    )
                    logger.info(f"Found {len(book_buttons)} badgeable_cover buttons")

                    for book_button in book_buttons:
                        try:
                            # Get its content-desc to check if it's the right book
                            content_desc = book_button.get_attribute("content-desc") or ""
                            logger.info(f"Book button content-desc: {content_desc}")

                            # Check if this is the right book
                            if book_title.lower() in content_desc.lower():
                                logger.info(f"Found matching book in search results: '{book_title}'")

                                # Find the parent container (the LinearLayout that contains the button)
                                try:
                                    parent_container = book_button.find_element(AppiumBy.XPATH, "./..")
                                    if parent_container.get_attribute("clickable") == "true":
                                        logger.info("Found clickable parent container for book button")
                                    else:
                                        # Go up one more level if this parent isn't clickable
                                        parent_container = parent_container.find_element(
                                            AppiumBy.XPATH, "./.."
                                        )
                                        logger.info("Found parent's parent container for book button")
                                except NoSuchElementException:
                                    # If we can't find the parent, use the button itself
                                    parent_container = book_button
                                    logger.info("Using book button as parent container")

                                # Create book info dictionary from content-desc
                                parts = content_desc.split(",")
                                book_info = {"title": parts[0].strip()}
                                if len(parts) > 1:
                                    book_info["author"] = parts[1].strip()

                                # Return the result - we'll click on the parent container
                                return parent_container, book_button, book_info
                        except Exception as e:
                            logger.debug(f"Error processing book button: {e}")
                            continue
                except Exception as e:
                    logger.debug(f"Error finding badgeable_cover buttons: {e}")

                # If we couldn't find the book button directly, look for any clickable items with content-desc containing our book title
                try:
                    # Look for any elements in the search results that might contain our book
                    elements = self.driver.find_elements(
                        AppiumBy.XPATH,
                        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/search_recycler_view']//*[@clickable='true']",
                    )

                    logger.info(f"Found {len(elements)} potential clickable elements in search results")

                    for element in elements:
                        try:
                            content_desc = element.get_attribute("content-desc") or ""
                            if book_title.lower() in content_desc.lower():
                                logger.info(f"Found element with matching content-desc: {content_desc}")

                                # Create book info dictionary from content-desc
                                parts = content_desc.split(",")
                                book_info = {"title": parts[0].strip()}
                                if len(parts) > 1:
                                    book_info["author"] = parts[1].strip()

                                # Return the result
                                return element, element, book_info
                        except Exception as e:
                            logger.debug(f"Error processing element: {e}")
                            continue
                except Exception as e:
                    logger.debug(f"Error finding clickable elements: {e}")

                # If we still couldn't find any matches, check if there's a "No results" message
                try:
                    no_results = self.driver.find_element(
                        AppiumBy.XPATH,
                        "//*[contains(@text, 'No results') or contains(@content-desc, 'No results')]",
                    )
                    if no_results:
                        logger.info("Search found no results")
                except NoSuchElementException:
                    logger.info("No explicit 'No results' message found")

                # Exit search mode and return to library
                try:
                    back_button = self.driver.find_element(
                        AppiumBy.XPATH,
                        "//*[@content-desc='Navigate up' or @content-desc='Back' or @content-desc='back']",
                    )
                    back_button.click()
                    logger.info("Clicked back button to exit search")
                    time.sleep(1)
                except NoSuchElementException:
                    logger.warning("Could not find back button, trying hardware back")
                    self.driver.press_keycode(4)  # Android back button

                return None

            except NoSuchElementException:
                logger.error("Could not find search box")
                return None

        except Exception as e:
            logger.error(f"Error searching for book: {e}")
            # Try to exit search mode in case we're stuck there
            try:
                self.driver.press_keycode(4)  # Android back button
                time.sleep(1)
            except:
                pass
            return None
