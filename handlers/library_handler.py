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
        self.scroll_handler = LibraryHandlerScroll(driver)

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

            # Check for LIST_VIEW_OPTION_STRATEGIES
            for strategy, locator in LIST_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found List view option: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue

            # Check for GRID_VIEW_OPTION_STRATEGIES
            for strategy, locator in GRID_VIEW_OPTION_STRATEGIES:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info(f"Found Grid view option: {strategy}={locator}")
                        identifiers_found += 1
                except NoSuchElementException:
                    continue

            # Also check for specific view type header text
            try:
                header = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/view_type_header")
                if header.is_displayed() and header.text == "View":
                    logger.info("Found View type header with text 'View'")
                    identifiers_found += 1
            except NoSuchElementException:
                pass

            # If we found at least 2 of the identifying elements, we're confident it's the Grid/List dialog
            is_dialog_open = identifiers_found >= 2

            # Capture a screenshot and page source for debugging
            if is_dialog_open:
                store_page_source(self.driver.page_source, "grid_list_dialog_open")
                screenshot_path = os.path.join(self.screenshots_dir, "grid_list_dialog.png")
                self.driver.save_screenshot(screenshot_path)

            return is_dialog_open
        except Exception as e:
            logger.error(f"Error checking for Grid/List view dialog: {e}")
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
                    logger.error("Failed to handle Grid/List view dialog")
                    return False
                time.sleep(0.5)  # Wait for dialog to close

            # Check if view options menu is open and close it if needed
            if self._is_view_options_menu_open():
                logger.info("View options menu is open, closing it first")
                if not self._close_menu():
                    logger.error("Failed to close view options menu")
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

            logger.error("Failed to find Library tab with any strategy")
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "failed_library_tab")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "failed_library_tab.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}")
            return False
        except Exception as e:
            logger.error(f"Error navigating to library: {e}")
            # Save page source for debugging
            try:
                source = self.driver.page_source
                xml_path = store_page_source(source, "library_navigation_error")
                # Save screenshot
                screenshot_path = os.path.join(self.screenshots_dir, "library_navigation_error.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved diagnostics: XML={xml_path}, Screenshot={screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save diagnostics: {screenshot_error}")
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
            logger.error(f"Error checking grid view: {e}")
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
            logger.error(f"Error checking list view: {e}")
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
            if is_search:
                logger.info(f"Detected search interface with {search_indicators} indicators")
                # Save page source for debugging
                store_page_source(self.driver.page_source, "search_interface_detected")
            return is_search

        except Exception as e:
            logger.error(f"Error checking for search interface: {e}")
            return False

    def switch_to_list_view(self):
        """Switch to list view if not already in it"""
        try:
            # First check if we're in search interface
            if self._is_in_search_interface():
                logger.info("Detected we're in search interface, exiting search mode first")
                if not self.search_handler._exit_search_mode():
                    logger.error("Failed to exit search mode")
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
                return True

            # Force update state machine to ensure we're recognized as being in LIBRARY state
            # This is crucial to prevent auth_handler from trying to enter email after view changes
            if hasattr(self.driver, "automator") and self.driver.automator:
                automator = self.driver.automator
                if hasattr(automator, "state_machine") and automator.state_machine:
                    logger.info("Ensuring state machine recognizes LIBRARY state before view change")
                    automator.state_machine.update_current_state()

            # If we're in grid view, we need to open the view options menu
            if self._is_grid_view():
                logger.info("Currently in grid view, switching to list view")

                # Store page source for debugging
                filepath = store_page_source(self.driver.page_source, "grid_view_detected")
                logger.info(f"Stored grid view page source at: {filepath}")

                # Check again for search interface (could be misdetected as grid view)
                if self._is_in_search_interface():
                    logger.info(
                        "Actually in search interface even though grid view was detected, exiting search mode"
                    )
                    if not self.search_handler._exit_search_mode():
                        logger.error("Failed to exit search mode")
                        return False
                    logger.info("Successfully exited search mode")
                    time.sleep(1)  # Give UI time to settle
                    return True

                # Click view options button
                button_clicked = False
                for strategy, locator in VIEW_OPTIONS_BUTTON_STRATEGIES:
                    try:
                        button = self.driver.find_element(strategy, locator)
                        button.click()
                        logger.info(f"Clicked view options button using {strategy}: {locator}")
                        time.sleep(1)  # Increased wait for menu animation
                        button_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click view options button with strategy {strategy}: {e}")
                        continue

                if not button_clicked:
                    logger.error("Failed to click any view options button")
                    return False

                # After clicking the view options button, check if Grid/List dialog is open
                # and handle it with the dedicated method
                if self._is_grid_list_view_dialog_open():
                    logger.info("Grid/List view dialog opened, handling it")
                    if not self.handle_grid_list_view_dialog():
                        logger.error("Failed to handle Grid/List view dialog")
                        return False

                    # After handling the dialog, verify we're in list view
                    if self._is_list_view():
                        logger.info("Successfully switched to list view after handling dialog")
                        return True
                    else:
                        logger.error("Still not in list view after handling dialog")
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
                    logger.error("View options menu did not open properly")
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
                    logger.error("Failed to click list view option")
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
                    logger.error("Failed to click DONE button")
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
                    logger.error("Timed out waiting for list view")
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
                        logger.error("Failed to handle Grid/List view dialog")
                        return False
                else:
                    logger.warning("Neither in grid view nor list view, unable to determine current state")
                    filepath = store_page_source(self.driver.page_source, "unknown_view_state")
                    logger.info(f"Stored unknown view state page source at: {filepath}")
                    return False

        except Exception as e:
            logger.error(f"Error switching to list view: {e}")
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
            logger.error(f"Error closing menu: {e}")
            return False

    def handle_grid_list_view_dialog(self):
        """Handle the Grid/List view selection dialog by selecting List view and clicking DONE.

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
                    logger.error(f"Error clicking List view option: {e}")
                    continue

            # If we couldn't click the List view option, it might already be selected or not found
            if not list_option_clicked:
                logger.warning(
                    "Could not click List view option, it might already be selected or not available"
                )

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
                    logger.error(f"Error clicking DONE button: {e}")
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
                        logger.error(f"Error clicking DONE button with alternative strategy: {e}")
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
                        logger.error(f"Error tapping at screen coordinates: {e}")

            # Verify the dialog was closed
            if self._is_grid_list_view_dialog_open():
                logger.error("Failed to close Grid/List view dialog")
                return False

            logger.info("Successfully handled Grid/List view selection dialog")
            return True

        except Exception as e:
            logger.error(f"Error handling Grid/List view selection dialog: {e}")
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
            logger.error(f"Error checking for sign-in button: {e}")
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

            logger.error("Could not find sign-in button to click")
            return False

        except Exception as e:
            logger.error(f"Error handling library sign-in: {e}")
            return False

    def get_book_titles(self, callback=None):
        """Get a list of all books in the library with their metadata.

        Args:
            callback: Optional callback function that will receive books as they're found.
                     If provided, books will be streamed to this function in batches.
                     The callback should accept a list of book dictionaries as its first argument,
                     and optional kwargs for control messages.

        Returns:
            List of book dictionaries, or None if authentication is required.
            If callback is provided, results are also streamed to the callback as they're found.
        """
        try:
            # Check if Grid/List view dialog is open and handle it first
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is open at the start, handling it first")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog")
                    # Continue anyway, as navigate_to_library will try again

            # Ensure we're in the library view
            if not self.navigate_to_library():
                logger.error("Failed to navigate to library")
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
                    logger.error("Failed to handle Grid/List view dialog")
                    # Try to continue anyway

            # Check if a book has been selected (happens from inadvertent long press)
            if self.scroll_handler.is_in_book_selection_mode():
                logger.info("Book selection mode detected, exiting selection mode first")
                if not self.scroll_handler.exit_book_selection_mode():
                    logger.error("Failed to exit book selection mode")
                    if callback:
                        callback(None, error="Failed to exit book selection mode")
                    return []
                logger.info("Successfully exited book selection mode")

            # Check if we're in search results interface (can be misidentified as library)
            if self._is_in_search_interface():
                logger.info("Detected we're in search results interface, exiting search mode first")
                if not self.search_handler._exit_search_mode():
                    logger.error("Failed to exit search mode")
                    if callback:
                        callback(None, error="Failed to exit search mode")
                    return []
                logger.info("Successfully exited search mode")
                time.sleep(1)  # Give UI time to settle

            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    if callback:
                        callback(None, error="Failed to switch to list view")
                    return []
                logger.info("Successfully switched to list view")

            # Scroll to top of list
            if not self.scroll_handler.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Use the scroll handler's method to get all books
            # If callback is provided, pass it to the scroll handler for streaming
            return self.scroll_handler._scroll_through_library(callback=callback)

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            if callback:
                callback(None, error=str(e))
            return []

    def _handle_book_click_and_transition(self, parent_container, button, book_info, book_title):
        """Handle clicking a book, waiting for download if needed, and transitioning to reading view.

        This is a shared method used after finding a book through various methods (visible on screen,
        search, or scrolling). It handles:
        1. Checking if the book needs to be downloaded
        2. Waiting for download to complete if needed
        3. Clicking the book and verifying transition to reading view

        Args:
            parent_container: The parent element containing the book
            button: The clickable element for the book
            book_info: Dictionary containing book metadata
            book_title: The title of the book (used for logging and verification)

        Returns:
            bool: True if book was successfully opened, False otherwise
        """
        try:
            # Check download status and handle download if needed
            content_desc = parent_container.get_attribute("content-desc") or ""
            logger.info(f"Book content description: {content_desc}")
            store_page_source(self.driver.page_source, "library_view_book_info")

            if "Book not downloaded" in content_desc:
                logger.info("Book is not downloaded yet, initiating download...")
                button.click()
                logger.info("Clicked book to start download")

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

                # Wait for download to complete (max 30 seconds)
                max_attempts = 30
                for attempt in range(max_attempts):
                    try:
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
                                parent_container.click()
                                logger.info("Clicked book button after download")

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
                                    parent_container.click()
                                    logger.info("Clicked book again")
                                except NoSuchElementException:
                                    logger.info("Successfully left library view")

                                return True

                            # If we see an error in the content description, abort
                            if any(error in content_desc.lower() for error in ["error", "failed"]):
                                logger.error(f"Download failed: {content_desc}")
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
                        logger.error(f"Error checking download status: {e}")

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
                    logger.error("Timed out waiting for book to download and still in library view")
                    return False
                except NoSuchElementException:
                    logger.info("Left library view after timeout - book likely opened anyway")
                    return True

            # For already downloaded books, just click and verify
            logger.info(f"Found downloaded book: {book_info.get('title', book_title)}")
            button.click()
            logger.info("Clicked book button")

            # Wait for library view to disappear (we've left it)
            try:
                WebDriverWait(self.driver, 5).until_not(
                    EC.presence_of_element_located((AppiumBy.ID, "com.amazon.kindle:id/library_root_view"))
                )
                logger.info("Successfully left library view")
                return True
            except TimeoutException:
                logger.error("Still in library view after clicking book")
                # Try clicking one more time
                button.click()

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
                    logger.error("Still in library view after second click, trying with parent container")
                    # Try clicking the parent container instead
                    parent_container.click()

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
                        logger.error("Failed to leave library view after multiple attempts")
                        return False

        except Exception as e:
            logger.error(f"Error handling book click and transition: {e}")
            traceback.print_exc()
            return False

    def find_book(self, book_title: str) -> bool:
        """Find and click a book button by title. If the book isn't downloaded, initiate download and wait for completion."""
        try:
            # Try using the search box first to find the book
            # search_result = self.search_handler._search_for_book(book_title)
            search_result = False  # TODO: Remove this once done testing scrolling method

            if search_result:
                parent_container, button, book_info = search_result
                logger.info(f"Successfully found book '{book_title}' using search function: {book_info}")

                # Handle clicking the book and check if we successfully exit library view
                return self._handle_book_click_and_transition(parent_container, button, book_info, book_title)
            else:
                logger.info(f"Search function didn't find '{book_title}', falling back to scrolling method")

            # Fallback: Search for the book by scrolling

            # First check if we're in the Grid/List view dialog and handle it
            if self._is_grid_list_view_dialog_open():
                logger.info("Detected Grid/List view dialog is open, handling it first")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog")
                    return False
                logger.info("Successfully handled Grid/List view dialog")
                time.sleep(1)  # Wait for UI to stabilize

            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    return False
                logger.info("Successfully switched to list view")

            # Scroll to top first
            if not self.scroll_handler.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Provide the title_match_func to scroll_through_library
            parent_container, button, book_info = self.scroll_handler._scroll_through_library(
                book_title, title_match_func=self.search_handler._title_match
            )

            # If standard search failed, try partial matching as fallback
            if not parent_container:
                logger.info(f"Standard search failed for '{book_title}', trying partial matching fallback")
                parent_container, button, book_info = self.search_handler._find_book_by_partial_match(
                    book_title,
                    scroll_through_library_func=lambda: self.scroll_handler._scroll_through_library(),
                )

                if not parent_container:
                    logger.error(f"Failed to find book '{book_title}' using all search methods")
                    return False

                logger.info(f"Found book using partial match fallback: {book_info}")

            # Now that we've found the book, handle clicking it and transition
            return self._handle_book_click_and_transition(parent_container, button, book_info, book_title)

        except Exception as e:
            logger.error(f"Error finding book: {e}")
            traceback.print_exc()
            return False

    def open_book(self, book_title: str) -> bool:
        """Open a book in the library.

        Args:
            book_title (str): The title of the book to open

        Returns:
            bool: True if the book was found and opened, False otherwise
        """
        try:
            # First check if we're in the Grid/List view dialog and handle it before trying to open a book
            if self._is_grid_list_view_dialog_open():
                logger.info("Detected Grid/List view dialog is open before opening book, handling it first")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog")
                    store_page_source(self.driver.page_source, "failed_to_handle_grid_list_dialog")
                    return False
                logger.info("Successfully handled Grid/List view dialog")
                time.sleep(1)  # Wait for UI to stabilize

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

                # Wait for library view to disappear (we've left it)
                try:
                    WebDriverWait(self.driver, 5).until_not(
                        EC.presence_of_element_located(
                            (AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                        )
                    )
                    logger.info("Successfully left library view")

                    # At this point, we've left the library. Let the reader_handler do the rest
                    return self._delegate_to_reader_handler(book_title)
                except TimeoutException:
                    logger.warning("Still in library view after clicking book, trying one more time")
                    button.click()
                    logger.info("Clicked book button again")

                    # Wait again for library view to disappear
                    try:
                        WebDriverWait(self.driver, 5).until_not(
                            EC.presence_of_element_located(
                                (AppiumBy.ID, "com.amazon.kindle:id/library_root_view")
                            )
                        )
                        logger.info("Successfully left library view after second click")

                        # Now delegate to reader_handler
                        return self._delegate_to_reader_handler(book_title)
                    except TimeoutException:
                        logger.error("Failed to leave library view even after second click")
                        return False

            # If book is not already visible, proceed with search and find methods
            logger.info(f"Proceeding to search for '{book_title}'")

            # Find and click the book button
            if not self.find_book(book_title):
                logger.error(f"Failed to find book: {book_title}")
                return False

            logger.info(f"Successfully found and clicked book: {book_title}")

            # Now delegate to the reader_handler which will handle all dialogs
            return self._delegate_to_reader_handler(book_title)

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error opening book: {e}")
            return False

    def _delegate_to_reader_handler(self, book_title):
        """Delegate to the reader_handler to handle the reading view and any dialogs.

        This method is called after we've successfully clicked on a book and left the
        library view. The reader_handler will take care of dialogs like "Go to that page?",
        download limits, and other reading-related interactions.

        Args:
            book_title: The title of the book we're opening

        Returns:
            bool: True if the book was successfully opened, False otherwise
        """
        logger.info(f"Delegating to reader_handler to handle reading view for '{book_title}'")

        # Get access to the reader_handler
        if hasattr(self.driver, "automator") and hasattr(self.driver.automator, "state_machine"):
            reader_handler = self.driver.automator.state_machine.reader_handler

            if reader_handler:
                # Let the reader_handler handle the reading view dialogs
                # Note that we're NOT calling reader_handler.open_book() which would cause a circular reference
                # Instead, we're directly handling the dialogs here

                # Wait for the reading view to appear with a longer timeout
                try:
                    logger.info("Waiting for reading view to load...")
                    # Using the imported READING_VIEW_IDENTIFIERS from view_strategies

                    # Wait for any of the reading view identifiers to appear
                    WebDriverWait(self.driver, 15).until(
                        lambda x: any(
                            self._check_element_present(x, strategy, locator)
                            for strategy, locator in READING_VIEW_IDENTIFIERS
                        )
                    )
                    logger.info("Reading view loaded successfully")

                    # Now that we're in the reading view, let reader_handler handle the dialogs
                    # We use show_placemark=False to avoid showing the placemark ribbon
                    dialog_handled = reader_handler.open_book(book_title, show_placemark=False)

                    if dialog_handled:
                        logger.info(f"Reader handler successfully handled dialogs for book '{book_title}'")
                        return True
                    else:
                        logger.error(f"Reader handler failed to handle dialogs for book '{book_title}'")
                        return False

                except TimeoutException:
                    logger.error(f"Timed out waiting for reading view to appear")
                    # Check for any dialogs or error states
                    return self._handle_loading_timeout(book_title)
                except Exception as e:
                    logger.error(f"Error waiting for reading view: {e}")
                    return False
            else:
                logger.error("No reader_handler available in the state machine")
                return False
        else:
            logger.error("Cannot access automator state machine")
            return False

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
                                    f"Failed to detect reading view after handling page navigation dialog: {e}"
                                )
                                return False
                    except NoSuchElementException:
                        logger.warning("Could not find YES button on page navigation dialog")
                    except Exception as btn_e:
                        logger.error(f"Error clicking YES button: {btn_e}")
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
            bool or str: True if successfully handled, "title_not_available" if that dialog was found,
                        False otherwise
        """
        filepath = store_page_source(self.driver.page_source, "unknown_library_timeout")
        logger.info(f"Stored unknown library timeout page source at: {filepath}")
        logger.error(f"Failed to wait for reading view after clicking '{book_title}'")

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
                return True

            # Check for "Title Not Available" dialog
            for strategy, locator in TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        # Store the dialog for debugging
                        filepath = store_page_source(self.driver.page_source, "title_not_available_dialog")

                        error_text = "Title Not Available"
                        try:
                            # Try to get the message text if available
                            message_element = self.driver.find_element(AppiumBy.ID, "android:id/message")
                            if message_element and message_element.is_displayed():
                                error_text = f"Title Not Available: {message_element.text}"
                        except:
                            pass

                        logger.error(f"Title Not Available dialog found: {error_text}")

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

                        # Return a specific value to indicate this dialog was found
                        # Using string 'title_not_available' instead of True/False for disambiguation
                        return "title_not_available"
                except:
                    pass

            # Check for download limit dialog title
            for strategy, locator in DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Download Limit dialog found after timeout: {strategy}={locator}")
                        return True  # ReaderHandler will handle the dialog
                except:
                    pass

            # Check for error text
            for strategy, locator in DOWNLOAD_LIMIT_ERROR_TEXT:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        logger.info(f"Download Limit error text found after timeout: {strategy}={locator}")
                        return True  # ReaderHandler will handle the dialog
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
                return True  # ReaderHandler will handle the dialog

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
                            logger.error(f"Failed to wait for reading view after second click: {e}")

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
                logger.error(f"Error checking library view status: {e}")

            logger.info("No known dialogs found after explicit check")

        except Exception as dialog_e:
            logger.error(f"Error checking for known dialogs: {dialog_e}")

        # We didn't find any expected dialogs, so return failure
        return False

    def _dump_library_view(self):
        """Dump the library view for debugging"""
        try:
            screenshot_path = os.path.join(self.screenshots_dir, "library_view.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved library view screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save library view screenshot: {e}")
