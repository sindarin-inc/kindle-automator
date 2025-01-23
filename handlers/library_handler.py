from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from views.core.logger import logger
from views.library.view_strategies import (
    LIBRARY_VIEW_IDENTIFIERS,
    GRID_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
    BOOK_TITLE_IDENTIFIERS,
    BOOK_AUTHOR_IDENTIFIERS,
)
from views.library.interaction_strategies import (
    LIBRARY_TAB_STRATEGIES,
    VIEW_OPTIONS_BUTTON_STRATEGIES,
    LIST_VIEW_OPTION_STRATEGIES,
    BOOK_TITLE_STRATEGIES,
    MENU_CLOSE_STRATEGIES,
)
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES
from views.view_options.interaction_strategies import VIEW_OPTIONS_DONE_STRATEGIES
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS


class LibraryHandler:
    def __init__(self, driver):
        self.driver = driver

    def _get_tab_selection_strategies(self):
        """Generate strategies for detecting library tab selection state."""
        return [
            (
                AppiumBy.ANDROID_UIAUTOMATOR,
                'new UiSelector().descriptionContains("LIBRARY, Tab selected")',
            ),
            (
                AppiumBy.ID,
                "com.amazon.kindle:id/library_tab",
                {
                    "icon": (
                        AppiumBy.ID,
                        "com.amazon.kindle:id/icon",
                        "selected",
                        "true",
                    ),
                    "label": (
                        AppiumBy.ID,
                        "com.amazon.kindle:id/label",
                        "selected",
                        "true",
                    ),
                },
            ),
        ]

    def _is_library_tab_selected(self):
        """Check if the library tab is currently selected."""
        logger.info("Checking if library tab is selected...")

        for strategy in self._get_tab_selection_strategies():
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
                    self.driver.find_element(by, value)
                    logger.info(f"Found library tab with strategy: {by}")
                    return True
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue

        logger.info("Library tab is not selected")
        return False

    def _is_view_options_menu_open(self):
        """Check if the view options menu is currently open."""
        try:
            # Check for distinctive elements of the view options menu
            for strategy, locator in VIEW_OPTIONS_MENU_STATE_STRATEGIES:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"View options menu detected via {strategy}: {locator}")
                    return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Error checking view options menu state: {e}")
            return False

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

            # Try each strategy to find and click the library tab
            for strategy, locator in LIBRARY_TAB_STRATEGIES:
                try:
                    logger.info(f"Trying to find Library tab with strategy: {strategy}, locator: {locator}")
                    library_tab = self.driver.find_element(strategy, locator)
                    logger.info(f"Found Library tab using {strategy}")
                    library_tab.click()
                    logger.info("Clicked Library tab")

                    # Wait for library tab to be selected
                    logger.info("Waiting for library tab to be selected...")
                    WebDriverWait(self.driver, 10).until(lambda x: self._is_library_tab_selected())
                    logger.info("Library tab selected")
                    return True
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
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
                    logger.info(f"List view detected via {strategy}: {locator}")
                    return True
                except Exception as e:
                    logger.debug(f"List view strategy failed - {strategy}: {locator} - {e}")
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
            try:
                done_button = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"
                )
                done_button.click()
                logger.info("Clicked DONE button")
            except Exception as e:
                logger.error(f"Failed to click DONE button: {e}")
                return False

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
            except Exception as e:
                logger.error(f"Timed out waiting for list view: {e}")
                # Get page source for debugging
                logger.info("\n=== PAGE SOURCE AFTER VIEW SWITCH ===")
                logger.info(self.driver.page_source)
                logger.info("=== END PAGE SOURCE ===\n")
                return False

        except Exception as e:
            logger.error(f"Error switching to list view: {e}")
            return False

    def _close_menu(self):
        """Close any open menu by clicking outside or the done button"""
        logger.info("Attempting to close menu...")

        # First try view options specific strategies
        for strategy, locator in VIEW_OPTIONS_DONE_STRATEGIES:
            try:
                element = self.driver.find_element(strategy, locator)
                element.click()
                logger.info(f"Closed menu using {strategy}: {locator}")
                return True
            except Exception as e:
                logger.debug(f"Strategy {strategy} failed: {e}")
                continue

        # Fall back to general menu close strategies
        for strategy, locator in MENU_CLOSE_STRATEGIES:
            try:
                element = self.driver.find_element(strategy, locator)
                element.click()
                logger.info(f"Closed menu using fallback {strategy}: {locator}")
                return True
            except Exception as e:
                logger.debug(f"Fallback strategy {strategy} failed: {e}")
                continue

        logger.error("Failed to close menu with any strategy")
        return False

    def get_book_titles(self):
        """Get a list of books in the library.

        Returns:
            list[dict]: List of dictionaries containing book information with 'title' and 'author' keys.
        """
        try:
            # First close view options menu if it's open
            if self._is_view_options_menu_open():
                logger.info("View options menu is open, closing it")
                if not self._close_menu():
                    logger.error("Failed to close view options menu")
                    return []
                time.sleep(0.5)  # Wait for menu to close

            # Check current view type
            if self._is_grid_view():
                logger.info("Currently in grid view, switching to list view...")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    return []

            # Get page source for debugging
            logger.info("\n=== PAGE SOURCE START ===")
            logger.info(self.driver.page_source)
            logger.info("=== PAGE SOURCE END ===\n")

            books = []
            try:
                # Find all book title elements
                title_elements = []
                for strategy, locator in BOOK_TITLE_IDENTIFIERS:
                    try:
                        elements = self.driver.find_elements(strategy, locator)
                        if elements:
                            title_elements = elements
                            break
                    except Exception as e:
                        logger.debug(f"Failed to find titles with {strategy}: {e}")
                        continue

                # Find all author elements
                author_elements = []
                for strategy, locator in BOOK_AUTHOR_IDENTIFIERS:
                    try:
                        elements = self.driver.find_elements(strategy, locator)
                        if elements:
                            author_elements = elements
                            break
                    except Exception as e:
                        logger.debug(f"Failed to find authors with {strategy}: {e}")
                        continue

                # Pair up titles and authors
                for title_elem, author_elem in zip(title_elements, author_elements):
                    try:
                        title = title_elem.text
                        author = author_elem.text
                        if title and author:  # Only add if both are present
                            books.append({"title": title, "author": author})
                            logger.info(f"Found book: {title} by {author}")
                    except Exception as e:
                        logger.debug(f"Failed to get book info: {e}")
                        continue

            except Exception as e:
                logger.debug(f"Failed to find book elements: {e}")

            logger.info(f"Found {len(books)} books")
            if books:
                logger.info("Found books:")
                for book in books:
                    logger.info(f"- {book}")
            return books

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            return []

    def list_books(self):
        """List all books in the library"""
        # TODO: Implement book listing functionality
        pass

    def open_book(self, book_title):
        """Open a specific book by title"""
        # TODO: Implement book opening functionality
        pass

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
                        EC.presence_of_element_located((AppiumBy.CLASS_NAME, "android.webkit.WebView"))
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
