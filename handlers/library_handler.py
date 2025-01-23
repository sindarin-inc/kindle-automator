from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from views.core.logger import logger
from views.library.view_strategies import (
    LIBRARY_VIEW_IDENTIFIERS,
    GRID_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
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
                    return True
                except:
                    continue
            return False
        except:
            return False

    def _is_list_view(self):
        """Check if currently in list view"""
        try:
            logger.info("Checking if in list view...")
            logger.info("\n=== PAGE SOURCE START ===")
            logger.info(self.driver.page_source)
            logger.info("=== PAGE SOURCE END ===\n")

            for strategy, locator in LIST_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"List view detected via {strategy}: {locator}")
                    return True
                except Exception as e:
                    logger.debug(f"List view strategy failed - {strategy}: {locator} - {e}")
                    continue
            logger.info("Not in list view")
            return False
        except Exception as e:
            logger.error(f"Error checking list view: {e}")
            return False

    def switch_to_list_view(self):
        """Switch to list view if not already in it"""
        try:
            if self._is_list_view():
                logger.info("Already in list view")
                return True

            # Find and click view options button
            view_options = None
            for strategy, locator in VIEW_OPTIONS_BUTTON_STRATEGIES:
                try:
                    view_options = self.driver.find_element(strategy, locator)
                    break
                except:
                    continue

            if not view_options:
                logger.error("Could not find view options button")
                return False

            view_options.click()
            logger.info("Clicked view options button")
            time.sleep(1)  # Wait for menu to appear

            # Find and click list view option
            list_option = None
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    list_option = self.driver.find_element(strategy, locator)
                    break
                except:
                    continue

            if not list_option:
                logger.error("Could not find list view option")
                # Try to close menu before returning
                self._close_menu()
                return False

            list_option.click()
            logger.info("Clicked list view option")
            time.sleep(1)  # Wait for view to change

            # Close the menu
            if not self._close_menu():
                logger.error("Failed to close menu")
                return False

            time.sleep(1)  # Wait for menu to close
            return self._is_list_view()
        except Exception as e:
            logger.error(f"Error switching to list view: {e}")
            # Try to close menu in case of error
            self._close_menu()
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
            list: A list of dictionaries containing book information with 'title' and 'author' keys.
        """
        logger.info("Getting book titles...")

        # First close view options menu if it's open
        if self._is_view_options_menu_open():
            logger.info("View options menu is open, closing it")
            self._close_menu()
            time.sleep(0.5)  # Wait for menu to close

        # Then check if we need to switch to list view
        if not self._is_list_view():
            logger.info("Not in list view, switching...")
            if not self.switch_to_list_view():
                logger.error("Failed to switch to list view")
                return []

        logger.info("\n=== PAGE SOURCE START ===")
        logger.info(self.driver.page_source)
        logger.info("=== PAGE SOURCE END ===\n")

        books = []
        try:
            # Find all book buttons in list view
            book_buttons = self.driver.find_elements(
                AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, 'Book')]"
            )
            for button in book_buttons:
                try:
                    # Get the title element
                    title_element = button.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                    )
                    title = title_element.text

                    # Get the author element
                    author_element = button.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_author"
                    )
                    author = author_element.text

                    books.append({"title": title, "author": author})
                    logger.info(f"- {title} by {author}")
                except Exception as e:
                    logger.debug(f"Error extracting book info: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error finding book elements: {e}")
            return []

        logger.info(f"Found {len(books)} books")
        if books:
            logger.info("Found books:")
            for book in books:
                logger.info(f"- {book}")

        return books

    def list_books(self):
        """List all books in the library"""
        # TODO: Implement book listing functionality
        pass

    def open_book(self, book_title):
        """Open a specific book by title"""
        # TODO: Implement book opening functionality
        pass
