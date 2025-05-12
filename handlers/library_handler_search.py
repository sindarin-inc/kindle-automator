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
from views.library.view_strategies import (
    SEARCH_BACK_BUTTON_IDENTIFIERS,
    SEARCH_BOX_IDENTIFIERS,
    SEARCH_INPUT_IDENTIFIERS,
    SEARCH_RESULT_ITEM_IDENTIFIERS,
    SEARCH_RESULTS_IDENTIFIERS,
)

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

            # Find all text elements
            title_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")

            if not title_elements:
                logger.info("No text elements found on current screen")
                return None

            logger.info(f"Found {len(title_elements)} text elements on current screen")

            # Check each title to see if it matches our target book
            for title_element in title_elements:
                try:
                    title_text = title_element.text
                    if not title_text:
                        continue

                    # Check if this title matches our target book
                    if self._title_match(title_text, book_title):
                        logger.info(f"Found matching title: '{title_text}' for '{book_title}'")
                        # Store the match for fallback if needed
                        matched_title_element = title_element
                        matched_title_text = title_text

                        # Try to find the parent button
                        try:
                            # Go up through parent elements to find a clickable one
                            current = title_element
                            for _ in range(3):  # Try up to 3 levels up
                                try:
                                    parent = current.find_element(AppiumBy.XPATH, "./..")
                                    if parent.get_attribute("clickable") == "true":
                                        logger.info("Found clickable parent")
                                        return parent, parent, {"title": title_text}
                                    current = parent
                                except:
                                    break
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Error processing title element: {e}")
                    continue

            # If we have a matched title but couldn't find a clickable parent,
            # try a different approach
            if matched_title_element and matched_title_text:
                logger.info("Found matching title but couldn't find clickable parent")

                # Try to find a clickable element near this text
                try:
                    title_y = matched_title_element.location["y"]

                    # Get all buttons
                    buttons = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.Button")

                    # Find buttons near our text element
                    for button in buttons:
                        try:
                            button_y = button.location["y"]
                            # If button is close to our text (within 100 pixels)
                            if abs(button_y - title_y) < 100:
                                logger.info(f"Found button near matching text at y={button_y}")
                                return button, button, {"title": matched_title_text}
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"Error finding nearby buttons: {e}")

                # Last resort: return the text element itself
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
                        # Find titles with similar text
                        title_elements = self.driver.find_elements(
                            AppiumBy.CLASS_NAME, "android.widget.TextView"
                        )

                        for element in title_elements:
                            try:
                                if element.text and title.lower() in element.text.lower():
                                    logger.info(f"Found matching text element: '{element.text}'")

                                    # Try to find a clickable parent
                                    current = element
                                    for _ in range(3):  # Try up to 3 levels up
                                        try:
                                            parent = current.find_element(AppiumBy.XPATH, "./..")
                                            if parent.get_attribute("clickable") == "true":
                                                logger.info("Found clickable parent")
                                                return parent, parent, book
                                            current = parent
                                        except:
                                            break
                            except:
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

                # Try to find text elements containing these distinctive words
                for word in target_words[:3]:  # Try up to 3 most distinctive words
                    if len(word) < 4:  # Skip short words
                        continue

                    try:
                        # Find text elements containing our word
                        text_elements = self.driver.find_elements(
                            AppiumBy.CLASS_NAME, "android.widget.TextView"
                        )

                        for element in text_elements:
                            try:
                                element_text = element.text
                                if element_text and word.lower() in element_text.lower():
                                    logger.info(f"Found text containing '{word}': '{element_text}'")

                                    # Try to find a clickable parent
                                    current = element
                                    for _ in range(3):  # Try up to 3 levels up
                                        try:
                                            parent = current.find_element(AppiumBy.XPATH, "./..")
                                            if parent.get_attribute("clickable") == "true":
                                                logger.info("Found clickable parent")

                                                # Create book info
                                                book_info = {"title": element_text}

                                                return parent, parent, book_info
                                            current = parent
                                        except:
                                            break

                                    # If no clickable parent found, try finding nearby buttons
                                    try:
                                        element_y = element.location["y"]
                                        buttons = self.driver.find_elements(
                                            AppiumBy.CLASS_NAME, "android.widget.Button"
                                        )

                                        for button in buttons:
                                            try:
                                                button_y = button.location["y"]
                                                if abs(button_y - element_y) < 100:
                                                    logger.info(
                                                        f"Found button near matching text at y={button_y}"
                                                    )
                                                    return button, button, {"title": element_text}
                                            except:
                                                continue
                                    except Exception as e:
                                        logger.debug(f"Error finding nearby buttons: {e}")
                            except:
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

        This implementation avoids complex XPath expressions.

        Args:
            book_title (str): The title of the book to search for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            logger.info(f"Searching for book '{book_title}' using simplified implementation")

            # Save screenshots for debugging
            store_page_source(self.driver.page_source, "before_search")
            self.driver.save_screenshot(os.path.join(self.screenshots_dir, "before_search.png"))

            # Find search box
            search_box = None
            try:
                search_box = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_box")
                logger.info("Found search box by ID")
            except:
                # Try finding by class name and content-desc
                linear_layouts = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.LinearLayout")
                for layout in linear_layouts:
                    try:
                        if layout.get_attribute("resource-id") == "com.amazon.kindle:id/search_box":
                            search_box = layout
                            logger.info("Found search box by class name and resource-id")
                            break
                    except:
                        continue

            if not search_box:
                logger.error("Could not find search box")
                return None

            # Click search box
            search_box.click()
            logger.info("Clicked search box")
            time.sleep(1)

            # Save screenshot after clicking search box
            store_page_source(self.driver.page_source, "after_search_click")
            self.driver.save_screenshot(os.path.join(self.screenshots_dir, "after_search_click.png"))

            # Find search input field
            search_field = None
            try:
                search_field = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
                logger.info("Found search input field by ID")
            except:
                # Try finding by class name
                edit_texts = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.EditText")
                if edit_texts:
                    search_field = edit_texts[0]
                    logger.info("Found search input field by class name")

            if not search_field:
                logger.error("Could not find search input field")
                self._exit_search_mode()
                return None

            # Clear and enter book title
            search_field.clear()
            search_field.send_keys(book_title)
            logger.info(f"Entered book title in search field: '{book_title}'")

            # Save screenshot after entering text
            store_page_source(self.driver.page_source, "after_search_text_entry")
            self.driver.save_screenshot(os.path.join(self.screenshots_dir, "after_search_text_entry.png"))

            # Press Enter key
            self.driver.press_keycode(66)  # Android keycode for Enter/Search
            logger.info("Pressed Enter to execute search")

            # Wait for search results
            time.sleep(1)

            # Save search results
            store_page_source(self.driver.page_source, "search_results")
            self.driver.save_screenshot(os.path.join(self.screenshots_dir, "search_results.png"))

            # Find "In your library" section and "Results from" section to establish boundaries
            in_library_section = None
            in_library_y = 0
            results_from_section = None
            results_from_y = float("inf")  # Default to bottom of screen if not found

            # Get all text elements
            text_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            logger.info(f"Found {len(text_elements)} text elements")

            # First pass: look for both section headers
            for element in text_elements:
                try:
                    text = element.text
                    if not text:
                        continue

                    # Look for "In your library" text
                    if "In your library" in text:
                        in_library_section = element
                        in_library_y = element.location["y"]
                        logger.info(f"Found 'In your library' section at y={in_library_y}")

                    # Look for "Results from" text
                    elif "Results from" in text:
                        results_from_section = element
                        results_from_y = element.location["y"]
                        logger.info(f"Found 'Results from' section at y={results_from_y}")
                except Exception as e:
                    logger.debug(f"Error checking section headers: {e}")
                    continue

            if not in_library_section:
                logger.info("Could not find 'In your library' section")
                self._exit_search_mode()
                return None

            # If we didn't find the "Results from" section, use screen height as fallback
            if not results_from_section:
                logger.info("Could not find 'Results from' section, using screen height as boundary")
                # Set a default boundary using screen height
                screen_size = self.driver.get_window_size()
                results_from_y = screen_size["height"] - 100  # Use near bottom of screen

            # Look for "No results" message or any other text elements in the library section
            in_library_text_elements = []
            for element in text_elements:
                try:
                    text = element.text
                    if not text:
                        continue

                    y = element.location["y"]
                    # Make sure in_library_y has a valid value (greater than zero)
                    if in_library_y < 1:
                        logger.warning("Invalid in_library_y position, using default values")
                        continue

                    # Only check elements in the library section (between "In your library" and "Results from")
                    if in_library_y < y < results_from_y:
                        logger.info(f"Text element in library section at y={y}: '{text}'")
                        in_library_text_elements.append((element, text))

                        # Check for "No results" type messages
                        if any(
                            phrase in text.lower()
                            for phrase in [
                                "no results",
                                "not found",
                                "empty",
                                "no books",
                                "no matching",
                                "couldn't find",
                            ]
                        ):
                            logger.info(f"Found 'No results' message in library section: {text}")
                            self._exit_search_mode()
                            return None
                except Exception as e:
                    logger.debug(f"Error processing text element: {e}")
                    continue

            # If we don't find any text elements in the library section, that likely means
            # there are no books matching the search query in the library
            if not in_library_text_elements:
                logger.info(
                    "No text elements found in library section - likely means no matching books in library"
                )

                # Check for empty library section by looking at pixels between sections
                library_section_height = results_from_y - in_library_y
                logger.info(f"Library section height: {library_section_height}px")

                if library_section_height < 150:  # If section is less than 150px tall
                    logger.info("Library section appears to be empty (small height)")
                    self._exit_search_mode()
                    return None

                # Try to find "No results" text or similar messages anywhere in the view
                no_results_found = False
                for element in text_elements:
                    try:
                        text = element.text.lower() if element.text else ""
                        if any(
                            phrase in text
                            for phrase in [
                                "no results",
                                "no matches",
                                "not found",
                                "could not find",
                                "empty",
                                "no books",
                            ]
                        ):
                            y_pos = element.location["y"]
                            logger.info(f"Found potential 'No results' message: '{text}' at y={y_pos}")
                            # If this text is located near the library section, it's likely a no results message
                            if in_library_y - 50 <= y_pos <= results_from_y + 50:
                                logger.info(f"Confirmed 'No results' message in library section: '{text}'")
                                no_results_found = True
                                break
                    except Exception as e:
                        logger.debug(f"Error checking text element for no results message: {e}")
                        continue

                if no_results_found:
                    logger.info("No results message found in library section, exiting search mode")
                    self._exit_search_mode()
                    return None

                # If we still can't determine if there are no results, check for visual cues
                # Such as: lack of any clickable elements in the library section
                clickable_elements_in_library = 0
                try:
                    all_elements = self.driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
                    for element in all_elements:
                        try:
                            y = element.location["y"]
                            if in_library_y < y < results_from_y:
                                clickable_elements_in_library += 1
                                logger.info(f"Found clickable element in library section at y={y}")
                        except Exception as e:
                            logger.debug(f"Error checking clickable element position: {e}")
                            continue

                    logger.info(
                        f"Found {clickable_elements_in_library} clickable elements in library section"
                    )
                    if clickable_elements_in_library == 0:
                        logger.info("No clickable elements in library section, likely empty results")
                        self._exit_search_mode()
                        return None
                except Exception as e:
                    logger.debug(f"Error counting clickable elements: {e}")
                    # Continue anyway since this is just a supplementary check

            # We've already found the "Results from" section in the first pass,
            # so no need to search for it again.

            # First, try to find all elements in the library section specifically
            # This is critical to avoid matching books in the "Results from Kindle" section

            logger.info("Searching specifically for elements in the 'In your library' section")

            # Start by looking for elements directly in the library section
            library_section_elements = []

            # Approach 1: Find all elements between "In your library" and "Results from" sections
            # Get all elements (we'll filter by position later)
            all_elements = self.driver.find_elements(AppiumBy.XPATH, "//*")
            logger.info(f"Found {len(all_elements)} total elements, filtering by position")

            # Set search margin - start 50px below "In your library" header
            start_y = in_library_y + 50

            # Find buttons, especially those with content-desc that might have our book
            library_buttons = []
            library_buttons_with_content = []

            # Log the search boundaries
            logger.info(f"Library section boundary: y > {start_y} and y < {results_from_y}")

            # First look specifically for buttons with content-desc attributes in the library section
            for element in all_elements:
                try:
                    # Check element type - we're especially interested in buttons
                    class_name = element.get_attribute("class") or ""

                    # Skip text elements, etc. - focus on containers and buttons
                    if "TextView" in class_name:
                        continue

                    # Get position to check if in library section
                    y = element.location["y"]

                    # Check if this element is in the library section
                    if start_y <= y < results_from_y:
                        # Check if it has content-desc (especially important for buttons)
                        content_desc = element.get_attribute("content-desc") or ""

                        # If it's a button, add it to our library buttons list
                        if "Button" in class_name:
                            library_buttons.append(element)

                            # If it also has content-desc, it's even more interesting
                            if content_desc:
                                library_buttons_with_content.append((element, content_desc))
                                logger.info(
                                    f"Found button with content-desc in library section at y={y}: '{content_desc}'"
                                )

                                # Check for book title substring in content-desc (key part!)
                                if book_title.lower() in content_desc.lower():
                                    logger.info(
                                        f"FOUND DIRECT MATCH! Button with content-desc contains book title: '{content_desc}'"
                                    )
                                    # Create book info
                                    book_info = {"title": book_title}

                                    # Extract more info from content-desc if available
                                    parts = content_desc.split(",")
                                    if len(parts) > 0:
                                        book_info["title"] = parts[0].strip()
                                    if len(parts) > 1:
                                        book_info["author"] = parts[1].strip()

                                    # This is a direct match for what we're looking for
                                    logger.info(f"Found book by content-desc substring match: {book_info}")
                                    return element, element, book_info

                        # Add element to general list of elements in the library section
                        library_section_elements.append(element)
                except Exception as e:
                    logger.debug(f"Error checking element position: {e}")
                    continue

            logger.info(f"Found {len(library_section_elements)} elements in the library section")
            logger.info(f"Found {len(library_buttons)} buttons in the library section")
            logger.info(
                f"Found {len(library_buttons_with_content)} buttons with content-desc in the library section"
            )

            # If we found buttons with content-desc but no direct title match yet,
            # try more relaxed matching on those first (they're likely our best candidates)
            if library_buttons_with_content:
                logger.info("Trying relaxed matching on buttons with content-desc in library section")

                for element, content_desc in library_buttons_with_content:
                    try:
                        # Log what we're checking
                        logger.info(f"Checking button content-desc for relaxed match: '{content_desc}'")

                        # Check for partial or case-insensitive match
                        book_parts = book_title.lower().split()
                        content_parts = content_desc.lower().split()

                        # Look for significant word matches
                        matches = set(book_parts) & set(content_parts)

                        if len(matches) >= max(1, len(book_parts) // 2):
                            logger.info(f"Found word-level match: {matches}")

                            # Create book info
                            book_info = {"title": book_title}

                            # Extract info from content-desc
                            parts = content_desc.split(",")
                            if len(parts) > 0:
                                book_info["title"] = parts[0].strip()
                            if len(parts) > 1:
                                book_info["author"] = parts[1].strip()

                            logger.info(f"Found matching book with relaxed matching: {book_info}")
                            return element, element, book_info

                        # Check if the first few letters of each word match
                        # This catches small variations like "The world without us" vs "The World Without Us"
                        strong_match = True
                        for book_word in book_parts:
                            if len(book_word) < 3:  # Skip short words like "the", "and", etc.
                                continue

                            prefix_matched = False
                            for content_word in content_parts:
                                # Check if first 3 letters match
                                if (
                                    len(book_word) >= 3
                                    and len(content_word) >= 3
                                    and book_word[:3] == content_word[:3]
                                ):
                                    prefix_matched = True
                                    break

                            if not prefix_matched and len(book_word) >= 3:
                                strong_match = False
                                break

                        if strong_match:
                            logger.info(f"Found prefix match for words in: '{content_desc}'")

                            # Create book info
                            book_info = {"title": book_title}

                            # Extract info from content-desc
                            parts = content_desc.split(",")
                            if len(parts) > 0:
                                book_info["title"] = parts[0].strip()
                            if len(parts) > 1:
                                book_info["author"] = parts[1].strip()

                            logger.info(f"Found matching book with prefix matching: {book_info}")
                            return element, element, book_info
                    except Exception as e:
                        logger.debug(f"Error during relaxed content-desc matching: {e}")
                        continue

            # Fallback to general elements in the library section if we haven't found a match yet
            if library_buttons:
                logger.info("Falling back to checking all buttons in library section")

                for element in library_buttons:
                    try:
                        # Get text and content-desc
                        content_desc = element.get_attribute("content-desc") or ""
                        element_text = element.text or ""

                        # If no direct text, look at child text elements
                        if not element_text:
                            try:
                                child_texts = element.find_elements(
                                    AppiumBy.CLASS_NAME, "android.widget.TextView"
                                )
                                for child in child_texts:
                                    try:
                                        if child.text:
                                            element_text += " " + child.text
                                    except:
                                        continue
                                element_text = element_text.strip()
                            except:
                                pass

                        # Log what we're checking
                        logger.info(f"Checking button: content-desc='{content_desc}', text='{element_text}'")

                        # Check for any kind of match
                        matched = False
                        match_reason = ""

                        # Try with _title_match function which has advanced matching logic
                        if content_desc and self._title_match(content_desc, book_title):
                            matched = True
                            match_reason = "title_match on content_desc"
                        elif element_text and self._title_match(element_text, book_title):
                            matched = True
                            match_reason = "title_match on text"

                        # If we found a match, return it
                        if matched:
                            logger.info(f"Found book match: {match_reason}")

                            # Create book info
                            book_info = {"title": book_title}

                            # Extract info from content-desc if available
                            if content_desc:
                                parts = content_desc.split(",")
                                if len(parts) > 0:
                                    book_info["title"] = parts[0].strip()
                                if len(parts) > 1:
                                    book_info["author"] = parts[1].strip()

                            logger.info(f"Found matching book: {book_info}")
                            return element, element, book_info
                    except Exception as e:
                        logger.debug(f"Error checking button in library section: {e}")
                        continue

            # We've tried specific ways to find the book in the library section
            # If nothing has worked, try a final sweeping check of all library elements
            logger.info("Trying one final pass through all library section elements")

            for element in library_section_elements:
                try:
                    # Get text and content-desc
                    content_desc = element.get_attribute("content-desc") or ""
                    element_text = element.text or ""

                    # Skip elements with no text or content-desc
                    if not content_desc and not element_text:
                        continue

                    # Check for simple substring match first
                    if content_desc and book_title.lower() in content_desc.lower():
                        logger.info(f"Found substring match in content-desc: '{content_desc}'")
                        book_info = {"title": book_title}
                        return element, element, book_info
                    elif element_text and book_title.lower() in element_text.lower():
                        logger.info(f"Found substring match in text: '{element_text}'")
                        book_info = {"title": book_title}
                        return element, element, book_info
                except Exception as e:
                    logger.debug(f"Error in final element check: {e}")
                    continue

            # No match found in library section
            logger.info("No matching book found in 'In your library' section")
            self._exit_search_mode()
            return None

        except Exception as e:
            logger.error(f"Error searching for book: {e}")
            traceback.print_exc()
            self._exit_search_mode()
            return None

    def _exit_search_mode(self):
        """Exit search mode and return to library view."""
        try:
            logger.info("Exiting search mode")

            # Try hardware back button as it's the most reliable
            self.driver.press_keycode(4)  # Android back button
            time.sleep(1)
            return True

        except Exception as e:
            logger.error(f"Error exiting search mode: {e}")
            return False
