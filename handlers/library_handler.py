import logging
import os
import re
import time
import traceback
from typing import Dict, List, Optional, Tuple, Union

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from handlers.library_handler_scroll import LibraryHandlerScroll
from handlers.library_handler_search import LibraryHandlerSearch
from server.logging_config import store_page_source
from views.auth.interaction_strategies import LIBRARY_SIGN_IN_STRATEGIES
from views.auth.view_strategies import EMAIL_VIEW_IDENTIFIERS
from views.library.interaction_strategies import (
    GRID_VIEW_OPTION_STRATEGIES,
    LIBRARY_TAB_STRATEGIES,
    LIST_VIEW_OPTION_STRATEGIES,
    MENU_CLOSE_STRATEGIES,
    SAFE_TAP_AREAS,
    VIEW_OPTIONS_BUTTON_STRATEGIES,
)
from views.library.view_strategies import (
    BOOK_AUTHOR_IDENTIFIERS,
    BOOK_CONTAINER_RELATIONSHIPS,
    BOOK_METADATA_IDENTIFIERS,
    BOTTOM_NAV_IDENTIFIERS,
    CONTENT_DESC_STRATEGIES,
    DOWNLOAD_PROGRESS_BAR_IDENTIFIERS,
    GRID_VIEW_IDENTIFIERS,
    LIBRARY_ELEMENT_DETECTION_STRATEGIES,
    LIBRARY_TAB_CHILD_SELECTION_STRATEGIES,
    LIBRARY_TAB_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_IDENTIFIERS,
    LIBRARY_TAB_SELECTION_STRATEGIES,
    LIBRARY_VIEW_DETECTION_STRATEGIES,
    LIBRARY_VIEW_IDENTIFIERS,
    LIST_VIEW_IDENTIFIERS,
    READER_DRAWER_LAYOUT_IDENTIFIERS,
    VIEW_OPTIONS_DONE_BUTTON_STRATEGIES,
    VIEW_OPTIONS_MENU_STRATEGIES,
    WEBVIEW_IDENTIFIERS,
)
from views.reading.view_strategies import READING_VIEW_IDENTIFIERS
from views.view_options.interaction_strategies import VIEW_OPTIONS_DONE_STRATEGIES
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES

logger = logging.getLogger(__name__)


class LibraryHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

        # Initialize helper classes
        self.search_handler = LibraryHandlerSearch(driver)
        self.scroll_handler = LibraryHandlerScroll(driver, parent_handler=self)

    def _discover_and_save_library_preferences(self):
        """Discover the current library view state and save it to preferences.

        This is called when we detect the library is already in a certain state
        but we haven't saved those preferences yet.

        Note: We can only discover view_type without opening the dialog.
        group_by_series requires opening the Grid/List view dialog to check.
        """
        try:
            # Check if we're in list view
            if self._is_list_view():
                logger.info("Discovered library is in list view, saving preference")
                self.driver.automator.profile_manager.save_style_setting("view_type", "list")
            elif self._is_grid_view():
                logger.info("Discovered library is in grid view, saving preference")
                self.driver.automator.profile_manager.save_style_setting("view_type", "grid")

            # We cannot determine group_by_series without opening the dialog
            # Don't assume anything about it
            logger.info(
                "Cannot determine group_by_series without opening dialog - not setting this preference"
            )

        except Exception as e:
            logger.warning(f"Error discovering and saving library preferences: {e}", exc_info=True)

    def pull_to_refresh(self):
        """Perform pull-to-refresh gesture by swiping from top 1/3 to bottom 1/3 of screen.

        Captures page source 0.2s after swipe starts to identify refresh indicator XML.

        Returns:
            bool: True if pull-to-refresh was successfully performed, False otherwise
        """
        try:
            # Get screen dimensions
            screen_size = self.driver.get_window_size()
            screen_width = screen_size["width"]
            screen_height = screen_size["height"]

            # Calculate swipe coordinates (from top 1/3 to bottom 1/3)
            start_x = screen_width // 2  # Center horizontally
            start_y = screen_height // 3  # Top 1/3
            end_x = screen_width // 2  # Stay centered horizontally
            end_y = (screen_height * 2) // 3  # Bottom 1/3 (2/3 down from top)

            # Start the swipe gesture
            self.driver.swipe(start_x, start_y, end_x, end_y, duration=800)

            # Capture page source 0.2s after swipe starts to see refresh indicator
            time.sleep(0.2)
            try:
                timestamp = int(time.time())
                page_source_filename = f"pull_refresh_indicator_{timestamp}.xml"
                page_source_path = os.path.join(self.screenshots_dir, page_source_filename)

                page_source = self.driver.page_source
                with open(page_source_path, "w", encoding="utf-8") as f:
                    f.write(page_source)

                # Also take a screenshot to see the visual state
                screenshot_filename = f"pull_refresh_indicator_{timestamp}.png"
                screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
                self.driver.save_screenshot(screenshot_path)

            except Exception as e:
                logger.warning(f"Could not capture page source during refresh: {e}")

            # Wait for refresh to complete (give it a moment to settle)
            time.sleep(1.5)

            return True

        except Exception as e:
            logger.warning(f"Error performing pull-to-refresh: {e}", exc_info=True)
            store_page_source(self.driver, "pull_refresh_error")
            return False

    def click_filter_button_and_count_books(self):
        """Click the filter button and count the number of books shown in the filter modal.

        Returns:
            int: Sum of Read and Unread counts from the filter modal, or None if failed
        """
        try:
            from views.library.interaction_strategies import FILTER_BUTTON_STRATEGIES

            # Try to find and click the filter button
            filter_button_clicked = False
            for strategy, locator in FILTER_BUTTON_STRATEGIES:
                try:
                    filter_button = self.driver.find_element(strategy, locator)
                    if filter_button.is_displayed():
                        filter_button.click()
                        logger.info("Successfully clicked filter button")
                        filter_button_clicked = True
                        break
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.warning(f"Error clicking filter button with strategy {strategy}: {e}")

            if not filter_button_clicked:
                logger.warning("Could not find or click filter button")
                return None

            # Wait a moment for the filter modal to appear
            time.sleep(1.0)

            # Try to find the Read and Unread counts in the filter modal
            try:
                # Take a screenshot for debugging
                timestamp = int(time.time())
                screenshot_filename = f"filter_modal_{timestamp}.png"
                screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
                self.driver.save_screenshot(screenshot_path)

                # Also save page source
                store_page_source(self.driver.page_source, f"filter_modal_{timestamp}")

                # Extract Read and Unread counts
                read_count = 0
                unread_count = 0

                # First try content-desc attributes
                try:
                    # Find the button with Read in content-desc
                    read_button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, 'red:')]"
                    )
                    content_desc = read_button.get_attribute("content-desc")
                    if content_desc:
                        import re

                        match = re.search(r"red:\s*(\d+)", content_desc)
                        if match:
                            read_count = int(match.group(1))
                            logger.info(f"Found Read count from content-desc: {read_count}")
                except Exception as e:
                    logger.debug(f"Could not find Read count from content-desc: {e}")

                try:
                    # Find the button with Unread in content-desc
                    unread_button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, 'Unread:')]"
                    )
                    content_desc = unread_button.get_attribute("content-desc")
                    if content_desc:
                        import re

                        match = re.search(r"Unread:\s*(\d+)", content_desc)
                        if match:
                            unread_count = int(match.group(1))
                            logger.info(f"Found Unread count from content-desc: {unread_count}")
                except Exception as e:
                    logger.debug(f"Could not find Unread count from content-desc: {e}")

                # If that didn't work fully, try the structured approach
                if read_count == 0:
                    try:
                        # Find the Read text element
                        read_text_element = self.driver.find_element(
                            AppiumBy.XPATH,
                            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/checkable_item_text_view' and @text='Read']",
                        )
                        # Find its parent LinearLayout
                        parent = read_text_element.find_element(AppiumBy.XPATH, "..")
                        # Find the count TextView within the same parent
                        count_element = parent.find_element(
                            AppiumBy.XPATH,
                            ".//android.widget.TextView[@resource-id='com.amazon.kindle:id/checkable_item_count']",
                        )
                        count_text = count_element.text
                        if count_text:
                            import re

                            match = re.search(r"\((\d+)\)", count_text)
                            if match:
                                read_count = int(match.group(1))
                                logger.info(f"Found Read count from structure: {read_count}")
                    except Exception as e:
                        logger.debug(f"Could not find Read count using structured approach: {e}")

                if unread_count == 0:
                    try:
                        # Find the Unread text element
                        unread_text_element = self.driver.find_element(
                            AppiumBy.XPATH,
                            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/checkable_item_text_view' and @text='Unread']",
                        )
                        # Find its parent LinearLayout
                        parent = unread_text_element.find_element(AppiumBy.XPATH, "..")
                        # Find the count TextView within the same parent
                        count_element = parent.find_element(
                            AppiumBy.XPATH,
                            ".//android.widget.TextView[@resource-id='com.amazon.kindle:id/checkable_item_count']",
                        )
                        count_text = count_element.text
                        if count_text:
                            import re

                            match = re.search(r"\((\d+)\)", count_text)
                            if match:
                                unread_count = int(match.group(1))
                                logger.info(f"Found Unread count from structure: {unread_count}")
                    except Exception as e:
                        logger.debug(f"Could not find Unread count using structured approach: {e}")

                # Calculate total book count
                book_count = read_count + unread_count
                logger.info(f"Total book count (Read + Unread): {book_count} = {read_count} + {unread_count}")

                # Close the filter modal by clicking the DONE button
                try:
                    # Try to find the DONE button (visible in the filter modal)
                    done_button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[@text='DONE']"
                    )
                    done_button.click()
                    logger.info("Closed filter modal using DONE button")
                except NoSuchElementException:
                    try:
                        # Try as a Button element
                        done_button = self.driver.find_element(
                            AppiumBy.XPATH, "//android.widget.Button[@text='DONE']"
                        )
                        done_button.click()
                        logger.info("Closed filter modal using DONE button")
                    except:
                        # If no close button, tap outside the modal
                        screen_size = self.driver.get_window_size()
                        self.driver.tap([(screen_size["width"] // 10, screen_size["height"] // 10)])
                        logger.info("Closed filter modal by tapping outside")

                time.sleep(0.5)

                return book_count if book_count > 0 else None

            except Exception as e:
                logger.error(f"Error counting books in filter modal: {e}", exc_info=True)
                return None

        except Exception as e:
            logger.error(f"Error in click_filter_button_and_count_books: {e}", exc_info=True)
            return None

    def _is_library_view_preferences_correctly_set(self):
        """Check if library view preferences are correctly set to list view with group_by_series=false.

        If preferences haven't been set yet (return None), we need to discover and save them.

        Returns:
            bool: True if preferences are correctly set, False otherwise
        """
        try:
            cached_view_type = self.driver.automator.profile_manager.get_style_setting(
                "view_type", default=None
            )
            cached_group_by_series = self.driver.automator.profile_manager.get_style_setting(
                "group_by_series", default=None
            )

            logger.info(
                f"Cached preferences check: view_type={cached_view_type}, group_by_series={cached_group_by_series}"
            )

            # If we have no cached preferences, we need to discover the current state
            if cached_view_type is None or cached_group_by_series is None:
                logger.info("No cached preferences found, will need to discover current state")
                return False

            return cached_view_type == "list" and cached_group_by_series is False
        except Exception as e:
            logger.warning(f"Error checking library view preferences: {e}", exc_info=True)
            return False

    def apply_library_settings(self, view_type="list", group_by_series=False):
        """Apply library view settings (view type and group by series).

        This is a reusable method that ensures the library is configured with the specified settings.

        Args:
            view_type: Either "list" or "grid" view
            group_by_series: Whether to group books by series

        Returns:
            bool: True if settings were applied successfully, False otherwise
        """
        try:
            # Check current preferences
            cached_view_type = self.driver.automator.profile_manager.get_style_setting(
                "view_type", default=None
            )
            cached_group_by_series = self.driver.automator.profile_manager.get_style_setting(
                "group_by_series", default=None
            )

            # If preferences are already correct, no need to open dialog
            if cached_view_type == view_type and cached_group_by_series == group_by_series:
                logger.info(
                    f"Library settings already correct: view_type={view_type}, group_by_series={group_by_series}"
                )
                return True

            # Open the grid/list dialog
            if not self.open_grid_list_view_dialog(force_open=True):
                logger.error("Failed to open grid/list view dialog", exc_info=True)
                return False

            # Now apply the settings in the dialog
            dialog_open = self._is_grid_list_view_dialog_open()
            if not dialog_open:
                logger.error("Dialog not open after attempting to open it", exc_info=True)
                return False

            # Set group by series switch
            try:
                group_by_series_switch = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/lib_menu_switch"
                )
                if group_by_series_switch.is_displayed():
                    is_checked = group_by_series_switch.get_attribute("checked") == "true"
                    logger.info(f"Group by Series switch currently checked: {is_checked}")

                    if is_checked != group_by_series:
                        # Toggle the switch
                        group_by_series_switch.click()
                        logger.info(f"Toggled Group by Series to: {group_by_series}")
                        time.sleep(0.5)

                    # Record the setting
                    self.driver.automator.profile_manager.save_style_setting(
                        "group_by_series", group_by_series
                    )
            except NoSuchElementException:
                logger.warning("Group by Series switch not found")

            # Click the appropriate view option
            if view_type == "list":
                strategies = LIST_VIEW_OPTION_STRATEGIES
            else:
                strategies = GRID_VIEW_OPTION_STRATEGIES

            view_clicked = False
            for strategy, locator in strategies:
                try:
                    option = self.driver.find_element(strategy, locator)
                    if option.is_displayed():
                        option.click()
                        logger.info(f"Clicked {view_type} view option")
                        view_clicked = True
                        time.sleep(0.5)
                        break
                except NoSuchElementException:
                    continue

            if not view_clicked:
                logger.error(f"Failed to click {view_type} view option", exc_info=True)
                return False

            # Record the view type setting
            self.driver.automator.profile_manager.save_style_setting("view_type", view_type)

            # Click DONE to close the dialog
            done_clicked = False
            for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                try:
                    done_button = self.driver.find_element(strategy, locator)
                    if done_button.is_displayed():
                        done_button.click()
                        logger.info("Clicked DONE button")
                        done_clicked = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue

            if not done_clicked:
                logger.error("Failed to click DONE button", exc_info=True)
                return False

            # Verify dialog is closed
            if self._is_grid_list_view_dialog_open():
                logger.error("Dialog still open after clicking DONE", exc_info=True)
                return False

            logger.info(
                f"Successfully applied library settings: view_type={view_type}, group_by_series={group_by_series}"
            )
            return True

        except Exception as e:
            logger.warning(f"Error applying library settings: {e}", exc_info=True)
            return False

    def _is_library_tab_selected(self):
        """Check if the library tab is currently selected."""

        # First try the selection strategies
        for strategy in LIBRARY_TAB_SELECTION_IDENTIFIERS:
            try:
                if len(strategy) == 3:  # Complex strategy with child elements
                    by, value, child_checks = strategy
                    tab = self.driver.find_element(by, value)

                    # Check child elements
                    for child_by, child_value, attr, expected in child_checks.values():
                        child = tab.find_element(child_by, child_value)
                        if child.get_attribute(attr) == expected:
                            return True
                else:  # Simple strategy
                    by, value = strategy
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
                        return True
            except NoSuchElementException:
                continue

        # If we're here, check if we're in the library view by looking for library-specific elements
        try:
            for strategy, locator in LIBRARY_VIEW_DETECTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found library view element: {locator}")
                        # Also check for selected child elements
                        try:
                            # Check both child elements are selected
                            all_selected = True
                            for (
                                child_strategy,
                                child_locator,
                            ) in LIBRARY_TAB_CHILD_SELECTION_STRATEGIES:
                                child = self.driver.find_element(child_strategy, child_locator)
                                if not child.is_displayed():
                                    all_selected = False
                                    break
                            if all_selected:
                                logger.info("Found library tab child elements selected")
                                return True
                        except:
                            pass
                except:
                    continue
        except Exception as e:
            logger.debug(f"Library view check failed: {e}")

        logger.info("Library tab is not selected")
        return False

    def _is_view_options_menu_open(self):
        """Check if the view options menu is open."""
        try:
            self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/view_options_menu")
            return True
        except:
            return False

    def _open_grid_list_view_dialog_internal(self):
        """Internal method to open the Grid/List view dialog by clicking the view options button.

        This is a shared method used by both open_grid_list_view_dialog and switch_to_list_view.

        Returns:
            bool: True if dialog was opened successfully, False otherwise
        """
        try:
            # Check if dialog is already open
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is already open")
                return True

            # Before trying to open dialog, make sure we're in library view
            if not self._is_library_tab_selected():
                logger.info("Not in library view, navigating to library first")
                if not self.navigate_to_library():
                    logger.error("Failed to navigate to library", exc_info=True)
                    return False

            # Click view options button to open the dialog
            for strategy, locator in VIEW_OPTIONS_BUTTON_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    button.click()
                    logger.info(f"Clicked view options button using {strategy}: {locator}")
                    time.sleep(1)  # Wait for dialog animation

                    # Verify dialog opened
                    if self._is_grid_list_view_dialog_open():
                        logger.info("Successfully opened Grid/List view dialog")
                        return True

                except Exception as e:
                    logger.debug(f"Failed to click view options button with strategy {strategy}: {e}")
                    continue

            logger.error("Failed to open Grid/List view dialog with any strategy", exc_info=True)
            return False

        except Exception as e:
            logger.warning(f"Error opening Grid/List view dialog: {e}", exc_info=True)
            return False

    def open_grid_list_view_dialog(self, force_open=False):
        """Open the Grid/List view dialog to access settings like 'Group by Series'.

        Args:
            force_open: If True, open the dialog even if preferences appear to be set
                       This is useful when we need to verify/set group_by_series

        Returns:
            bool: True if dialog was opened successfully, False otherwise
        """
        try:
            # Check if both preferences are already correctly set (unless force_open is True)
            if not force_open and self._is_library_view_preferences_correctly_set():
                logger.info("Library preferences already correctly set, dialog not needed")
                return True

            # Check specifically if we need to open dialog for group_by_series
            cached_group_by_series = self.driver.automator.profile_manager.get_style_setting(
                "group_by_series"
            )
            if cached_group_by_series is None:
                logger.info("group_by_series is not set, need to open dialog to check/set it")
            else:
                logger.info("Opening Grid/List view dialog")

            # Use the internal method to open the dialog
            return self._open_grid_list_view_dialog_internal()

        except Exception as e:
            logger.warning(f"Error in open_grid_list_view_dialog: {e}", exc_info=True)
            return False

    def _is_grid_list_view_dialog_open(self):
        """Check if the Grid/List view selection dialog is open.

        This dialog appears when view options is clicked and shows Grid, List, and Collections choices.
        """
        try:
            # Check for multiple identifiers to ensure we're specifically in the Grid/List dialog
            identifiers_found = 0

            # Check for VIEW_OPTIONS_DONE_BUTTON_STRATEGIES (DONE button)
            for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found Grid/List dialog element: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue
                except (InvalidSessionIdException, WebDriverException) as e:
                    if "A session is either terminated or not started" in str(e):
                        logger.warning("Session terminated, stopping dialog check", exc_info=True)
                        return False
                    raise

            # Check for LIST_VIEW_OPTION_STRATEGIES
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found List view option: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue
                except (InvalidSessionIdException, WebDriverException) as e:
                    if "A session is either terminated or not started" in str(e):
                        logger.warning("Session terminated, stopping dialog check", exc_info=True)
                        return False
                    raise

            # Check for GRID_VIEW_OPTION_STRATEGIES
            for strategy, locator in GRID_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found Grid view option: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue
                except (InvalidSessionIdException, WebDriverException) as e:
                    if "A session is either terminated or not started" in str(e):
                        logger.warning("Session terminated, stopping dialog check", exc_info=True)
                        return False
                    raise

            # Also check for specific view type header text
            try:
                header = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/view_type_header")
                if header.is_displayed() and header.text == "View":
                    logger.info("Found View type header with text 'View'")
                    identifiers_found += 1
            except NoSuchElementException:
                pass
            except (InvalidSessionIdException, WebDriverException) as e:
                if "A session is either terminated or not started" in str(e):
                    logger.warning("Session terminated, stopping dialog check", exc_info=True)
                    return False
                raise

            # If we found at least 2 of the identifying elements, we're confident it's the Grid/List dialog
            is_dialog_open = identifiers_found >= 2

            return is_dialog_open
        except Exception as e:
            logger.error(f"Error checking for Grid/List view dialog: {e}", exc_info=True)
            return False

    def _find_bottom_navigation(self):
        """Find the bottom navigation bar."""
        for strategy, locator in BOTTOM_NAV_IDENTIFIERS:
            try:
                nav = self.driver.find_element(strategy, locator)
                logger.info(f"Found bottom navigation using {strategy}")
                return nav
            except Exception as e:
                continue
        return None

    def navigate_to_library(self):
        """Navigate to the library tab"""
        try:
            # Check if Grid/List view dialog is open and handle it first
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is open, handling it first")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                    return False
                time.sleep(0.5)  # Wait for dialog to close

            # Check if view options menu is open and close it if needed
            if self._is_view_options_menu_open():
                logger.info("View options menu is open, closing it first")
                if not self._close_menu():
                    logger.error("Failed to close view options menu", exc_info=True)
                    return False
                time.sleep(0.5)  # Wait for menu to close

            # First check if library tab is already selected
            if self._is_library_tab_selected():
                return True

            # Try to find the library tab directly using identifiers
            for strategy, locator in LIBRARY_TAB_IDENTIFIERS:
                try:
                    library_tab = self.driver.find_element(strategy, locator)
                    library_tab.click()
                    logger.info("Clicked Library tab")
                    time.sleep(1)  # Wait for tab switch animation
                    # Verify we're in library view
                    if self._is_library_tab_selected():
                        return True
                except Exception as e:
                    continue

            # Try to find the bottom navigation bar
            nav = self._find_bottom_navigation()
            if nav:
                logger.info("Found bottom navigation bar")
                # Try each library tab strategy within the navigation bar
                for strategy, locator in LIBRARY_TAB_STRATEGIES:
                    try:
                        library_tab = nav.find_element(strategy, locator)
                        logger.info(f"Found Library tab using {strategy}")
                        library_tab.click()
                        logger.info("Clicked Library tab")
                        time.sleep(1)  # Wait for tab switch animation
                        # Verify we're in library view
                        if self._is_library_tab_selected():
                            logger.info("Successfully switched to library tab")
                            return True
                    except Exception as e:
                        logger.debug(f"Strategy {strategy} failed: {e}")
                        continue

            # If we're here, try checking if we're already in the library view
            for strategy, locator in LIBRARY_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found library view element: {locator}")
                        return True
                except:
                    continue

            logger.error("Failed to find Library tab with any strategy", exc_info=True)
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "failed_library_tab")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "failed_library_tab.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error navigating to library: {e}", exc_info=True)
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "library_navigation_error")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "library_navigation_error.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}", exc_info=True)
            return False

    def navigate_to_more_settings(self):
        """Navigate to the More tab/settings"""
        try:
            from views.more.interaction_strategies import MORE_TAB_STRATEGIES

            logger.info("Navigating to More tab...")

            # Check if more tab is already selected
            if self._is_more_tab_selected():
                logger.info("More tab is already selected")
                return True

            # Try to find and click the More tab
            for strategy, locator in MORE_TAB_STRATEGIES:
                try:
                    more_tab = self.driver.find_element(strategy, locator)
                    if more_tab.is_displayed():
                        more_tab.click()
                        logger.info(f"Clicked More tab using {strategy}")
                        time.sleep(1)  # Wait for tab switch animation

                        # Verify we're in More settings view
                        if self._is_more_tab_selected():
                            logger.info("Successfully switched to More tab")
                            return True
                except Exception as e:
                    logger.debug(f"Strategy {strategy} failed: {e}")
                    continue

            logger.error("Failed to find More tab with any strategy", exc_info=True)
            return False

        except Exception as e:
            logger.error(f"Error navigating to More settings: {e}", exc_info=True)
            return False

    def navigate_from_more_to_library(self):
        """Navigate from More tab back to Library tab"""
        try:
            logger.info("Navigating from More tab to Library tab...")

            # First check if we're actually in More tab
            if not self._is_more_tab_selected():
                logger.warning("Not in More tab, checking if we're already in Library")
                if self._is_library_tab_selected():
                    return True

            # Navigate to library using existing method
            return self.navigate_to_library()

        except Exception as e:
            logger.error(f"Error navigating from More to Library: {e}", exc_info=True)
            return False

    def sync_in_more_tab(self):
        """Click the Sync Now button in the More tab and wait for completion"""
        try:
            from views.more.interaction_strategies import (
                SYNC_BUTTON_STRATEGIES,
                SYNC_PROGRESS_INDICATORS,
                SYNC_STATUS_STRATEGIES,
            )

            logger.info("Looking for Sync Now button...")

            # Find and click the sync button
            sync_clicked = False
            for strategy, locator in SYNC_BUTTON_STRATEGIES:
                try:
                    sync_button = self.driver.find_element(strategy, locator)
                    if sync_button.is_displayed():
                        sync_button.click()
                        logger.info("Clicked Sync Now button")
                        sync_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"Sync button strategy {strategy} failed: {e}")
                    continue

            if not sync_clicked:
                logger.error("Could not find Sync Now button", exc_info=True)
                return False

            # Wait for sync to start
            time.sleep(1)

            # Monitor sync progress
            sync_complete = False
            max_wait_time = 15  # Maximum 15 seconds for sync (as expected by user)
            start_time = time.time()
            logger.info(f"Waiting up to {max_wait_time} seconds for sync to complete...")

            while time.time() - start_time < max_wait_time:
                try:
                    # Always check sync status first to see if it's complete
                    for strategy, locator in SYNC_STATUS_STRATEGIES:
                        try:
                            status_element = self.driver.find_element(strategy, locator)
                            if status_element.is_displayed():
                                status_text = status_element.text
                                logger.info(f"Sync status: {status_text}")

                                # Check if sync is complete (status shows "Last synced" with recent time)
                                if "Last synced" in status_text:
                                    logger.info("Sync completed successfully")
                                    sync_complete = True
                                    break
                        except Exception as e:
                            logger.debug(f"Error checking sync status with strategy {strategy}: {e}")
                            continue

                    if sync_complete:
                        break

                    # Check if sync is still in progress
                    sync_in_progress = False
                    for strategy, locator in SYNC_PROGRESS_INDICATORS:
                        try:
                            progress_element = self.driver.find_element(strategy, locator)
                            if progress_element.is_displayed():
                                sync_in_progress = True
                                logger.info("Sync is in progress...")
                                break
                        except Exception as e:
                            logger.debug(f"Error checking sync progress with strategy {strategy}: {e}")
                            continue

                    # Log current wait time
                    elapsed_time = time.time() - start_time
                    logger.debug(f"Sync wait time: {elapsed_time:.1f}s / {max_wait_time}s")

                    time.sleep(1)  # Check every second

                except Exception as e:
                    logger.error(f"Unexpected error in sync monitoring loop: {e}", exc_info=True)
                    # Don't break the loop on errors, just continue
                    time.sleep(1)

            # Log final status
            final_elapsed = time.time() - start_time
            if not sync_complete:
                logger.warning(
                    f"Sync may not have completed within timeout period (waited {final_elapsed:.1f}s)"
                )
                # Store diagnostic information for sync timeout
                try:
                    from server.logging_config import store_page_source

                    store_page_source(self.driver.page_source, "sync_timeout_failure")
                    logger.warning("Stored page source for sync timeout analysis")
                except Exception as e:
                    logger.error(f"Failed to store diagnostic info for sync timeout: {e}", exc_info=True)
            else:
                logger.info(f"Sync completed after {final_elapsed:.1f}s")

            logger.info(f"sync_in_more_tab() finishing, returning: {sync_complete}")
            return sync_complete

        except Exception as e:
            logger.error(f"Error during sync: {e}", exc_info=True)
            # Store diagnostic information for sync exception
            try:
                from server.logging_config import store_page_source

                store_page_source(self.driver.page_source, "sync_exception_failure")
                logger.error("Stored page source for sync exception analysis", exc_info=True)
            except Exception as diag_error:
                logger.error(
                    f"Failed to store diagnostic info for sync exception: {diag_error}", exc_info=True
                )
            logger.info("sync_in_more_tab() caught exception, returning False")
            return False

    def _is_more_tab_selected(self):
        """Check if More tab is currently selected"""
        try:
            from views.more.view_strategies import MORE_TAB_SELECTION_IDENTIFIERS

            for strategy, locator in MORE_TAB_SELECTION_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.debug(f"More tab is selected (found via {strategy})")
                        return True
                except:
                    continue

            return False
        except Exception as e:
            logger.error(f"Error checking if More tab is selected: {e}", exc_info=True)
            return False

    def _is_grid_view(self):
        """Check if currently in grid view"""
        try:
            # First check for grid view identifiers
            for strategy, locator in GRID_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    logger.info(f"Grid view detected via {strategy}: {locator}")
                    return True
                except NoSuchElementException:
                    # Expected failure, continue silently without logging
                    continue
                except StaleElementReferenceException:
                    # UI state changed, continue silently without logging
                    continue
                except Exception as e:
                    # Only log unexpected errors
                    logger.debug(f"Unexpected error checking grid view with {strategy}: {e}")
                    continue

            # Second check - look for GridView element directly
            try:
                self.driver.find_element(AppiumBy.CLASS_NAME, "android.widget.GridView")
                logger.info("Grid view detected via GridView class")
                return True
            except NoSuchElementException:
                # Expected failure, don't log
                pass
            except Exception as e:
                # Only log unexpected errors
                logger.debug(f"Unexpected error checking for GridView class: {e}")

            return False
        except Exception as e:
            logger.error(f"Error checking grid view: {e}", exc_info=True)
            return False

    def _is_list_view(self):
        """Check if currently in list view"""
        try:
            for strategy, locator in LIST_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    return True
                except NoSuchElementException:
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking list view: {e}", exc_info=True)
            return False

    def _detect_collapsed_series(self):
        """Detect if there are collapsed series items in the current library view.

        Returns:
            bool: True if collapsed series are detected, False otherwise
        """
        try:
            # Look for series indicators - either in content-desc or the series count badge
            # Pattern 1: content-desc contains "Series: [name], X volumes"
            series_elements = self.driver.find_elements(
                AppiumBy.XPATH, "//android.widget.RelativeLayout[contains(@content-desc, 'Series:')]"
            )
            if series_elements:
                logger.info(f"Found {len(series_elements)} collapsed series items via content-desc")
                return True

            # Pattern 2: Look for the series count badge (e.g., "3" indicating 3 books in series)
            # This appears as a TextView with resource-id "middle_right_label"
            series_badges = self.driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/middle_right_label")
            if series_badges:
                # Check if any of these badges contain numbers (indicating series count)
                for badge in series_badges:
                    try:
                        text = badge.text
                        if text and text.isdigit():
                            logger.info(f"Found series badge with count: {text}")
                            return True
                    except Exception:
                        continue

            return False
        except Exception as e:
            logger.debug(f"Error detecting collapsed series: {e}")
            return False

    def _should_check_series_grouping(self):
        """Check if it's been more than 24 hours since the last series group check.

        Returns:
            bool: True if we should check (and potentially disable) series grouping
        """
        try:
            from datetime import datetime, timedelta, timezone

            # Get the last check time from the database
            library_settings = self.driver.automator.profile_manager.get_library_settings()
            if not library_settings:
                # No settings yet, should check
                return True

            last_check = library_settings.last_series_group_check
            if not last_check:
                # Never checked before
                return True

            # Check if it's been more than 24 hours
            now = datetime.now(timezone.utc)
            time_since_check = now - last_check
            should_check = time_since_check > timedelta(hours=24)

            if not should_check:
                logger.debug(
                    f"Last series group check was {time_since_check.total_seconds() / 3600:.1f} hours ago, skipping"
                )

            return should_check
        except Exception as e:
            logger.warning(f"Error checking series grouping time: {e}")
            # On error, default to checking
            return True

    def _handle_series_grouping_if_needed(self):
        """Check for collapsed series and disable grouping if needed.

        This should be called when scrolling through the library and collapsed
        series are detected.
        """
        try:
            # First check if we should even check (24 hour limit)
            if not self._should_check_series_grouping():
                return

            # Check if there are collapsed series visible
            if not self._detect_collapsed_series():
                return

            logger.info("Collapsed series detected, checking if group by series needs to be disabled")

            # Open the grid/list dialog to check and disable series grouping
            if not self.open_grid_list_view_dialog(force_open=True):
                logger.warning("Failed to open Grid/List dialog to check series grouping")
                return

            # Handle the dialog to ensure series grouping is off
            if self.handle_grid_list_view_dialog():
                logger.info("Successfully handled Grid/List dialog to disable series grouping")

                # Update the last check time in the database
                from datetime import datetime, timezone

                from database.repositories.user_repository import UserRepository
                from server.utils.request_utils import get_sindarin_email

                sindarin_email = get_sindarin_email(self.driver.automator)
                if sindarin_email:
                    with UserRepository() as repo:
                        library_settings = repo.get_or_create_library_settings(sindarin_email)
                        library_settings.last_series_group_check = datetime.now(timezone.utc)
                        repo.commit()
                        logger.info("Updated last_series_group_check timestamp in database")
            else:
                logger.warning("Failed to handle Grid/List dialog to disable series grouping")

        except Exception as e:
            logger.warning(f"Error handling series grouping: {e}")

    def _is_in_series_collection_view(self):
        """Check if we're in an expanded series/collection view.

        This view appears when clicking on a grouped series/collection item.
        It shows "You have X volumes in this series" and lists the books in the series.

        Returns:
            bool: True if in series/collection view, False otherwise
        """
        try:
            # Check for the series ownership count field
            # "You have X volumes in this series/collection"
            try:
                series_count = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/series_ownership_count_field"
                )
                if series_count and series_count.is_displayed():
                    text = series_count.text
                    if "volumes" in text.lower() and (
                        "series" in text.lower() or "collection" in text.lower()
                    ):
                        logger.info(f"Detected series/collection view: {text}")
                        return True
            except NoSuchElementException:
                pass

            # Also check for "View all items in series/collection" link
            try:
                view_all_link = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/series_see_all_items_in_store"
                )
                if view_all_link and view_all_link.is_displayed():
                    text = view_all_link.text
                    if "view all items" in text.lower():
                        logger.info(f"Detected series/collection view via 'View all items' link")
                        return True
            except NoSuchElementException:
                pass

            # Additional check: Look for text patterns in any TextView
            try:
                elements = self.driver.find_elements(
                    AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'volumes in this')]"
                )
                if elements:
                    logger.info("Detected series/collection view via text pattern")
                    return True
            except Exception:
                pass

            # Enhanced check: Look for back button in library view (indicates series/collection)
            # Regular library view doesn't have a back/navigate up button
            try:
                # First confirm we're in library view
                self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")

                # Now check for back button which only appears in series/collection views
                try:
                    back_button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Navigate up']"
                    )
                    if back_button and back_button.is_displayed():
                        logger.info("Detected series/collection view via back button in library")
                        return True
                except NoSuchElementException:
                    pass
            except NoSuchElementException:
                # Not in library view, can't be series view
                pass

            return False
        except Exception as e:
            logger.debug(f"Error checking for series/collection view: {e}")
            return False

    def _wait_for_view_transition(self, timeout=2):
        """Wait for a view transition to complete by checking for stable UI elements.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            bool: True if transition completed, False if timeout
        """
        try:

            def check_stable_view(driver):
                # Check if we're in a stable known view (library, series, or reading)
                try:
                    # Check for library view
                    driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                    return True
                except NoSuchElementException:
                    pass

                try:
                    # Check for series view
                    driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/series_ownership_count_field")
                    return True
                except NoSuchElementException:
                    pass

                try:
                    # Check for reading view
                    driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/reader_drawer_layout")
                    return True
                except NoSuchElementException:
                    pass

                return False

            WebDriverWait(self.driver, timeout).until(check_stable_view)
            return True
        except TimeoutException:
            return False

    def _exit_series_collection_view(self):
        """Exit from the series/collection expanded view back to the library.

        Returns:
            bool: True if successfully exited, False otherwise
        """
        try:
            if not self._is_in_series_collection_view():
                logger.debug("Not in series/collection view, nothing to exit")
                return True

            logger.info("In series/collection view, attempting to navigate back")

            # Look for the back/navigate up button
            back_button = None

            # Try finding by content-desc "Navigate up"
            try:
                back_button = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Navigate up']"
                )
            except NoSuchElementException:
                # Try finding by class and position (usually top-left)
                try:
                    back_button = self.driver.find_element(AppiumBy.CLASS_NAME, "android.widget.ImageButton")
                except NoSuchElementException:
                    pass

            if back_button and back_button.is_displayed():
                logger.info("Found back button, clicking to exit series view")
                back_button.click()

                # Wait for the view to transition out of series view
                try:

                    def not_in_series_view(driver):
                        return not self._is_in_series_collection_view()

                    WebDriverWait(self.driver, 2).until(not_in_series_view)
                    logger.info("Successfully exited series/collection view")

                    # Now handle the series grouping if needed
                    self._handle_series_grouping_if_needed()
                    return True
                except TimeoutException:
                    logger.warning("Still in series view after clicking back")
                    return False
            else:
                logger.warning("Could not find back button in series view")
                # Try using device back button as fallback
                try:
                    self.driver.back()

                    # Wait for transition
                    def not_in_series_view(driver):
                        return not self._is_in_series_collection_view()

                    WebDriverWait(self.driver, 2).until(not_in_series_view)
                    logger.info("Successfully exited series view using device back")
                    self._handle_series_grouping_if_needed()
                    return True
                except TimeoutException:
                    logger.warning("Still in series view after device back")
                    return False
                except Exception as e:
                    logger.error(f"Failed to use device back button: {e}")
                    return False

        except Exception as e:
            logger.error(f"Error exiting series/collection view: {e}")
            return False

    def _is_in_search_interface(self):
        """
        Check if we're currently in the search results interface.
        This can be misidentified as the library view because it uses some of the same elements.
        """
        try:
            # Check for search-specific elements
            search_indicators = 0

            # Check for search query input field
            try:
                search_query = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_query")
                if search_query and search_query.is_displayed():
                    search_indicators += 1
                    logger.info("Found search query input field")
            except NoSuchElementException:
                pass

            # Check for search recycler view
            try:
                search_results = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/search_recycler_view"
                )
                if search_results and search_results.is_displayed():
                    search_indicators += 1
                    logger.info("Found search results recycler view")
            except NoSuchElementException:
                pass

            # Check for sections like "In your library" and "Results from Kindle"
            try:
                sections = self.driver.find_elements(
                    AppiumBy.ID, "com.amazon.kindle:id/search_store_progress_bar"
                )
                if sections and len(sections) > 0:
                    search_indicators += 1
                    logger.info(f"Found {len(sections)} search section headers")
            except NoSuchElementException:
                pass

            # Check for "Navigate up" button which is present in search view
            try:
                up_button = self.driver.find_element(
                    AppiumBy.XPATH,
                    "//android.widget.ImageButton[@content-desc='Navigate up']",
                )
                if up_button and up_button.is_displayed():
                    search_indicators += 1
                    logger.info("Found Navigate up button in search view")
            except NoSuchElementException:
                pass

            # We need at least 2 indicators to be confident we're in search view
            is_search = search_indicators >= 2
            return is_search

        except Exception as e:
            logger.error(f"Error checking for search interface: {e}", exc_info=True)
            return False

    def switch_to_list_view(self):
        """Switch to list view if not already in it"""
        try:
            # First check cached preferences to see if we should already be in list view
            if self._is_library_view_preferences_correctly_set():
                logger.info(
                    "Library settings already set to list view with group_by_series=false in cache, "
                    "assuming we're already in list view and skipping all checks"
                )
                return True

            # If cache doesn't indicate list view, proceed with normal checks
            # First check if we're in search interface
            if self._is_in_search_interface():
                logger.info("Detected we're in search interface, exiting search mode first")
                if not self.search_handler._exit_search_mode():
                    logger.error("Failed to exit search mode", exc_info=True)
                    return False
                logger.info("Successfully exited search mode")
                time.sleep(1)  # Give UI time to settle
                return True  # Return after exiting search mode to avoid attempting grid/list view toggle

            # Check if the Grid/List view dialog is already open
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is already open, handling it directly")
                return self.handle_grid_list_view_dialog()

            # Check if we're already in list view
            if self._is_list_view():
                # Check if we need to discover and save preferences
                cached_view_type = self.driver.automator.profile_manager.get_style_setting("view_type")
                if cached_view_type is None:
                    logger.info("Already in list view but no cached preferences, discovering and saving")
                    self._discover_and_save_library_preferences()
                return True

            # Force update state machine to ensure we're recognized as being in LIBRARY state
            # This is crucial to prevent auth_handler from trying to enter email after view changes
            logger.info("Ensuring state machine recognizes LIBRARY state before view change")
            self.driver.automator.state_machine.update_current_state()

            # If we're in grid view, we need to open the view options menu
            if self._is_grid_view():
                logger.info("Currently in grid view, switching to list view")

                # Check again for search interface (could be misdetected as grid view)
                if self._is_in_search_interface():
                    logger.info(
                        "Actually in search interface even though grid view was detected, exiting search mode"
                    )
                    if not self.search_handler._exit_search_mode():
                        logger.error("Failed to exit search mode", exc_info=True)
                        return False
                    logger.info("Successfully exited search mode")
                    time.sleep(1)  # Give UI time to settle
                    return True

                # Use the shared internal method to open the dialog
                if not self._open_grid_list_view_dialog_internal():
                    logger.error("Failed to open Grid/List view dialog", exc_info=True)
                    return False

                # After clicking the view options button, check if Grid/List dialog is open
                # and handle it with the dedicated method
                if self._is_grid_list_view_dialog_open():
                    logger.info("Grid/List view dialog opened, handling it")
                    if not self.handle_grid_list_view_dialog():
                        logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                        return False

                    # After handling the dialog, verify we're in list view
                    if self._is_list_view():
                        logger.info("Successfully switched to list view after handling dialog")
                        return True
                    else:
                        logger.error("Still not in list view after handling dialog", exc_info=True)
                        return False

                # If we didn't detect the Grid/List dialog, continue with the old approach
                # (This is a fallback for backward compatibility)

                # Verify the menu is open
                menu_open = False
                try:
                    for strategy, locator in VIEW_OPTIONS_MENU_STATE_STRATEGIES:
                        try:
                            self.driver.find_element(strategy, locator)
                            menu_open = True
                            logger.info(f"View options menu is open, detected via {strategy}: {locator}")
                            break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking if menu is open: {e}")

                if not menu_open:
                    logger.error("View options menu did not open properly", exc_info=True)
                    return False

                # Click list view option
                list_option_clicked = False
                for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                    try:
                        option = self.driver.find_element(strategy, locator)
                        option.click()
                        logger.info(f"Clicked list view option using {strategy}: {locator}")
                        time.sleep(1)  # Increased wait for selection to register
                        list_option_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click list view option with strategy {strategy}: {e}")
                        continue

                if not list_option_clicked:
                    logger.error("Failed to click list view option", exc_info=True)
                    return False

                # Click DONE button
                done_clicked = False
                for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                    try:
                        done_button = self.driver.find_element(strategy, locator)
                        done_button.click()
                        logger.info(f"Clicked DONE button using {strategy}: {locator}")
                        done_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click DONE button with strategy {strategy}: {e}")
                        continue

                if not done_clicked:
                    logger.error("Failed to click DONE button", exc_info=True)
                    return False

                # Wait longer for list view to appear
                try:
                    logger.info("Waiting for list view to appear...")
                    WebDriverWait(self.driver, 5).until(
                        lambda x: any(
                            self.try_find_element(x, strategy, locator)
                            for strategy, locator in LIST_VIEW_IDENTIFIERS
                        )
                    )
                    logger.info("Successfully switched to list view")

                    # Force update the state machine to recognize we're still in LIBRARY state
                    # This prevents auth_handler from trying to enter email
                    if hasattr(self.driver, "automator") and self.driver.automator:
                        automator = self.driver.automator
                        if hasattr(automator, "state_machine") and automator.state_machine:
                            logger.info("Forcing state update after view change to prevent auth confusion")
                            automator.state_machine.update_current_state()

                    # Add slight delay to ensure UI is settled
                    time.sleep(1)
                    return True
                except TimeoutException:
                    logger.error("Timed out waiting for list view", exc_info=True)
                    # Get page source for debugging
                    filepath = store_page_source(self.driver.page_source, "list_view_timeout")
                    logger.info(f"Stored list view timeout page source at: {filepath}")
                    return False
            else:
                # Check if we're in the Grid/List view dialog state
                if self._is_grid_list_view_dialog_open():
                    logger.info("Detected Grid/List view dialog, handling it directly")
                    if self.handle_grid_list_view_dialog():
                        logger.info("Successfully handled Grid/List view dialog")
                        # After handling the dialog, verify we're in list view
                        if self._is_list_view():
                            logger.info("Successfully switched to list view after handling dialog")
                            return True
                        else:
                            logger.warning("Still not in list view after handling dialog, will retry")
                            # Try once more with the standard approach
                            return self.switch_to_list_view()
                    else:
                        logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                        return False
                else:
                    logger.warning("Neither in grid view nor list view, unable to determine current state")
                    filepath = store_page_source(self.driver.page_source, "unknown_view_state")
                    logger.info(f"Stored unknown view state page source at: {filepath}")
                    return False

        except Exception as e:
            logger.error(f"Error switching to list view: {e}", exc_info=True)
            traceback.print_exc()
            return False

    def try_find_element(self, driver, strategy, locator):
        """Safe wrapper to find element without raising exception"""
        try:
            return driver.find_element(strategy, locator) is not None
        except:
            return False

    def _close_menu(self):
        """Close any open menu by tapping outside."""
        try:
            # Try each safe tap area
            for x, y in SAFE_TAP_AREAS:
                try:
                    self.driver.tap([(x, y)])
                    logger.info(f"Tapped at ({x}, {y}) to close menu")
                    time.sleep(0.5)  # Wait for menu animation
                    if not self._is_view_options_menu_open():
                        return True
                except Exception as e:
                    logger.debug(f"Failed to tap at ({x}, {y}): {e}")
                    continue

            # If tapping didn't work, try clicking dismiss buttons
            for strategy, locator in MENU_CLOSE_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    button.click()
                    logger.info(f"Clicked dismiss button using {strategy}")
                    return True
                except Exception as e:
                    logger.debug(f"Failed to click dismiss button: {e}")
                    continue

            return False
        except Exception as e:
            logger.error(f"Error closing menu: {e}", exc_info=True)
            return False

    def handle_grid_list_view_dialog(self):
        """Handle the Grid/List view selection dialog by selecting List view and turning off Group by Series.

        This method is called when we detect that the Grid/List view selection dialog is open,
        which can happen when trying to open a book or navigate in the library view.

        Returns:
            bool: True if successfully handled the dialog, False otherwise.
        """
        try:
            logger.info("Handling Grid/List view selection dialog...")

            # First check if the dialog is actually open
            if not self._is_grid_list_view_dialog_open():
                return True  # Return True since there's no dialog to handle

            # Turn off Group by Series switch first
            group_by_series_handled = False
            try:
                # Find the Group by Series switch
                group_by_series_switch = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/lib_menu_switch"
                )
                if group_by_series_switch.is_displayed():
                    # Check if it's currently enabled (checked=true)
                    is_checked = group_by_series_switch.get_attribute("checked") == "true"
                    logger.info(f"Group by Series switch found, currently checked: {is_checked}")

                    if is_checked:
                        # Click to turn it off
                        group_by_series_switch.click()
                        logger.info("Turned off Group by Series switch")
                        time.sleep(0.5)  # Wait for the change to register
                        group_by_series_handled = True
                    else:
                        logger.info("Group by Series switch is already off")
                        group_by_series_handled = True

                    # Record the state in profile manager
                    self.driver.automator.profile_manager.save_style_setting("group_by_series", False)
                else:
                    logger.warning("Group by Series switch not displayed")
            except NoSuchElementException:
                logger.debug("Group by Series switch not found")
            except (InvalidSessionIdException, WebDriverException) as e:
                if "A session is either terminated or not started" in str(e):
                    logger.error("Session terminated while handling Group by Series switch", exc_info=True)
                    return False
                logger.error(f"Error handling Group by Series switch: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error handling Group by Series switch: {e}", exc_info=True)

            # Click the List view option to ensure consistent view
            list_option_clicked = False
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    list_option = self.driver.find_element(strategy, locator)
                    if list_option.is_displayed():
                        logger.info(f"Clicking List view option using {strategy}={locator}")
                        list_option.click()
                        list_option_clicked = True
                        time.sleep(0.5)  # Short wait for selection to register
                        break
                except NoSuchElementException:
                    logger.debug(f"List view option not found with {strategy}={locator}")
                    continue
                except Exception as e:
                    logger.error(f"Error clicking List view option: {e}", exc_info=True)
                    continue

            # If we couldn't click the List view option, it might already be selected or not found
            if not list_option_clicked:
                logger.warning(
                    "Could not click List view option, it might already be selected or not available"
                )

            # Update the view_type in profile preferences if list was clicked
            if list_option_clicked:
                self.driver.automator.profile_manager.save_style_setting("view_type", "list")

            # Now click the DONE button to close the dialog
            done_clicked = False

            # Try the VIEW_OPTIONS_DONE_BUTTON_STRATEGIES
            for strategy, locator in VIEW_OPTIONS_DONE_BUTTON_STRATEGIES:
                try:
                    done_button = self.driver.find_element(strategy, locator)
                    if done_button.is_displayed():
                        logger.info(f"Clicking DONE button using {strategy}={locator}")
                        done_button.click()
                        done_clicked = True
                        time.sleep(1)  # Wait for dialog to close
                        break
                except NoSuchElementException:
                    logger.debug(f"DONE button not found with {strategy}={locator}")
                    continue
                except Exception as e:
                    logger.error(f"Error clicking DONE button: {e}", exc_info=True)
                    continue

            # If we still couldn't click the DONE button, try VIEW_OPTIONS_DONE_STRATEGIES
            # which include touch_outside
            if not done_clicked:
                for strategy, locator in VIEW_OPTIONS_DONE_STRATEGIES:
                    try:
                        done_button = self.driver.find_element(strategy, locator)
                        if done_button.is_displayed():
                            logger.info(
                                f"Clicking DONE button using alternative strategy {strategy}={locator}"
                            )
                            done_button.click()
                            done_clicked = True
                            time.sleep(1)  # Wait for dialog to close
                            break
                    except NoSuchElementException:
                        logger.debug(f"DONE button not found with alternative strategy {strategy}={locator}")
                        continue
                    except Exception as e:
                        logger.error(
                            f"Error clicking DONE button with alternative strategy: {e}", exc_info=True
                        )
                        continue

            # If we still couldn't click the DONE button, try the alternative approach of tapping outside
            if not done_clicked:
                logger.warning("Could not click DONE button, trying to tap outside the dialog")
                # Try to tap outside the dialog
                for strategy, locator in [(AppiumBy.ID, "com.amazon.kindle:id/touch_outside")]:
                    try:
                        outside_area = self.driver.find_element(strategy, locator)
                        if outside_area.is_displayed():
                            logger.info(f"Tapping outside area using {strategy}={locator}")
                            outside_area.click()
                            done_clicked = True
                            time.sleep(1)  # Wait for dialog to close
                            break
                    except Exception as e:
                        logger.debug(f"Could not tap outside area: {e}")
                        continue

                # If tapping specific outside area didn't work, try tapping at screen coordinates
                if not done_clicked:
                    try:
                        # Tap in the top-left corner where there's usually nothing in the dialog
                        screen_size = self.driver.get_window_size()
                        x = int(screen_size["width"] * 0.1)
                        y = int(screen_size["height"] * 0.1)
                        logger.info(f"Tapping at screen coordinates ({x}, {y})")
                        self.driver.tap([(x, y)])
                        done_clicked = True
                        time.sleep(1)  # Wait for dialog to close
                    except Exception as e:
                        logger.error(f"Error tapping at screen coordinates: {e}", exc_info=True)

            # Verify the dialog was closed
            if self._is_grid_list_view_dialog_open():
                logger.error("Failed to close Grid/List view dialog", exc_info=True)
                return False

            logger.info("Successfully handled Grid/List view selection dialog")
            return True

        except Exception as e:
            logger.error(f"Error handling Grid/List view selection dialog: {e}", exc_info=True)
            traceback.print_exc()
            return False

    def check_for_sign_in_button(self):
        """Check if the sign-in button is present in the library view.

        Returns:
            bool: True if sign-in button is present, False otherwise
        """

        try:
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    if button.is_displayed():
                        logger.info(f"Found sign-in button in library view using {strategy}")
                        return True
                except NoSuchElementException:
                    continue

            # Also check by ID based on the XML
            try:
                button = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in")
                if button.is_displayed():
                    logger.info("Found sign-in button by ID")
                    return True
            except NoSuchElementException:
                pass

            # Check for empty library logged out container
            try:
                container = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/empty_library_logged_out"
                )
                if container.is_displayed():
                    logger.info("Found empty library logged out container")
                    return True
            except NoSuchElementException:
                pass

            return False

        except Exception as e:
            logger.error(f"Error checking for sign-in button: {e}", exc_info=True)
            return False

    def handle_library_sign_in(self):
        """Handle sign-in when in library view with sign-in button.

        This method clicks the sign-in button when detected in the library view,
        which should transition to the authentication flow.

        Returns:
            bool: True if successfully clicked sign-in button, False otherwise
        """

        try:
            logger.info("Attempting to handle library sign-in...")

            # Check for and click sign-in button using strategies
            for strategy, locator in LIBRARY_SIGN_IN_STRATEGIES:
                try:
                    button = self.driver.find_element(strategy, locator)
                    if button.is_displayed():
                        logger.info(f"Found and clicking sign-in button using {strategy}")
                        button.click()
                        time.sleep(1)  # Wait for navigation
                        return True
                except NoSuchElementException:
                    continue

            # Try by ID based on XML
            try:
                button = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in")
                if button.is_displayed():
                    logger.info("Found and clicking sign-in button by ID")
                    button.click()
                    time.sleep(1)  # Wait for navigation
                    return True
            except NoSuchElementException:
                pass

            logger.error("Could not find sign-in button to click", exc_info=True)
            return False

        except Exception as e:
            logger.error(f"Error handling library sign-in: {e}", exc_info=True)
            return False

    def get_book_titles(self, callback=None, sync=False):
        """Get a list of all books in the library with their metadata.

        Args:
            callback: Optional callback function that will receive books as they're found.
                     If provided, books will be streamed to this function in batches.
                     The callback should accept a list of book dictionaries as its first argument,
                     and optional kwargs for control messages.
            sync: If True, perform pull-to-refresh to ensure we're working with the latest book list.

        Returns:
            List of book dictionaries, or None if authentication is required.
            If callback is provided, results are also streamed to the callback as they're found.
        """
        try:
            # Check if Grid/List view dialog is open and handle it first
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is open at the start, handling it first")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                    # Continue anyway, as navigate_to_library will try again

            # Ensure we're in the library view
            if not self.navigate_to_library():
                logger.error("Failed to navigate to library", exc_info=True)
                if callback:
                    callback(None, error="Failed to navigate to library")
                return []

            # Check if we need to sign in
            if self.check_for_sign_in_button():
                logger.warning("Library view shows sign-in button - authentication required")
                if callback:
                    callback(None, error="Authentication required")
                return None  # Return None to indicate authentication needed

            # Check if Grid/List view dialog is open after navigating to library
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is open after navigation, handling it")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                    # Try to continue anyway

            # Check if a book has been selected (happens from inadvertent long press)
            if self.scroll_handler.is_in_book_selection_mode():
                logger.info("Book selection mode detected, exiting selection mode first")
                if not self.scroll_handler.exit_book_selection_mode():
                    logger.error("Failed to exit book selection mode", exc_info=True)
                    if callback:
                        callback(None, error="Failed to exit book selection mode")
                    return []
                logger.info("Successfully exited book selection mode")

            # Check if we're in search results interface (can be misidentified as library)
            if self._is_in_search_interface():
                logger.info("Detected we're in search results interface, exiting search mode first")
                if not self.search_handler._exit_search_mode():
                    logger.error("Failed to exit search mode", exc_info=True)
                    if callback:
                        callback(None, error="Failed to exit search mode")
                    return []
                logger.info("Successfully exited search mode")
                time.sleep(1)  # Give UI time to settle

            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view", exc_info=True)
                    if callback:
                        callback(None, error="Failed to switch to list view")
                    return []
                logger.info("Successfully switched to list view")

            # Check if we're in a series/collection expanded view and exit if needed
            if self._is_in_series_collection_view():
                logger.info("Detected we're in series/collection view when getting books, exiting first")
                if not self._exit_series_collection_view():
                    logger.warning("Failed to exit series/collection view, continuing anyway...")
                else:
                    logger.info("Successfully exited series/collection view")
                    # Give UI time to settle after exiting series view
                    time.sleep(1)

            # Scroll to top of list (hits All/Downloaded tabs to ensure we're at the top)
            if not self.scroll_handler.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Always perform pull-to-refresh to ensure latest book list (after we're at the top)
            logger.info("Performing pull-to-refresh to get latest book list")
            if not self.pull_to_refresh():
                logger.warning("Pull-to-refresh failed, continuing anyway...")

            # After pull-to-refresh and All/Downloaded tab switching, capture filter book count
            filter_book_count = self.click_filter_button_and_count_books()
            if filter_book_count is not None:
                logger.info(f"Captured filter book count: {filter_book_count}")
                # Save to database
                try:
                    from server.utils.request_utils import get_sindarin_email

                    sindarin_email = get_sindarin_email()
                    if sindarin_email:
                        self.driver.automator.profile_manager.save_style_setting(
                            "filter_book_count", filter_book_count
                        )
                        logger.info(f"Saved filter book count to database: {filter_book_count}")

                    # Send the filter book count in the callback if available
                    if callback:
                        callback(None, filter_book_count=filter_book_count)
                except Exception as e:
                    logger.error(f"Error saving filter book count: {e}", exc_info=True)
            else:
                logger.warning("Failed to capture filter book count")

            # Use the scroll handler's method to get all books
            # If callback is provided, pass it to the scroll handler for streaming
            return self.scroll_handler._scroll_through_library(callback=callback)

        except Exception as e:
            logger.error(f"Error getting book titles: {e}", exc_info=True)
            if callback:
                callback(None, error=str(e))
            return []

    def _check_invalid_item_dialog(self, book_title, context=""):
        """Check for and handle the 'Invalid Item' dialog.

        Args:
            book_title: The title of the book being accessed
            context: Context description for logging (e.g., "after clicking book")

        Returns:
            bool: True if dialog was found and handled, False otherwise
        """
        from views.library.interaction_strategies import INVALID_ITEM_DIALOG_BUTTONS
        from views.library.view_strategies import INVALID_ITEM_DIALOG_IDENTIFIERS

        try:
            for strategy, locator in INVALID_ITEM_DIALOG_IDENTIFIERS:
                try:
                    dialog_title = self.driver.find_element(strategy, locator)
                    if dialog_title.is_displayed():
                        logger.info(f"Found 'Invalid Item' dialog {context}")

                        # Store page source for diagnostics
                        store_page_source(
                            self.driver.page_source,
                            f"invalid_item_dialog_{context.replace(' ', '_')}",
                        )

                        # Get the error message text if available
                        error_message = "Please remove the item from your device and go to All Items to download it again."
                        try:
                            message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
                            if message_element and message_element.is_displayed():
                                error_message = message_element.text
                                logger.info(f"Invalid Item dialog message: {error_message}")
                        except:
                            logger.debug("Could not get error message text from dialog")

                        # Click the REMOVE button
                        remove_clicked = False
                        for btn_strategy, btn_locator in INVALID_ITEM_DIALOG_BUTTONS:
                            try:
                                btn = self.driver.find_element(btn_strategy, btn_locator)
                                if btn.is_displayed() and (
                                    btn.text == "REMOVE" or "button1" in str(btn_locator)
                                ):
                                    btn.click()
                                    logger.info(f"Clicked REMOVE button on 'Invalid Item' dialog")
                                    remove_clicked = True
                                    time.sleep(1)  # Wait for dialog to dismiss
                                    break
                            except:
                                continue

                        if not remove_clicked:
                            logger.warning("Could not click REMOVE button on 'Invalid Item' dialog")

                        # Set an error property on the automator to inform the client
                        if hasattr(self.driver, "automator"):
                            self.driver.automator.last_error = {
                                "type": "invalid_item",
                                "message": error_message,
                                "book_title": book_title,
                            }

                        # Return True to indicate dialog was found and handled
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for 'Invalid Item' dialog: {e}")

            # Dialog not found
            return False
        except Exception as e:
            logger.error(f"Error in _check_invalid_item_dialog: {e}", exc_info=True)
            return False

    def _check_unable_to_download_dialog(self, book_title, context=""):
        """Check for and handle the 'Unable to Download' dialog.

        Args:
            book_title: The title of the book being downloaded/opened
            context: Context description for logging (e.g., "after clicking book")

        Returns:
            bool: True if dialog was found and handled, False otherwise
        """
        from views.library.interaction_strategies import (
            UNABLE_TO_DOWNLOAD_DIALOG_BUTTONS,
            UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS,
        )

        try:
            for strategy, locator in UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS:
                try:
                    dialog_title = self.driver.find_element(strategy, locator)
                    if dialog_title.is_displayed():
                        if dialog_title.text == "Unable to Download" or strategy == AppiumBy.ID:
                            logger.info(f"Found 'Unable to Download' dialog {context}")

                            # Store page source for diagnostics
                            store_page_source(
                                self.driver.page_source,
                                f"unable_to_download_dialog_{context.replace(' ', '_')}",
                            )

                            # Get the error message text if available
                            error_message = "Book is not available to download"
                            try:
                                message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
                                if message_element and message_element.is_displayed():
                                    error_message = message_element.text
                                    logger.info(f"Unable to Download dialog message: {error_message}")
                            except:
                                logger.debug("Could not get error message text from dialog")

                            # Click the CANCEL button
                            cancel_clicked = False
                            for btn_strategy, btn_locator in UNABLE_TO_DOWNLOAD_DIALOG_BUTTONS:
                                try:
                                    btn = self.driver.find_element(btn_strategy, btn_locator)
                                    if btn.is_displayed() and (
                                        btn.text == "CANCEL" or "button2" in str(btn_locator)
                                    ):
                                        btn.click()
                                        logger.info(f"Clicked CANCEL button on 'Unable to Download' dialog")
                                        cancel_clicked = True
                                        time.sleep(1)  # Wait for dialog to dismiss
                                        break
                                except:
                                    continue

                            if not cancel_clicked:
                                logger.warning("Could not click CANCEL button on 'Unable to Download' dialog")

                            # Set an error property on the automator to inform the client
                            if hasattr(self.driver, "automator"):
                                self.driver.automator.last_error = {
                                    "type": "unable_to_download",
                                    "message": error_message,
                                    "book_title": book_title,
                                }

                            # Return True to indicate dialog was found and handled
                            return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for 'Unable to Download' dialog: {e}")

            # Dialog not found
            return False
        except Exception as e:
            logger.error(f"Error in _check_unable_to_download_dialog: {e}", exc_info=True)
            return False

    def _handle_book_click_and_transition(
        self, parent_container, button, book_info, book_title, cancellation_check=None
    ):
        """Handle clicking a book, waiting for download if needed, and transitioning to reading view.

        This is a shared method used after finding a book through various methods (visible on screen,
        search, or scrolling). It handles:
        1. Checking if the book needs to be downloaded
        2. Waiting for download to complete if needed
        3. Clicking the book and verifying transition to reading view
        4. Checking and handling dialogs like "Unable to Download"

        Args:
            parent_container: The parent element containing the book
            button: The clickable element for the book
            book_info: Dictionary containing book metadata
            book_title: The title of the book (used for logging and verification)
            cancellation_check: Optional function to check if operation should be cancelled

        Returns:
            bool: True if book was successfully opened, False otherwise
        """
        try:
            # Check for cancellation before any clicks
            if cancellation_check and cancellation_check():
                logger.info("Book click cancelled by higher priority operation")
                return False
            # Check download status and handle download if needed
            content_desc = parent_container.get_attribute("content-desc") or ""
            logger.info(f"Book content description: {content_desc}")
            store_page_source(self.driver.page_source, "library_view_book_info")

            if "Book not downloaded" in content_desc:
                logger.info("Book is not downloaded yet, initiating download...")
                button.click()
                logger.info("Clicked book to start download")

                # Store page source immediately after click
                store_page_source(self.driver.page_source, "after_book_click_download_start")

                # Wait a moment for view to stabilize and check what opened
                self._wait_for_view_transition(timeout=1)

                # Check if we accidentally opened a series/collection view
                if self._is_in_series_collection_view():
                    logger.info("Opened series/collection view instead of starting download, backing out")
                    if self._exit_series_collection_view():
                        logger.info("Successfully exited series view, retrying book search")
                        return self.find_book(book_title)
                    else:
                        logger.error("Failed to exit series/collection view")
                        return False

                # Check for "Invalid Item" dialog first
                if self._check_invalid_item_dialog(book_title, "after clicking non-downloaded book"):
                    # Try to find the book again after removing it
                    logger.info(f"Book '{book_title}' was removed as an invalid item, trying to find again")
                    time.sleep(1)  # Wait for UI to refresh after removal
                    return self.find_book(book_title)

                # Check for "Unable to Download" dialog
                if self._check_unable_to_download_dialog(book_title, "after clicking non-downloaded book"):
                    return False

                # Check for download progress bar
                if self._check_for_download_progress_bar():
                    logger.info("Download progress bar detected, waiting for download to complete...")
                    if not self._wait_for_download_completion():
                        return False

                    # After download completes, check if we're already in reading view
                    # The download completion might have auto-opened the book
                    try:
                        for identifier_type, identifier_value in READING_VIEW_IDENTIFIERS[:3]:
                            try:
                                element = self.driver.find_element(identifier_type, identifier_value)
                                if element:
                                    logger.info("Already in reading view after download completed")
                                    return True
                            except NoSuchElementException:
                                continue
                    except Exception:
                        pass

                    # Check which view we're in after download
                    try:
                        # Check if we're in search results view
                        self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/search_recycler_view")
                        logger.info("Still in search results view after download")
                        # In search results, the UI often changes after download, so we should let the caller retry
                        return True
                    except NoSuchElementException:
                        pass

                    try:
                        # Check if we're in library view
                        self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                        logger.info("Still in library view after download, need to retry book click")
                        return True
                    except NoSuchElementException:
                        pass

                    # Not in search or library view, we might be transitioning
                    logger.info("Not in search or library view after download, likely transitioning")
                    return True

                # After clicking the book, first check if we've already left the library view
                # This happens when the book downloads very quickly or is already downloaded
                try:
                    # Use a short timeout (2 seconds) to check if we've already left library view
                    logger.info("Checking if we've already left the library view...")
                    WebDriverWait(self.driver, 2).until_not(
                        EC.presence_of_element_located(
                            (AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                        )
                    )
                    logger.info("Already left library view - book opened immediately")

                    # If we're here, we're already in the reading view
                    return True
                except TimeoutException:
                    # We're still in library view, continue with download monitoring
                    logger.info("Still in library view, monitoring download status...")
                    pass

                # Wait for download to complete (max 30 seconds) with monitoring
                max_attempts = 30
                start_time = time.time()
                last_capture_time = start_time
                capture_count = 0

                for attempt in range(max_attempts):
                    try:
                        # Capture page source every second during download
                        current_time = time.time()
                        if current_time - last_capture_time >= 1.0:
                            capture_count += 1
                            elapsed = current_time - start_time
                            logger.info(f"Book download in progress... {elapsed:.1f}s elapsed")
                            store_page_source(
                                self.driver.page_source, f"book_downloading_{capture_count}_{int(elapsed)}s"
                            )
                            last_capture_time = current_time

                        # Check again for "Unable to Download" dialog that might appear during download
                        if self._check_unable_to_download_dialog(
                            book_title, f"during download attempt {attempt}"
                        ):
                            return False

                        # First check if we've already left the library view (download finished and opened)
                        try:
                            # Check if we're still in library view
                            self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                            # We're still in library view, continue checking download status
                        except NoSuchElementException:
                            # We've left the library view - book has opened automatically
                            logger.info(
                                f"Left library view automatically after {attempt} checks - book opened"
                            )
                            return True

                        # Re-find the parent container since the page might have refreshed
                        title_text = book_info.get("title", book_title)

                        # For titles with apostrophes, use a more reliable approach
                        if "'" in title_text:
                            # Split by apostrophe and use the part before it
                            first_part = title_text.split("'")[0].strip()
                            if first_part:
                                xpath = f"//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and contains(@text, '{first_part}')]]"
                            else:
                                # Fallback to just match with the ID
                                xpath = f"//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']]"
                        else:
                            # Normal case - use exact text matching
                            xpath = f"//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text='{title_text}']]"

                        # Try to find the book element - if this fails, it might mean we've already left the view
                        try:
                            parent_container = self.driver.find_element(AppiumBy.XPATH, xpath)
                            content_desc = parent_container.get_attribute("content-desc") or ""
                            logger.info(
                                f"Checking download status (attempt {attempt + 1}/{max_attempts}): {content_desc}"
                            )

                            if "Book downloaded" in content_desc:
                                logger.info("Book has finished downloading")
                                time.sleep(1)  # Short wait for UI to stabilize
                                # Check cancellation before clicking
                                if cancellation_check and cancellation_check():
                                    logger.info("Book open click cancelled after download")
                                    return False
                                parent_container.click()
                                logger.info("Clicked book button after download")

                                # Wait for view transition and check if we accidentally opened a series/collection view
                                self._wait_for_view_transition(timeout=1)
                                if self._is_in_series_collection_view():
                                    logger.info("Opened series/collection view after download, backing out")
                                    if self._exit_series_collection_view():
                                        logger.info("Successfully exited series view, retrying book search")
                                        return self.find_book(book_title)
                                    else:
                                        logger.error("Failed to exit series/collection view")
                                        return False

                                # Check for "Invalid Item" dialog first
                                if self._check_invalid_item_dialog(
                                    book_title, "after clicking downloaded book"
                                ):
                                    # Try to find the book again after removing it
                                    logger.info(
                                        f"Book '{book_title}' was removed as an invalid item, trying to find again"
                                    )
                                    time.sleep(1)  # Wait for UI to refresh after removal
                                    return self.find_book(book_title)

                                # Check for "Unable to Download" dialog again after clicking downloaded book
                                if self._check_unable_to_download_dialog(
                                    book_title, "after clicking downloaded book"
                                ):
                                    return False

                                # Check if we successfully left the library view
                                try:
                                    self.driver.find_element(
                                        AppiumBy.ID,
                                        "com.amazon.kindle:id/library_root_view",
                                    )
                                    logger.warning(
                                        "Still in library view after clicking downloaded book, trying again..."
                                    )
                                    time.sleep(1)
                                    # Check cancellation before clicking again
                                    if cancellation_check and cancellation_check():
                                        logger.info("Book retry click cancelled")
                                        return False
                                    parent_container.click()
                                    logger.info("Clicked book again")
                                except NoSuchElementException:
                                    logger.info("Successfully left library view")

                                return True

                            # If we see an error in the content description, abort
                            if any(error in content_desc.lower() for error in ["error", "failed"]):
                                logger.error(f"Download failed: {content_desc}", exc_info=True)
                                return False
                        except NoSuchElementException:
                            # If we can't find the book element, check if we've left the library view
                            logger.info("Can't find book element - checking if we've left library view")
                            try:
                                self.driver.find_element(
                                    AppiumBy.ID,
                                    "com.amazon.kindle:id/library_root_view",
                                )
                                logger.warning("Still in library view but can't find book element")
                            except NoSuchElementException:
                                logger.info("Left library view - book likely opened automatically")
                                return True

                        time.sleep(1)
                    except Exception as e:
                        logger.error(f"Error checking download status: {e}", exc_info=True)

                        # Check if we've already left the library view
                        try:
                            self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                            # We're still in library view, continue checking
                            logger.info("Still in library view despite error, continuing...")
                        except NoSuchElementException:
                            # We've left the library view - book has opened automatically
                            logger.info("Left library view - book opened despite error")
                            return True

                        time.sleep(1)
                        continue

                # If we've timed out but are no longer in library view, that's still success
                try:
                    self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                    logger.error(
                        "Timed out waiting for book to download and still in library view", exc_info=True
                    )
                    return False
                except NoSuchElementException:
                    logger.info("Left library view after timeout - book likely opened anyway")
                    return True

            # For already downloaded books, just click and verify
            logger.info(f"Found downloaded book: {book_info.get('title', book_title)}")
            button.click()
            logger.info("Clicked book button")

            # Store page source immediately after click
            store_page_source(self.driver.page_source, "after_book_click_already_downloaded")

            # Wait for view transition and check if we accidentally opened a series/collection view
            self._wait_for_view_transition(timeout=1)
            if self._is_in_series_collection_view():
                logger.info("Opened series/collection view instead of book, backing out")
                if self._exit_series_collection_view():
                    logger.info("Successfully exited series view, retrying book search")
                    # Now try to find the actual book again
                    # Since we're in a series view, the book title might need adjustment
                    return self.find_book(book_title)
                else:
                    logger.error("Failed to exit series/collection view")
                    return False

            # Check for download progress bar even for "downloaded" books
            # Sometimes the content-desc may show downloaded but it's still downloading
            if self._check_for_download_progress_bar():
                logger.info(
                    "Download progress bar detected on already downloaded book, waiting for download to complete..."
                )
                if not self._wait_for_download_completion():
                    return False

            # Check for "Invalid Item" dialog first
            if self._check_invalid_item_dialog(book_title, "after clicking already downloaded book"):
                # Try to find the book again after removing it
                logger.info(f"Book '{book_title}' was removed as an invalid item, trying to find again")
                time.sleep(1)  # Wait for UI to refresh after removal
                return self.find_book(book_title)

            # Check for "Unable to Download" dialog for already downloaded books
            if self._check_unable_to_download_dialog(book_title, "after clicking already downloaded book"):
                return False

            # Wait for library view to disappear (we've left it)
            try:
                WebDriverWait(self.driver, 5).until_not(
                    EC.presence_of_element_located((AppiumBy.ID, "com.amazon.kindle:id/library_root_view"))
                )
                logger.info("Successfully left library view")
                return True
            except TimeoutException:
                logger.error("Still in library view after clicking book", exc_info=True)
                # Try clicking one more time
                button.click()

                # Check for "Invalid Item" dialog first
                if self._check_invalid_item_dialog(book_title, "after second click"):
                    # Try to find the book again after removing it
                    logger.info(f"Book '{book_title}' was removed as an invalid item, trying to find again")
                    time.sleep(1)  # Wait for UI to refresh after removal
                    return self.find_book(book_title)

                # Check for "Unable to Download" dialog after second click
                if self._check_unable_to_download_dialog(book_title, "after second click"):
                    return False

                # Wait again for library view to disappear
                try:
                    WebDriverWait(self.driver, 5).until_not(
                        EC.presence_of_element_located(
                            (AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                        )
                    )
                    logger.info("Successfully left library view after second click")
                    return True
                except TimeoutException:
                    logger.error(
                        "Still in library view after second click, trying with parent container",
                        exc_info=True,
                    )
                    # Try clicking the parent container instead
                    # Check cancellation before clicking
                    if cancellation_check and cancellation_check():
                        logger.info("Book parent container click cancelled")
                        return False
                    parent_container.click()

                    # Check for "Invalid Item" dialog first
                    if self._check_invalid_item_dialog(book_title, "after parent container click"):
                        # Try to find the book again after removing it
                        logger.info(
                            f"Book '{book_title}' was removed as an invalid item, trying to find again"
                        )
                        time.sleep(1)  # Wait for UI to refresh after removal
                        return self.find_book(book_title)

                    # Check for "Unable to Download" dialog after parent container click
                    if self._check_unable_to_download_dialog(book_title, "after parent container click"):
                        return False

                    # Wait one more time for library view to disappear
                    try:
                        WebDriverWait(self.driver, 5).until_not(
                            EC.presence_of_element_located(
                                (AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                            )
                        )
                        logger.info("Successfully left library view after clicking parent container")
                        return True
                    except TimeoutException:
                        logger.error("Failed to leave library view after multiple attempts", exc_info=True)
                        return False

        except Exception as e:
            logger.error(f"Error handling book click and transition: {e}", exc_info=True)
            traceback.print_exc()
            return False

    def find_book(self, book_title: str) -> bool:
        """Find and click a book button by title. If the book isn't downloaded, initiate download and wait for completion."""
        try:
            # Try using the search box first to find the book
            search_result = self.search_handler.search_for_book(book_title)
            # search_result = False  # TODO: Remove this once done testing scrolling method

            if search_result:
                parent_container, button, book_info = search_result
                logger.info(f"Successfully found book '{book_title}' using search function: {book_info}")

                # Handle clicking the book and check if we successfully exit library view
                return self._handle_book_click_and_transition(parent_container, button, book_info, book_title)
            else:
                logger.info(f"Search function didn't find '{book_title}', falling back to scrolling method")

            # Fallback: Search for the book by scrolling

            # Only handle Grid/List view if cached preferences indicate we need to
            if not self._is_library_view_preferences_correctly_set():
                # First check if we're in the Grid/List view dialog and handle it
                if self._is_grid_list_view_dialog_open():
                    logger.info("Detected Grid/List view dialog is open, handling it first")
                    if not self.handle_grid_list_view_dialog():
                        logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                        return False
                    logger.info("Successfully handled Grid/List view dialog")
                    time.sleep(1)  # Wait for UI to stabilize

                # Check if we're in grid view and switch to list view if needed
                if self._is_grid_view():
                    logger.info("Detected grid view, switching to list view")
                    if not self.switch_to_list_view():
                        logger.error("Failed to switch to list view", exc_info=True)
                        return False
                    logger.info("Successfully switched to list view")
            else:
                logger.info(
                    "Skipping grid/list view checks in find_book - cached preferences already set correctly"
                )

            # Scroll to top first
            if not self.scroll_handler.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Provide the title_match_func to scroll_through_library
            parent_container, button, book_info = self.scroll_handler._scroll_through_library(
                book_title, title_match_func=self.search_handler._title_match
            )

            # If standard search failed, check for partial matches
            if not parent_container:
                logger.info(f"Standard search failed for '{book_title}', checking for partial matches")

                # Get any partial matches that were collected during scrolling
                partial_matches = self.scroll_handler.get_partial_matches()

                if partial_matches:
                    logger.info(f"Found {len(partial_matches)} partial matches during the scroll")

                    # Use the first partial match
                    _, _, book_info = partial_matches[0]
                    if book_info and book_info.get("title"):
                        logger.info(f"Using partial match: '{book_info['title']}' for '{book_title}'")

                        # Try to find this book on screen
                        visible_book_result = self.search_handler._check_book_visible_on_screen(
                            book_info["title"]
                        )
                        if visible_book_result:
                            parent_container, button, _ = visible_book_result
                            logger.info(f"Found partial match '{book_info['title']}' visible on screen")
                        else:
                            # If not visible, scroll to top and try to find it again
                            logger.info(f"Partial match not visible, scrolling to top to find it")
                            self.scroll_handler.scroll_to_list_top()

                            # Now search for this specific book by title
                            parent_container, button, _ = self.scroll_handler._scroll_through_library(
                                book_info["title"], title_match_func=self.search_handler._title_match
                            )

                # If no partial matches found or couldn't locate the book, fall back to original method
                if not parent_container:
                    logger.info("No usable partial matches, falling back to word-based matching")
                    parent_container, button, book_info = self.search_handler._find_book_by_partial_match(
                        book_title,
                        scroll_through_library_func=lambda: self.scroll_handler._scroll_through_library(),
                    )

                if not parent_container:
                    logger.error(
                        f"Failed to find book '{book_title}' using all search methods", exc_info=True
                    )
                    return False

                logger.info(f"Found book using partial match fallback: {book_info}")

            # Now that we've found the book, handle clicking it and transition
            return self._handle_book_click_and_transition(parent_container, button, book_info, book_title)

        except Exception as e:
            logger.error(f"Error finding book: {e}", exc_info=True)
            traceback.print_exc()
            return False

    def _check_for_download_progress_bar(self):
        """Check if a download progress bar is visible.

        Returns:
            bool: True if download progress bar is found, False otherwise
        """
        for strategy, locator in DOWNLOAD_PROGRESS_BAR_IDENTIFIERS:
            try:
                element = self.driver.find_element(strategy, locator)
                # Don't call is_displayed() as it can cause stale element exceptions
                # The fact that we found the element is enough
                logger.info(f"Download progress bar detected using {strategy} with locator: {locator}")
                return True
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        return False

    def _wait_for_download_completion(self, timeout=120):
        """Wait for download progress bar to disappear.

        Args:
            timeout: Maximum time to wait for download completion in seconds

        Returns:
            bool: True if download completed (progress bar disappeared), False if timeout
        """
        logger.info("Waiting for download to complete...")
        start_time = time.time()
        last_capture_time = start_time
        capture_count = 0

        while time.time() - start_time < timeout:
            # Capture page source periodically
            current_time = time.time()
            if current_time - last_capture_time >= 2.0:
                capture_count += 1
                elapsed = current_time - start_time
                store_page_source(
                    self.driver.page_source, f"download_progress_{capture_count}_{int(elapsed)}s"
                )
                last_capture_time = current_time

            try:
                # Check if progress bar is still visible
                if not self._check_for_download_progress_bar():
                    logger.info(f"Download completed after {time.time() - start_time:.1f}s")
                    return True

                # Also check if we've already transitioned to reading view
                for identifier_type, identifier_value in READING_VIEW_IDENTIFIERS[:3]:
                    try:
                        element = self.driver.find_element(identifier_type, identifier_value)
                        if element:
                            logger.info("Already transitioned to reading view during download")
                            return True
                    except NoSuchElementException:
                        continue
            except StaleElementReferenceException:
                # If we get a stale element exception, it likely means the view changed
                # Wait a moment and continue checking
                logger.info("Got stale element exception during download check, view likely changed")
                time.sleep(1)
                continue
            except Exception as e:
                logger.warning(f"Exception during download completion check: {e}")
                pass

            time.sleep(0.5)

        logger.error(f"Download did not complete within {timeout}s timeout", exc_info=True)
        return False

    def open_book(self, book_title: str) -> dict:
        """Open a book in the library.

        Args:
            book_title (str): The title of the book to open

        Returns:
            dict: A result dictionary with 'success' boolean and optional error details
        """
        try:
            # Check if we have any cached preferences at all
            cached_view_type = self.driver.automator.profile_manager.get_style_setting("view_type")
            cached_group_by_series = self.driver.automator.profile_manager.get_style_setting(
                "group_by_series"
            )

            # If we have no preferences cached, try to discover the current state
            if cached_view_type is None or cached_group_by_series is None:
                logger.info(
                    "No cached library preferences found in open_book, attempting to discover current state"
                )
                self._discover_and_save_library_preferences()

            # Only handle the Grid/List view dialog if cached preferences indicate we need to
            if not self._is_library_view_preferences_correctly_set():
                # Check if we're in the Grid/List view dialog and handle it before trying to open a book
                if self._is_grid_list_view_dialog_open():
                    logger.info(
                        "Detected Grid/List view dialog is open before opening book, handling it first"
                    )
                    if not self.handle_grid_list_view_dialog():
                        logger.error("Failed to handle Grid/List view dialog", exc_info=True)
                        store_page_source(self.driver.page_source, "failed_to_handle_grid_list_dialog")
                        return {"success": False, "error": "Failed to handle Grid/List view dialog"}
                    logger.info("Successfully handled Grid/List view dialog")
                    time.sleep(1)  # Wait for UI to stabilize
                else:
                    # Dialog is not open but preferences aren't correctly set
                    # We need to open the dialog to check/set group_by_series
                    if cached_group_by_series is None:
                        logger.info("group_by_series is not set, opening Grid/List dialog to check/set it")
                        # Use force_open=True to ensure dialog opens even if view_type is already set
                        if self.open_grid_list_view_dialog(force_open=True):
                            logger.info("Opened Grid/List dialog, now handling it")
                            if not self.handle_grid_list_view_dialog():
                                logger.error(
                                    "Failed to handle Grid/List view dialog after opening", exc_info=True
                                )
                                return {
                                    "success": False,
                                    "error": "Failed to handle Grid/List view dialog after opening",
                                }
                        else:
                            logger.warning("Failed to open Grid/List dialog to check group_by_series")
            else:
                logger.info("Skipping Grid/List view dialog check - cached preferences already set correctly")

            # Import dialog identifiers here to avoid circular imports
            from views.reading.interaction_strategies import (
                TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS,
                UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS,
            )

            # Store initial page source for diagnostics
            store_page_source(self.driver.page_source, "library_before_book_search")

            # Check if the book is already visible on the current screen before searching
            visible_book_result = self.search_handler._check_book_visible_on_screen(book_title)
            if visible_book_result:
                parent_container, button, book_info = visible_book_result
                logger.info(f"Book '{book_title}' is already visible on the current screen")

                # Handle clicking the book
                button.click()
                logger.info(f"Clicked book button for already visible book: {book_title}")

                # Store page source immediately after click
                store_page_source(self.driver.page_source, "after_book_click")

                # Wait for view transition and check if we accidentally opened a series/collection view
                self._wait_for_view_transition(timeout=1)
                if self._is_in_series_collection_view():
                    logger.info("Opened series/collection view instead of book, backing out")
                    if self._exit_series_collection_view():
                        logger.info("Successfully exited series view, retrying book search")
                        return self.open_book(book_title)
                    else:
                        logger.error("Failed to exit series/collection view")
                        return {"success": False, "error": "Failed to exit series/collection view"}

                # Check for download progress bar
                if self._check_for_download_progress_bar():
                    logger.info("Download progress bar detected, waiting for download to complete...")
                    if not self._wait_for_download_completion():
                        return {"success": False, "error": "Download timed out"}

                    # After download completes, check if we're already in reading view
                    try:
                        for identifier_type, identifier_value in READING_VIEW_IDENTIFIERS[:3]:
                            try:
                                element = self.driver.find_element(identifier_type, identifier_value)
                                if element:
                                    logger.info("Already in reading view after download completed")
                                    return self._delegate_to_reader_handler(book_title)
                            except NoSuchElementException:
                                continue
                    except Exception:
                        pass

                    # After download completes, we need to click the book again
                    # Re-find the book to avoid stale element reference
                    time.sleep(1)  # Brief pause after download
                    visible_book_result = self.search_handler._check_book_visible_on_screen(book_title)
                    if visible_book_result:
                        _, button, _ = visible_book_result
                        button.click()
                        logger.info("Clicked book again after download completed")
                        store_page_source(self.driver.page_source, "after_book_click_post_download")

                # Check if we entered the reading view or hit a dialog
                try:
                    # Use WebDriverWait to check for either reading view or dialog
                    wait = WebDriverWait(self.driver, 5)

                    # Track time and capture page source periodically for download monitoring
                    start_time = time.time()
                    last_capture_time = start_time
                    capture_count = 0

                    def check_for_elements(driver):
                        nonlocal last_capture_time, capture_count

                        # Capture page source every second while waiting
                        current_time = time.time()
                        if current_time - last_capture_time >= 1.0:
                            capture_count += 1
                            elapsed = current_time - start_time
                            logger.info(f"Waiting for book to load/download... {elapsed:.1f}s elapsed")
                            store_page_source(
                                driver.page_source, f"book_download_state_{capture_count}_{int(elapsed)}s"
                            )
                            last_capture_time = current_time
                        # Check for Last Read Page dialog first
                        try:
                            last_read = driver.find_element(
                                AppiumBy.XPATH,
                                "//android.widget.TextView[contains(@text, 'Go to that page?')]",
                            )
                            if last_read and last_read.is_displayed():
                                logger.info("Last Read Page dialog detected when opening book")
                                return "last_read_page_dialog"
                        except NoSuchElementException:
                            # Also try location version of dialog
                            try:
                                last_read = driver.find_element(
                                    AppiumBy.XPATH,
                                    "//android.widget.TextView[contains(@text, 'Go to that location?')]",
                                )
                                if last_read and last_read.is_displayed():
                                    logger.info("Last Read Location dialog detected when opening book")
                                    return "last_read_page_dialog"
                            except NoSuchElementException:
                                pass

                        # Check for Title Not Available dialog
                        for strategy, locator in TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS:
                            try:
                                element = driver.find_element(strategy, locator)
                                if element and element.is_displayed():
                                    return "title_not_available"
                            except NoSuchElementException:
                                continue

                        # Check for Unable to Download dialog
                        for strategy, locator in UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS:
                            try:
                                element = driver.find_element(strategy, locator)
                                if element and element.is_displayed():
                                    return "unable_to_download"
                            except NoSuchElementException:
                                continue

                        # Check if we're in the reading view
                        for identifier_type, identifier_value in [
                            (AppiumBy.ID, "com.amazon.kindle:id/reader_drawer_layout"),
                            (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
                            (AppiumBy.ID, "com.amazon.kindle:id/reader_view"),
                        ]:
                            try:
                                element = driver.find_element(identifier_type, identifier_value)
                                if element:
                                    return "reading_view"
                            except NoSuchElementException:
                                continue

                        # Check if we're still in library view
                        try:
                            element = driver.find_element(
                                AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                            )
                            if element:
                                return "library_view"
                        except NoSuchElementException:
                            pass

                        return False

                    result = wait.until(check_for_elements)

                    if result == "title_not_available":
                        logger.info("Title Not Available dialog detected after clicking book")
                        return self._handle_loading_timeout(book_title)
                    elif result == "unable_to_download":
                        logger.info("Unable to Download dialog detected after clicking book")
                        return self._handle_unable_to_download(book_title)
                    elif result == "last_read_page_dialog":
                        logger.info("Last Read Page dialog detected, delegating to reader handler")
                        return self._delegate_to_reader_handler(book_title)
                    elif result == "reading_view":
                        logger.info("Successfully entered reading view")
                        return self._delegate_to_reader_handler(book_title)

                    # If not in reading view, check if we're still in library view
                    try:
                        self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                        logger.warning("Still in library view after clicking book, trying one more time")

                        # Re-find the button element to avoid stale element reference
                        visible_book_result = self.search_handler._check_book_visible_on_screen(book_title)
                        if visible_book_result:
                            _, button, _ = visible_book_result
                            button.click()
                            logger.info("Clicked book button again")

                            # Store page source immediately after second click
                            store_page_source(self.driver.page_source, "after_book_click_retry")

                            # Wait for view transition and check if we accidentally opened a series/collection view
                            self._wait_for_view_transition(timeout=1)
                            if self._is_in_series_collection_view():
                                logger.info("Opened series/collection view on retry, backing out")
                                if self._exit_series_collection_view():
                                    logger.info("Successfully exited series view, retrying book search")
                                    return self.open_book(book_title)
                                else:
                                    logger.error("Failed to exit series/collection view on retry")
                                    return {
                                        "success": False,
                                        "error": "Failed to exit series/collection view",
                                    }

                            # Check for download progress bar on retry
                            if self._check_for_download_progress_bar():
                                logger.info(
                                    "Download progress bar detected on retry, waiting for download to complete..."
                                )
                                if not self._wait_for_download_completion():
                                    return {"success": False, "error": "Download timed out on retry"}

                                # After download completes, check if we're already in reading view
                                try:
                                    for identifier_type, identifier_value in READING_VIEW_IDENTIFIERS[:3]:
                                        try:
                                            element = self.driver.find_element(
                                                identifier_type, identifier_value
                                            )
                                            if element:
                                                logger.info(
                                                    "Already in reading view after download completed on retry"
                                                )
                                                return self._delegate_to_reader_handler(book_title)
                                        except NoSuchElementException:
                                            continue
                                except Exception:
                                    pass

                                # Re-find and click the book again after download
                                time.sleep(1)
                                visible_book_result = self.search_handler._check_book_visible_on_screen(
                                    book_title
                                )
                                if visible_book_result:
                                    _, button, _ = visible_book_result
                                    button.click()
                                    logger.info("Clicked book again after download completed on retry")
                                    store_page_source(
                                        self.driver.page_source, "after_book_click_post_download_retry"
                                    )

                            # Wait for state transition - check if we leave library view or enter reading view
                            try:
                                # Track time and capture page source periodically for download monitoring
                                start_time = time.time()
                                last_capture_time = start_time
                                capture_count = 0

                                def check_transition(driver):
                                    nonlocal last_capture_time, capture_count

                                    # Capture page source every second while waiting
                                    current_time = time.time()
                                    if current_time - last_capture_time >= 1.0:
                                        capture_count += 1
                                        elapsed = current_time - start_time
                                        logger.info(
                                            f"Waiting for book transition after retry... {elapsed:.1f}s elapsed"
                                        )
                                        store_page_source(
                                            driver.page_source,
                                            f"book_transition_retry_{capture_count}_{int(elapsed)}s",
                                        )
                                        last_capture_time = current_time
                                    # Check if we're in reading view
                                    for identifier_type, identifier_value in READING_VIEW_IDENTIFIERS[:3]:
                                        try:
                                            element = driver.find_element(identifier_type, identifier_value)
                                            if element:
                                                logger.info("Transitioned to reading view after second click")
                                                return True
                                        except NoSuchElementException:
                                            continue

                                    # Check if we're still stuck in library view
                                    try:
                                        library_element = driver.find_element(
                                            AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                                        )
                                        if library_element.is_displayed():
                                            # Still in library, but wait will continue
                                            return False
                                    except NoSuchElementException:
                                        # Not in library view anymore, probably transitioning
                                        return True

                                    return False

                                WebDriverWait(self.driver, 3).until(check_transition)
                                logger.info("Successfully transitioned from library view")

                            except TimeoutException:
                                logger.error(
                                    "Still in library view after second click attempt", exc_info=True
                                )
                                store_page_source(
                                    self.driver.page_source, "stuck_in_library_after_second_click"
                                )
                                return {
                                    "success": False,
                                    "error": (
                                        "Unable to transition from library to reading view after multiple attempts"
                                    ),
                                }

                            # Now check if we're in reading view or have a dialog
                            return self._delegate_to_reader_handler(book_title)
                        else:
                            logger.error("Could not re-find book button for second click", exc_info=True)
                            return {
                                "success": False,
                                "error": "Could not re-find book button for second click",
                            }
                    except NoSuchElementException:
                        # Neither library nor reading view found
                        logger.warning("Neither library nor reading view found, assuming transition state")
                        # Give it a moment and check again
                        time.sleep(1)
                        return self._delegate_to_reader_handler(book_title)

                except TimeoutException:
                    logger.error("Timeout while checking view state", exc_info=True)
                    # Capture final page source to see what state we're stuck in
                    store_page_source(self.driver.page_source, "book_open_timeout_final_state")
                    return {"success": False, "error": "Timeout while checking view state"}

            # If book is not already visible, proceed with search and find methods
            logger.info(f"Proceeding to search for '{book_title}'")

            # Find and click the book button
            if not self.find_book(book_title):
                logger.error(f"Failed to find book: {book_title}", exc_info=True)
                return {"success": False, "error": f"Failed to find book: {book_title}"}

            logger.info(f"Successfully found and clicked book: {book_title}")

            # Now delegate to the reader_handler which will handle all dialogs
            return self._delegate_to_reader_handler(book_title)

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error opening book: {e}", exc_info=True)
            return {"success": False, "error": f"Error opening book: {e}"}

    def _delegate_to_reader_handler(self, book_title):
        """Delegate to the reader_handler to handle the reading view and any dialogs.

        This method is called after we've successfully clicked on a book and left the
        library view. The reader_handler will take care of dialogs like "Go to that page?",
        download limits, and other reading-related interactions.

        Args:
            book_title: The title of the book we're opening

        Returns:
            dict: A result dictionary with 'success' boolean and optional error details
        """
        # Get access to the reader_handler
        reader_handler = self.driver.automator.state_machine.reader_handler

        # Let the reader_handler handle the reading view dialogs
        # Note that we're NOT calling reader_handler.open_book() which would cause a circular reference
        # Instead, we're directly handling the dialogs here

        # Wait for the reading view to appear with a longer timeout
        try:
            # # Wait for any of the reading view identifiers to appear
            # WebDriverWait(self.driver, 3).until(
            #     lambda x: any(
            #         self._check_element_present(x, strategy, locator)
            #         for strategy, locator in READING_VIEW_IDENTIFIERS
            #     )
            # )
            # logger.info("Reading view loaded successfully")

            # Now that we're in the reading view, let reader_handler handle the dialogs
            # We use show_placemark=False to avoid showing the placemark ribbon
            dialog_handled = reader_handler.open_book(book_title, show_placemark=False)

            if dialog_handled:
                logger.info(f"Reader handler successfully handled dialogs for book '{book_title}'")
                return {"success": True}
            else:
                logger.error(
                    f"Reader handler failed to handle dialogs for book '{book_title}'", exc_info=True
                )
                return {"success": False, "error": "Reader handler failed to handle dialogs"}

        except TimeoutException:
            logger.error(f"Timed out waiting for reading view to appear", exc_info=True)
            # Check for any dialogs or error states
            return self._handle_loading_timeout(book_title)
        except Exception as e:
            logger.error(f"Error waiting for reading view: {e}", exc_info=True)
            return {"success": False, "error": f"Error waiting for reading view: {e}"}

    def _handle_page_navigation_dialog(self, source_description="dialog check"):
        """Handle the 'Go to that page?' or 'You are currently on page' dialog.

        Args:
            source_description (str): Description of where this is being called from for logging

        Returns:
            bool: True if dialog was found and handled successfully, False otherwise
        """
        try:
            # Look for message element containing the page navigation text
            message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
            if message_element and message_element.is_displayed():
                message_text = message_element.text

                # Check for both variations of the dialog text
                if ("Go to that page?" in message_text) or ("You are currently on page" in message_text):
                    logger.info(f"Found page navigation dialog during {source_description}: {message_text}")
                    store_page_source(
                        self.driver.page_source,
                        f"page_navigation_dialog_{source_description}",
                    )

                    # Try to click the YES button
                    try:
                        yes_button = self.driver.find_element(AppiumBy.ID, "android:id/button1")
                        if yes_button and yes_button.is_displayed() and yes_button.text == "YES":
                            yes_button.click()
                            logger.info(
                                f"Clicked YES button on page navigation dialog ({source_description})"
                            )
                            time.sleep(1.5)  # Give time for dialog to dismiss and reading view to load

                            # Now wait for reading view to appear
                            try:
                                WebDriverWait(self.driver, 10).until(
                                    lambda d: any(
                                        [
                                            self._check_element_present(
                                                d,
                                                AppiumBy.ID,
                                                "com.amazon.kindle:id/reader_drawer_layout",
                                            ),
                                            self._check_element_present(
                                                d,
                                                AppiumBy.ID,
                                                "com.amazon.kindle:id/reader_content_container",
                                            ),
                                            self._check_element_present(
                                                d,
                                                AppiumBy.ID,
                                                "com.amazon.kindle:id/reader_root_view",
                                            ),
                                        ]
                                    )
                                )
                                logger.info(
                                    f"Reading view loaded after handling page navigation dialog ({source_description})"
                                )
                                return True
                            except Exception as e:
                                logger.error(
                                    f"Failed to detect reading view after handling page navigation dialog: {e}",
                                    exc_info=True,
                                )
                                return False
                    except NoSuchElementException:
                        logger.warning("Could not find YES button on page navigation dialog")
                    except Exception as btn_e:
                        logger.error(f"Error clicking YES button: {btn_e}", exc_info=True)
            return False
        except NoSuchElementException:
            return False
        except Exception as e:
            logger.debug(f"Error checking for page navigation dialog: {e}")
            return False

    def _check_element_present(self, driver, by, value):
        """Helper method to check if an element is present and displayed.

        Args:
            driver: The WebDriver instance
            by: The locator strategy
            value: The locator value

        Returns:
            bool: True if element is present and displayed, False otherwise
        """
        try:
            element = driver.find_element(by, value)
            return element.is_displayed()
        except:
            return False

    def _check_reading_view_present(self, driver):
        """Helper method to check if any reading view element is present.

        Args:
            driver: The WebDriver instance

        Returns:
            bool or str: True if reading view elements found, "dialog" if dialog handled, False otherwise
        """
        # First check for "Go to that page?" or "You are currently on page" dialog
        try:
            message_element = driver.find_element(AppiumBy.ID, "android:id/message")
            if message_element.is_displayed():
                message_text = message_element.text

                # Check for dialog patterns
                if ("Go to that page?" in message_text) or ("You are currently on page" in message_text):
                    # We found the dialog, but we'll have the caller handle it via _handle_page_navigation_dialog
                    # This allows us to return a specific value for the caller to take appropriate action
                    return "dialog"
        except NoSuchElementException:
            pass
        except Exception:
            pass

        # Check for reading view elements
        for element_id in [
            "com.amazon.kindle:id/reader_drawer_layout",
            "com.amazon.kindle:id/reader_content_container",
            "com.amazon.kindle:id/reader_root_view",
        ]:
            if self._check_element_present(driver, AppiumBy.ID, element_id):
                return True

        return False

    def _handle_loading_timeout(self, book_title: str):
        """Handle timeout while waiting for reading view to load after clicking a book.

        Args:
            book_title (str): The title of the book that was clicked

        Returns:
            dict: A result dictionary with 'success' boolean and optional error details or status
        """
        filepath = store_page_source(self.driver.page_source, "unknown_library_timeout")
        logger.info(f"Stored unknown library timeout page source at: {filepath}")
        logger.error(f"Failed to wait for reading view after clicking '{book_title}'", exc_info=True)

        # Save screenshot for visual debugging
        screenshot_path = os.path.join(self.screenshots_dir, "library_timeout.png")
        self.driver.save_screenshot(screenshot_path)
        logger.info(f"Saved screenshot to {screenshot_path}")

        # After the timeout, let's check for specific dialogs that might have appeared
        logger.info("Checking for known dialogs after timeout...")
        try:
            # Import dialog identifiers here to avoid circular imports
            from views.reading.interaction_strategies import (
                DOWNLOAD_LIMIT_DEVICE_LIST,
                DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
                DOWNLOAD_LIMIT_ERROR_TEXT,
                DOWNLOAD_LIMIT_REMOVE_BUTTON,
                TITLE_NOT_AVAILABLE_DIALOG_BUTTONS,
                TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS,
            )

            # Check for "Go to that page?" dialog first - this is a common scenario that should be handled
            if self._handle_page_navigation_dialog("timeout handler"):
                return {"success": True}

            # Check for "Title Not Available" dialog
            for strategy, locator in TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        error_text = "Title Not Available"
                        try:
                            # Try to get the message text if available
                            message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
                            if message_element and message_element.is_displayed():
                                error_text = f"Title Not Available: {message_element.text}"
                        except:
                            pass

                        logger.error(f"Title Not Available dialog found: {error_text}", exc_info=True)

                        # Try to click the Cancel button to dismiss the dialog
                        try:
                            for (
                                btn_strategy,
                                btn_locator,
                            ) in TITLE_NOT_AVAILABLE_DIALOG_BUTTONS:
                                try:
                                    cancel_button = self.driver.find_element(btn_strategy, btn_locator)
                                    if cancel_button and cancel_button.is_displayed():
                                        cancel_button.click()
                                        logger.info("Clicked Cancel button on Title Not Available dialog")
                                        break
                                except:
                                    pass
                        except:
                            logger.warning("Failed to click Cancel button on Title Not Available dialog")

                        # Return a dictionary with error details instead of setting it on the automator
                        return {
                            "success": False,
                            "error": error_text,
                            "book_title": book_title,
                            "status": "title_not_available",
                        }
                except:
                    pass

            # Check for download limit dialog title
            for strategy, locator in DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Download Limit dialog found after timeout: {strategy}={locator}")
                        return {"success": True}  # ReaderHandler will handle the dialog
                except:
                    pass

            # Check for error text
            for strategy, locator in DOWNLOAD_LIMIT_ERROR_TEXT:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Download Limit error text found after timeout: {strategy}={locator}")
                        return {"success": True}  # ReaderHandler will handle the dialog
                except:
                    pass

            # Final check - look for device list + button combination
            device_list = None
            for dl_strategy, dl_locator in DOWNLOAD_LIMIT_DEVICE_LIST:
                try:
                    el = self.driver.find_element(dl_strategy, dl_locator)
                    if el.is_displayed():
                        device_list = True
                        break
                except:
                    pass

            button = None
            for btn_strategy, btn_locator in DOWNLOAD_LIMIT_REMOVE_BUTTON:
                try:
                    el = self.driver.find_element(btn_strategy, btn_locator)
                    if el.is_displayed():
                        button = True
                        break
                except:
                    pass

            if device_list and button:
                logger.info("Found Download Limit dialog (device list + button) after timeout")
                return {"success": True}  # ReaderHandler will handle the dialog

            # Check if we're still in the library view - we might need to try clicking the book again
            try:
                library_view = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                if library_view.is_displayed():
                    logger.info("Still in library view after timeout - book click may have failed")

                    # Check if the book is still visible on screen
                    visible_book_result = self.search_handler._check_book_visible_on_screen(book_title)
                    if visible_book_result:
                        parent_container, button, book_info = visible_book_result
                        logger.info(f"Book '{book_title}' is still visible - trying to click it again")

                        # Try clicking the book again
                        button.click()
                        logger.info("Clicked book button again after timeout")

                        # Wait for reading view with a longer timeout
                        try:
                            logger.info("Waiting for reading view to load after second click...")

                            # Define a custom wait condition that reuses our helper methods
                            def reading_view_present_second_click(driver):
                                # Use our helper method to check reading view or detect dialog
                                result = self._check_reading_view_present(driver)

                                # If we found the reading view, return True
                                if result is True:
                                    logger.info("Reading view found after second click")
                                    return True

                                # If we found a dialog, handle it
                                if result == "dialog":
                                    # Handle the dialog with our shared method
                                    # If dialog handling was successful, return True
                                    if self._handle_page_navigation_dialog("second click wait"):
                                        logger.info("Successfully handled dialog after second click")
                                        return True

                                # No reading view or dialog was successfully handled
                                return False

                            # Wait using the custom condition with longer timeout
                            WebDriverWait(self.driver, 20).until(reading_view_present_second_click)
                            logger.info("Reading view loaded after second click")
                            return True
                        except Exception as e:
                            logger.error(
                                f"Failed to wait for reading view after second click: {e}", exc_info=True
                            )

                            # Store state after second failure
                            store_page_source(self.driver.page_source, "after_second_click_failure")
                            screenshot_path = os.path.join(
                                self.screenshots_dir, "after_second_click_failure.png"
                            )
                            self.driver.save_screenshot(screenshot_path)
                    else:
                        logger.warning(f"Book '{book_title}' is no longer visible on screen after timeout")
            except NoSuchElementException:
                logger.info("Not in library view after timeout - may be transitioning or in a different view")
            except Exception as e:
                logger.error(f"Error checking library view status: {e}", exc_info=True)

            logger.info("No known dialogs found after explicit check")

        except Exception as dialog_e:
            logger.error(f"Error checking for known dialogs: {dialog_e}", exc_info=True)

        # We didn't find any expected dialogs, so return failure
        return {"success": False, "error": "Timeout waiting for reading view or expected dialogs"}

    def _handle_unable_to_download(self, book_title: str):
        """Handle the Unable to Download dialog when opening a book.

        Args:
            book_title (str): The title of the book that failed to download

        Returns:
            dict: A result dictionary with 'success' boolean and error details
        """
        # Import dialog identifiers from the reading module
        from views.reading.interaction_strategies import UNABLE_TO_DOWNLOAD_OK_BUTTON

        # Store page source for diagnostics
        filepath = store_page_source(self.driver.page_source, "unable_to_download_dialog")
        logger.info(f"Stored unable to download dialog page source at: {filepath}")

        # Save screenshot for visual debugging
        screenshot_path = os.path.join(self.screenshots_dir, "unable_to_download_dialog.png")
        self.driver.save_screenshot(screenshot_path)
        logger.info(f"Saved screenshot to {screenshot_path}")

        # Get the error message text
        error_message = "Unable to download the book"
        try:
            message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
            if message_element and message_element.is_displayed():
                error_message = message_element.text
                logger.info(f"Unable to Download dialog message: {error_message}")
        except NoSuchElementException:
            logger.debug("Could not get error message text from dialog")

        # Click the OK button to dismiss the dialog
        ok_clicked = False
        for strategy, locator in UNABLE_TO_DOWNLOAD_OK_BUTTON:
            try:
                button = self.driver.find_element(strategy, locator)
                if button.is_displayed():
                    button.click()
                    logger.info("Clicked OK button on Unable to Download dialog")
                    ok_clicked = True
                    time.sleep(1)  # Wait for dialog to dismiss
                    break
            except NoSuchElementException:
                continue

        if not ok_clicked:
            logger.warning("Could not click OK button on Unable to Download dialog")

        # Return error information
        return {
            "success": False,
            "error": "unable_to_download",
            "error_message": error_message,
            "book_title": book_title,
        }
