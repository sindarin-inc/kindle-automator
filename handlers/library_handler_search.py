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
from views.common.scroll_strategies import SmartScroller
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
        # Initialize the smart scroller
        self.scroller = SmartScroller(driver)

    def _title_match(self, title1: str, title2: str) -> bool:
        """
        Check if titles match exactly.
        """
        if not title1 or not title2:
            return False

        # Use exact matching
        if title1 == title2:
            logger.info("Exact match found")
            return True

        return False

    def _check_book_visible_on_screen(self, book_title: str):
        """Check if a book is already visible on the current screen without scrolling.

        Args:
            book_title (str): The title of the book to check for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            logger.info(f"Checking if '{book_title}' is visible on current screen")

            # Store a matched title element and info for fallback if we can't find the button right away
            matched_title_element = None
            matched_title_text = None

            # Find all text elements
            title_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")

            if not title_elements:
                logger.info("No text elements found on current screen")
                return None

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
            logger.error(f"Error checking if book is visible on screen: {e}", exc_info=True)
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

            # Save list of available titles
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
            logger.error(f"Error in partial book matching: {e}", exc_info=True)
            traceback.print_exc()
            return None, None, None

    def _process_search_results(self, book_title: str):
        """Process search results and find the book in the 'In your library' section.

        Args:
            book_title (str): The title of the book to search for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            # Wait for search results to load
            logger.info("Waiting for search results to load...")

            # Wait specifically for "In your library" text to appear
            if not self._wait_for_in_library_section():
                logger.warning("Timeout waiting for 'In your library' section to load")
                # Still continue in case it appears later

            # Check for "Search instead for" button and click it if present
            self._click_search_instead_for_if_present()

            # Find section headers and determine boundaries
            in_library_info, results_from_info = self._locate_section_headers()
            in_library_y, results_from_y = self._determine_library_bounds(in_library_info, results_from_info)

            # Do a quick initial scan for the book before waiting for more elements
            # This helps avoid unnecessary delays when the book is immediately visible
            button_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.Button")
            for button in button_elements:
                try:
                    content_desc = button.get_attribute("content-desc") or ""
                    if content_desc and book_title.lower() in content_desc.lower():
                        logger.info(f"Found book immediately via content-desc: '{content_desc}'")
                        # Verify it's in the library section by checking for "In your library" text
                        text_elements = self.driver.find_elements(
                            AppiumBy.CLASS_NAME, "android.widget.TextView"
                        )
                        for text_elem in text_elements:
                            if "In your library" in self._element_text(text_elem):
                                logger.info(
                                    "Confirmed 'In your library' section is present - proceeding with quick match"
                                )
                                book_info = self._parse_book_info_from_content_desc(content_desc, book_title)
                                return button, button, book_info
                except:
                    continue

            # Check if 'In your library' section is missing
            in_library_section, in_library_y = in_library_info
            if not in_library_section:
                logger.info("Could not find 'In your library' section on first attempt")

                # Extended wait and retry
                if self._wait_until(
                    lambda driver: driver.find_elements(
                        AppiumBy.XPATH,
                        "//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'in your library')]",
                    ),
                    timeout=3,
                ):
                    # Try to find headers again
                    in_library_info, results_from_info = self._locate_section_headers()
                    in_library_y, results_from_y = self._determine_library_bounds(
                        in_library_info, results_from_info
                    )

                    in_library_section, in_library_y = in_library_info
                    if not in_library_section:
                        logger.info("Still could not find 'In your library' section after retry")
                        store_page_source(self.driver.page_source, "in_your_library_not_found")
                        self._exit_search_mode()
                        return None
                else:
                    logger.info("Timeout waiting for 'In your library' section")
                    store_page_source(self.driver.page_source, "in_your_library_not_found")
                    self._exit_search_mode()
                    return None

            # Log all text elements for debugging
            self._log_all_text_elements()

            # Check for no results in library section
            if self._check_no_results_in_library(in_library_y, results_from_y):
                logger.info("No results found in library section")
                self._exit_search_mode()
                return None

            # Find buttons in the library section
            logger.info("Searching specifically for elements in the 'In your library' section")
            buttons, buttons_with_content = self._find_buttons_in_library(in_library_y, results_from_y)

            # First, try exact match in content-desc
            result = self._match_book_by_exact_content_desc(buttons_with_content, book_title)
            if result[0]:
                return result

            # Try relaxed matching on buttons with content-desc
            if buttons_with_content:
                result = self._match_book_by_relaxed_content_desc(buttons_with_content, book_title)
                if result[0]:
                    return result

            # Try matching in generic buttons
            if buttons:
                result = self._match_book_in_generic_buttons(buttons, book_title)
                if result[0]:
                    return result

            # Final sweep of all elements in library section
            logger.info("Trying one final pass through all library section elements")
            all_elements = self.driver.find_elements(AppiumBy.XPATH, "//*")
            library_elements = []
            for el in all_elements:
                if self._within_vertical_bounds(el, in_library_y + 50, results_from_y):
                    library_elements.append(el)

            result = self._final_sweep_over_elements(library_elements, book_title)
            if result[0]:
                return result

            # No match found in library section
            logger.info("No matching book found in 'In your library' section")
            self._exit_search_mode()
            return None

        except Exception as e:
            logger.error(f"Error processing search results: {e}", exc_info=True)
            traceback.print_exc()
            self._exit_search_mode()
            return None

    def search_for_book(self, book_title: str):
        """Use the search box to find a book by title.

        This implementation avoids complex XPath expressions.

        Args:
            book_title (str): The title of the book to search for

        Returns:
            tuple or None: (parent_container, button, book_info) if found, None otherwise
        """
        try:
            # Check if already in search mode
            search_element, current_query = self._is_already_in_search_mode()
            if search_element:
                # We're already in search mode
                if current_query.strip().lower() == book_title.strip().lower():
                    logger.info(f"Already in search results for '{book_title}', processing existing results")
                    return self._process_search_results(book_title)
                else:
                    # Update search query
                    if self._update_search_query(book_title):
                        # Wait for search results
                        self._wait_for_in_library_section()
                        return self._process_search_results(book_title)

            # Not in search mode - submit new search
            if self._submit_search(book_title):
                # Wait for search results
                self._wait_for_in_library_section()
                return self._process_search_results(book_title)
            else:
                logger.error("Failed to submit search", exc_info=True)
                self._exit_search_mode()
                return None

        except Exception as e:
            logger.error(f"Error searching for book: {e}", exc_info=True)
            traceback.print_exc()
            self._exit_search_mode()
            return None

    def _exit_search_mode(self):
        """Exit search mode and return to library view."""
        try:
            logger.info("Exiting search mode")

            # Try to find and click the back/up button in the search interface
            for strategy, locator in SEARCH_BACK_BUTTON_IDENTIFIERS:
                try:
                    back_button = self.driver.find_element(strategy, locator)
                    if back_button and back_button.is_displayed():
                        logger.info(f"Found search back button using {strategy}: {locator}")
                        back_button.click()
                        logger.info("Clicked search back button")
                        # Wait for library view to appear
                        wait = WebDriverWait(self.driver, 5)
                        try:
                            wait.until(
                                lambda driver: (
                                    driver.find_elements(
                                        AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                                    )
                                    or driver.find_elements(
                                        AppiumBy.ID, "com.amazon.kindle:id/library_list_view"
                                    )
                                )
                            )
                        except TimeoutException:
                            logger.warning("Timeout waiting for library view after clicking back")
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error clicking back button with {strategy}: {e}")
                    continue

            # If no back button was found or clickable, log the issue
            logger.warning("No search back button found, cannot exit search mode via UI")

            # Store page source and screenshot
            store_page_source(self.driver.page_source, "search_exit_failure")
            screenshot_path = os.path.join(self.screenshots_dir, "search_exit_failure.png")
            self.driver.save_screenshot(screenshot_path)

            return False

        except Exception as e:
            logger.error(f"Error exiting search mode: {str(e)[:100]}", exc_info=True)
            return False

    def _check_store_results_for_book(self, book_title: str):
        """Check if the book appears in the Kindle store results section.

        Args:
            book_title (str): The title of the book to check for

        Returns:
            bool: True if book found in store results, False otherwise
        """
        try:
            # Look for book title in store results section
            buttons = self.driver.find_elements(AppiumBy.XPATH, "//android.widget.Button[@content-desc]")

            for button in buttons:
                try:
                    content_desc = button.get_attribute("content-desc")
                    if content_desc and book_title.lower() in content_desc.lower():
                        logger.info(f"Found book in store results: {content_desc}")
                        return True
                except:
                    continue

            # Also check TextView elements for the title
            text_elements = self.driver.find_elements(
                AppiumBy.XPATH, f"//android.widget.TextView[@text='{book_title}']"
            )
            if text_elements:
                logger.info(f"Found book title in TextView elements")
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking store results: {e}", exc_info=True)
            return False

    # === Helper Methods Shared by Both Flows ===

    def _wait_until(self, predicate, timeout=3, poll=0.3):
        """Generic WebDriverWait wrapper that centralizes polling/timeout logic."""
        try:
            wait = WebDriverWait(self.driver, timeout, poll_frequency=poll)
            return wait.until(predicate)
        except TimeoutException:
            return None

    def _element_text(self, el):
        """Safe .text/get_attribute('text') getter with fallback ''."""
        try:
            return el.text or el.get_attribute("text") or ""
        except:
            return ""

    def _find_clickable_parent(self, el, max_levels=3):
        """Walks up the DOM and returns first element with clickable='true'."""
        current = el
        for _ in range(max_levels):
            try:
                parent = current.find_element(AppiumBy.XPATH, "./..")
                if parent.get_attribute("clickable") == "true":
                    return parent
                current = parent
            except:
                break
        return None

    def _within_vertical_bounds(self, el, top, bottom):
        """True if an element's y is between two pixel bounds."""
        try:
            y = el.location["y"]
            return top <= y < bottom
        except:
            return False

    def _parse_book_info_from_content_desc(self, content_desc, requested_title):
        """Splits 'Title, Author' strings and returns a dict {title, author} (falls back to requested_title)."""
        book_info = {"title": requested_title}
        if not content_desc:
            return book_info

        parts = content_desc.split(",")
        if len(parts) > 0:
            book_info["title"] = parts[0].strip()
        if len(parts) > 1:
            book_info["author"] = parts[1].strip()
        return book_info

    def _log_all_text_elements(self):
        """Debug helper that dumps every TextView string once per search."""
        try:
            text_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            texts = []
            for el in text_elements:
                text = self._element_text(el)
                if text:
                    texts.append(text)
            logger.info(f"All text on page: {texts}")
        except Exception as e:
            logger.debug(f"Error logging text elements: {e}")

    # === search_for_book Decomposition ===

    def _is_already_in_search_mode(self):
        """Detect existing search payload via id=search_query."""
        try:
            search_query_element = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
            current_query = self._element_text(search_query_element)
            return search_query_element, current_query
        except NoSuchElementException:
            return None, None

    def _update_search_query(self, book_title):
        """Clear + type new query + press Enter."""
        search_element, current_query = self._is_already_in_search_mode()
        if not search_element:
            return False

        if current_query.strip().lower() == book_title.strip().lower():
            logger.info(f"Already searching for '{book_title}'")
            return True

        logger.info(f"Clearing existing search '{current_query}' and searching for '{book_title}'")
        search_element.clear()
        search_element.send_keys(book_title)
        self.driver.press_keycode(66)  # Android keycode for Enter
        logger.info("Pressed Enter key to submit search")

        # Check for search results within 1 second
        search_results_found = self._wait_until(
            lambda driver: driver.find_elements(AppiumBy.XPATH, "//*[contains(@text, 'In your library')]"),
            timeout=3,
        )

        if not search_results_found:
            logger.info(
                "No search results found within 1 second, refocusing search box and pressing Enter again"
            )
            # Refocus on the search field
            search_element = self._get_search_field()
            if search_element:
                search_element.click()
                self.driver.press_keycode(66)  # Android keycode for Enter
                logger.info("Pressed Enter key again to submit search")

        return True

    def _open_search_box(self):
        """Locate and click the search box (multiple locator strategies)."""
        try:
            search_box = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_box")
            search_box.click()
            return True
        except:
            pass

        # Try finding by class name and content-desc
        linear_layouts = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.LinearLayout")
        for layout in linear_layouts:
            try:
                if layout.get_attribute("resource-id") == "com.amazon.kindle:id/search_box":
                    logger.info("Found search box by class name and resource-id")
                    layout.click()
                    return True
            except:
                continue

        logger.error("Could not find search box", exc_info=True)
        return False

    def _get_search_field(self):
        """Return the EditText used for typing."""
        try:
            return self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
        except:
            # Try finding by class name
            edit_texts = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.EditText")
            if edit_texts:
                logger.info("Found search input field by class name")
                return edit_texts[0]
        return None

    def _submit_search(self, book_title):
        """Delegates to _update_search_query (or initial typing) then waits for 'In your library'."""
        # First check if already in search mode
        if self._update_search_query(book_title):
            return True

        # Otherwise, open search box and type
        if not self._open_search_box():
            return False

        # Wait for search field to appear
        self._wait_until(
            EC.presence_of_element_located((AppiumBy.ID, "com.amazon.kindle:id/search_query")), timeout=3
        )

        search_field = self._get_search_field()
        if not search_field:
            logger.error("Could not find search input field", exc_info=True)
            return False

        search_field.clear()
        search_field.send_keys(book_title)
        logger.info(f"Entered book title in search field: '{book_title}'")

        # Press Enter
        self.driver.press_keycode(66)
        logger.info("Pressed Enter key to submit search")

        # Check for search results within 3 seconds because sometimes the results pop in
        search_results_found = self._wait_until(
            lambda driver: driver.find_elements(AppiumBy.XPATH, "//*[contains(@text, 'In your library')]"),
            timeout=3,
        )

        if not search_results_found:
            logger.info(
                "No search results found within 1 second, refocusing search box and pressing Enter again"
            )
            # Refocus on the search field
            if search_field:
                search_field.click()
                # Check what's currently in the search field
                current_text = self._element_text(search_field)
                logger.info(f"Current search field content: '{current_text}'")

                # If the field is empty or doesn't match our book title, re-enter it
                if not current_text or current_text != book_title:
                    logger.info(
                        f"Search field content doesn't match expected title, re-entering: '{book_title}'"
                    )
                    search_field.clear()
                    search_field.send_keys(book_title)

                self.driver.press_keycode(66)  # Android keycode for Enter
                logger.info("Pressed Enter key again to submit search")

        return True

    # === _process_search_results Decomposition ===

    def _wait_for_in_library_section(self):
        """Wait up to n seconds for any text containing 'In your library'."""
        return self._wait_until(
            lambda driver: driver.find_elements(AppiumBy.XPATH, "//*[contains(@text, 'In your library')]"),
            timeout=3,
        )

    def _click_search_instead_for_if_present(self):
        """Detect & click that suggestion and re-wait for results."""
        try:
            text_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            for element in text_elements:
                text = self._element_text(element)
                if "Search instead for" in text:
                    logger.info(f"Found 'Search instead for' suggestion: '{text}'")
                    if element.get_attribute("clickable") == "true":
                        element.click()
                        logger.info("Clicked 'Search instead for' button")
                        return True
                    else:
                        parent = self._find_clickable_parent(element, max_levels=1)
                        if parent:
                            parent.click()
                            logger.info("Clicked parent of 'Search instead for' text")
                            return True
            return False
        except Exception as e:
            logger.debug(f"Error checking for 'Search instead for' button: {e}")
            return False

    def _locate_section_headers(self):
        """Returns (in_library_el, results_from_el) and their y coords."""
        in_library_section = None
        in_library_y = 0
        results_from_section = None
        results_from_y = float("inf")

        text_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
        for element in text_elements:
            try:
                text = self._element_text(element)
                if not text:
                    continue

                if "in your library" in text.lower():
                    in_library_section = element
                    in_library_y = element.location["y"]
                    logger.info(f"Found 'In your library' section at y={in_library_y}")
                elif "results from" in text.lower():
                    results_from_section = element
                    results_from_y = element.location["y"]
                    logger.info(f"Found 'Results from' section at y={results_from_y}")
            except Exception as e:
                logger.debug(f"Error checking section headers: {e}")
                continue

        return (in_library_section, in_library_y), (results_from_section, results_from_y)

    def _determine_library_bounds(self, in_el_info, results_el_info):
        """Fallback to screen height when results_el absent."""
        _, in_library_y = in_el_info
        _, results_from_y = results_el_info

        if results_from_y == float("inf"):
            screen_size = self.driver.get_window_size()
            results_from_y = screen_size["height"] - 100
            logger.info("Using screen height as boundary for library section")

        return in_library_y, results_from_y

    def _check_no_results_in_library(self, in_y, results_y):
        """Consolidates all heuristics that decide 'no results'."""
        # Similar logic to original, but extracted
        text_elements = self.driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
        in_library_texts = []

        for element in text_elements:
            if self._within_vertical_bounds(element, in_y + 50, results_y):
                text = self._element_text(element)
                if text:
                    in_library_texts.append(text)

                    # Check for no results messages
                    if any(
                        phrase in text.lower() for phrase in ["no results", "not found", "empty", "no books"]
                    ):
                        logger.info(f"Found 'No results' message: {text}")
                        return True

        # Check if library section is empty
        if not in_library_texts:
            library_height = results_y - in_y
            if library_height < 150:
                logger.info("Library section appears to be empty (small height)")
                return True

        # Check for clickable elements in library section
        clickable_count = 0
        all_elements = self.driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
        for el in all_elements:
            if self._within_vertical_bounds(el, in_y, results_y):
                clickable_count += 1

        if clickable_count == 0:
            logger.info("No clickable elements in library section")
            return True

        return False

    def _find_buttons_in_library(self, in_y, results_y):
        """Collects buttons & elements within library bounds."""
        buttons = []
        buttons_with_content = []

        all_elements = self.driver.find_elements(AppiumBy.XPATH, "//*")
        for element in all_elements:
            try:
                if self._within_vertical_bounds(element, in_y + 50, results_y):
                    class_name = element.get_attribute("class") or ""
                    if "Button" in class_name:
                        buttons.append(element)
                        content_desc = element.get_attribute("content-desc") or ""
                        if content_desc:
                            buttons_with_content.append((element, content_desc))
                            logger.info(
                                f"Found button with content-desc at y={element.location['y']}: '{content_desc}'"
                            )
            except Exception as e:
                logger.debug(f"Error collecting buttons: {e}")

        return buttons, buttons_with_content

    def _match_book_by_exact_content_desc(self, buttons_with_content, book_title):
        """Direct substring / _title_match on content-desc."""
        for element, content_desc in buttons_with_content:
            if book_title.lower() in content_desc.lower():
                logger.info(f"Found exact match in content-desc: '{content_desc}'")
                book_info = self._parse_book_info_from_content_desc(content_desc, book_title)
                return element, element, book_info
        return None, None, None

    def _match_book_by_relaxed_content_desc(self, buttons_with_content, book_title):
        """Word-set & prefix matching."""
        for element, content_desc in buttons_with_content:
            # Word-level matching
            book_parts = book_title.lower().split()
            content_parts = content_desc.lower().split()
            matches = set(book_parts) & set(content_parts)

            if len(matches) >= max(1, len(book_parts) // 2):
                logger.info(f"Found word-level match: {matches}")
                book_info = self._parse_book_info_from_content_desc(content_desc, book_title)
                return element, element, book_info

            # Prefix matching
            strong_match = True
            for book_word in book_parts:
                if len(book_word) < 3:
                    continue

                found = any(book_word[:3] == cw[:3] for cw in content_parts if len(cw) >= 3)
                if not found:
                    strong_match = False
                    break

            if strong_match:
                logger.info(f"Found prefix match: '{content_desc}'")
                book_info = self._parse_book_info_from_content_desc(content_desc, book_title)
                return element, element, book_info

        return None, None, None

    def _match_book_in_generic_buttons(self, buttons, book_title):
        """Checks any button even w/o content-desc."""
        for button in buttons:
            try:
                content_desc = button.get_attribute("content-desc") or ""
                button_text = self._element_text(button)

                # Check child text elements
                if not button_text:
                    child_texts = button.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
                    for child in child_texts:
                        text = self._element_text(child)
                        if text:
                            button_text += " " + text
                    button_text = button_text.strip()

                # Try title match
                if (content_desc and self._title_match(content_desc, book_title)) or (
                    button_text and self._title_match(button_text, book_title)
                ):
                    logger.info("Found match in generic button")
                    book_info = self._parse_book_info_from_content_desc(content_desc, book_title)
                    return button, button, book_info
            except Exception as e:
                logger.debug(f"Error checking button: {e}")

        return None, None, None

    def _final_sweep_over_elements(self, elements, book_title):
        """Catch-all scan over every element in bounds."""
        for element in elements:
            try:
                content_desc = element.get_attribute("content-desc") or ""
                element_text = self._element_text(element)

                if not content_desc and not element_text:
                    continue

                if (content_desc and book_title.lower() in content_desc.lower()) or (
                    element_text and book_title.lower() in element_text.lower()
                ):
                    logger.info("Found match in final sweep")
                    book_info = {"title": book_title}
                    return element, element, book_info
            except Exception as e:
                logger.debug(f"Error in final sweep: {e}")

        return None, None, None
