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
from views.view_options.interaction_strategies import VIEW_OPTIONS_DONE_STRATEGIES
from views.view_options.view_strategies import VIEW_OPTIONS_MENU_STATE_STRATEGIES

logger = logging.getLogger(__name__)


class LibraryHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _is_library_tab_selected(self):
        """Check if the library tab is currently selected."""
        logger.info("Checking if library tab is selected...")

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
                            logger.info(f"Found library tab with '{attr}' in {child_by}")
                            return True
                else:  # Simple strategy
                    by, value = strategy
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
                        logger.info(f"Found library tab with strategy: {by}")
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
                            for child_strategy, child_locator in LIBRARY_TAB_CHILD_SELECTION_STRATEGIES:
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
            logger.info(
                f"Grid/List view dialog is{''.join(' open' if is_dialog_open else ' not open')} ({identifiers_found} identifiers found)"
            )

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
                logger.info("Successfully handled Grid/List view dialog")
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
                logger.info("Already on library tab")
                return True

            # Try to find the library tab directly using identifiers
            for strategy, locator in LIBRARY_TAB_IDENTIFIERS:
                try:
                    library_tab = self.driver.find_element(strategy, locator)
                    logger.info(f"Found Library tab using {strategy}")
                    library_tab.click()
                    logger.info("Clicked Library tab")
                    time.sleep(1)  # Wait for tab switch animation
                    # Verify we're in library view
                    if self._is_library_tab_selected():
                        logger.info("Successfully switched to library tab")
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

    def switch_to_list_view(self):
        """Switch to list view if not already in it"""
        try:
            # First check if the Grid/List view dialog is already open
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is already open, handling it directly")
                return self.handle_grid_list_view_dialog()

            # Check if we're already in list view
            if self._is_list_view():
                logger.info("Already in list view")
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
                logger.info("Grid/List view dialog is not open, nothing to handle.")
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

    def _scroll_through_library(self, target_title: str = None):
        """Scroll through library collecting book info, optionally looking for a specific title.

        Args:
            target_title: Optional title to search for. If provided, returns early when found.

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

            while True:
                # Log page source for debugging
                filepath = store_page_source(self.driver.page_source, "library_view")
                logger.info(f"Stored library view page source at: {filepath}")

                # Find all book containers on current screen
                # PRIMARY APPROACH: First directly find all title elements
                containers = []
                try:
                    # Look specifically for title elements
                    title_elements = self.driver.find_elements(
                        AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                    )
                    logger.info(f"Found {len(title_elements)} title elements directly")
                    
                    # Convert these title elements to containers
                    for i, title in enumerate(title_elements):
                        try:
                            logger.info(f"Direct title {i+1}: '{title.text}'")
                            # For each title, use a different approach to get the book container
                            # Instead of searching for parents, we'll create synthetic containers
                            # and use the title element directly for metadata extraction
                            
                            # Create a book "wrapper" for each title element
                            book_wrapper = {
                                "element": title,
                                "title_text": title.text,
                                # Add additional methods that the container would have
                                "find_elements": lambda by, locator: title.find_elements(by, locator) if by == AppiumBy.ID and locator == "com.amazon.kindle:id/lib_book_row_title" else [],
                                "get_attribute": lambda attr: title.get_attribute(attr) if attr != "content-desc" else f"{title.text}, , Book not downloaded.,"
                            }
                            
                            # Now try to find the actual container through a direct query
                            try:
                                # Try to find button containing this title text
                                escaped_text = title.text.replace("'", "\\'")
                                button = self.driver.find_element(
                                    AppiumBy.XPATH, 
                                    f"//android.widget.Button[contains(@content-desc, '{escaped_text}')]"
                                )
                                # If found, use the actual button
                                containers.append(button)
                                logger.info(f"Found actual container for '{title.text}'")
                            except Exception:
                                # If can't find actual container, use our synthetic wrapper
                                containers.append(book_wrapper)
                                logger.info(f"Using synthetic container for '{title.text}'")
                        except Exception as e:
                            logger.error(f"Error processing title '{title.text}': {e}")
                    
                    logger.info(f"Created {len(containers)} containers from title elements")
                    
                    # Also log RecyclerView info for debugging
                    try:
                        recycler_view = self.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/recycler_view")
                        all_items = recycler_view.find_elements(AppiumBy.XPATH, ".//*")
                        logger.info(f"RecyclerView contains {len(all_items)} total elements")
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
                        for container_strategy, container_locator in BOOK_METADATA_IDENTIFIERS["container"][1:]:
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

                # Process each container
                for container in containers:
                    try:
                        book_info = {"title": None, "progress": None, "size": None, "author": None}
                        
                        # Log container attributes for debugging
                        try:
                            # Handle both regular containers and our synthetic wrappers
                            if isinstance(container, dict) and "title_text" in container:
                                # This is a synthetic wrapper - create a synthetic content-desc
                                container_desc = f"{container['title_text']}, , Book not downloaded.,"
                                container_class = "synthetic-wrapper"
                                container_id = "N/A"
                                # Pre-fill the book title since we already know it
                                book_info["title"] = container["title_text"]
                                logger.info(f"Processing synthetic container for: {container['title_text']}")
                            else:
                                # This is a regular container element
                                container_desc = container.get_attribute("content-desc")
                                container_class = container.get_attribute("class")
                                container_id = container.get_attribute("resource-id")
                                logger.info(f"Processing container: class={container_class}, id={container_id}, desc={container_desc}")
                        except Exception as e:
                            logger.error(f"Error getting container attributes: {e}")

                        # Extract metadata using strategies
                        for field in ["title", "progress", "size", "author"]:
                            # Try to find elements directly in the container first
                            for strategy, locator in BOOK_METADATA_IDENTIFIERS[field]:
                                try:
                                    # Check if we're dealing with a synthetic wrapper
                                    if isinstance(container, dict) and "title_text" in container:
                                        # For synthetic wrappers, we handle fields specially
                                        if field == "title" and book_info["title"]:
                                            # Title is already set, skip this strategy
                                            break
                                        elif field == "author" and container_desc:
                                            # Try to extract author from content-desc
                                            parts = container_desc.split(',')
                                            if len(parts) > 1 and parts[1].strip():
                                                author = parts[1].strip()
                                                logger.info(f"Extracted author from synthetic wrapper: {author}")
                                                book_info["author"] = author
                                                break
                                        # For other fields or if author extraction failed, continue with next strategy
                                        continue
                                    
                                    # For direct elements, use find_element with a relative XPath
                                    relative_locator = (
                                        f".{locator}" if strategy == AppiumBy.XPATH else locator
                                    )
                                    elements = container.find_elements(strategy, relative_locator)
                                    if elements:
                                        # For title field, always log at INFO level
                                        if field == "title":
                                            logger.info(f"Found {field}: {elements[0].text}")
                                        else:
                                            logger.debug(f"Found {field}: {elements[0].text}")
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
                            if normalized_target and self._title_match(book_info["title"], target_title):
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
                                        if self._title_match(book_info["title"], target_title):
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
                                logger.info(f"Found book: {book_info}")
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

                # If we've found no new books on this screen, we need to double-check
                if not new_books_found:
                    logger.info("No new books found on this screen, doing a double-check")
                    # Double-check by directly looking for titles that might not have been processed
                    try:
                        title_elements = self.driver.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                        )
                        current_screen_titles = [el.text for el in title_elements]
                        logger.info(f"Double-check found {len(title_elements)} title elements: {current_screen_titles}")
                        
                        # If all these titles are already seen, then we can safely stop
                        new_unseen_titles = [t for t in current_screen_titles if t and t not in seen_titles]
                        if new_unseen_titles:
                            logger.info(f"Found {len(new_unseen_titles)} unseen titles in direct check: {new_unseen_titles}")
                            
                            # Add these titles to our seen set and create simple book entries for them
                            for new_title in new_unseen_titles:
                                seen_titles.add(new_title)
                                books.append({"title": new_title, "progress": None, "size": None, "author": None})
                                logger.info(f"Added book from direct check: {new_title}")
                            
                            # Update our flag since we found new books
                            new_books_found = True
                        else:
                            logger.info("Double-check confirms no new books, stopping scroll")
                            break
                    except Exception as e:
                        logger.error(f"Error during double-check for titles: {e}")
                        break
                else:
                    # We found new books on this screen - log them
                    logger.info(f"Found {len([b for b in books if b.get('title') in (seen_titles - previous_titles)])} new books on this screen")

                # At this point, if nothing new was found after our double-check, or if we're seeing exactly the same books, stop
                if not new_books_found or seen_titles == previous_titles:
                    logger.info("No progress in finding new books, stopping scroll")
                    break

                # Scroll down to see more books
                # Log visible elements before scrolling
                try:
                    logger.info("About to scroll, current visible titles:")
                    visible_titles = self.driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title")
                    for i, title in enumerate(visible_titles):
                        logger.info(f"Pre-scroll visible title {i+1}: '{title.text}'")
                except Exception as e:
                    logger.error(f"Error logging pre-scroll titles: {e}")
                
                # Perform scroll
                self.driver.swipe(screen_size["width"] // 2, start_y, screen_size["width"] // 2, end_y, 1000)
                time.sleep(1)  # Wait for scroll to complete

            logger.info(f"Found total of {len(books)} unique books")

            # If we were looking for a specific book but didn't find it
            if target_title:
                # Check if this book was found but we couldn't grab the container
                found_matching_title = False
                for book in books:
                    if book.get("title") and self._title_match(book["title"], target_title):
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

            logger.info("No sign-in button detected in library view")
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

    def get_book_titles(self):
        """Get a list of all books in the library with their metadata."""
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
                return []

            # Check if we need to sign in
            if self.check_for_sign_in_button():
                logger.warning("Library view shows sign-in button - authentication required")
                return None  # Return None to indicate authentication needed

            # Check if Grid/List view dialog is open after navigating to library
            if self._is_grid_list_view_dialog_open():
                logger.info("Grid/List view dialog is open after navigation, handling it")
                if not self.handle_grid_list_view_dialog():
                    logger.error("Failed to handle Grid/List view dialog")
                    # Try to continue anyway

            # Check if we're in grid view and switch to list view if needed
            if self._is_grid_view():
                logger.info("Detected grid view, switching to list view")
                if not self.switch_to_list_view():
                    logger.error("Failed to switch to list view")
                    return []
                logger.info("Successfully switched to list view")

            # Scroll to top of list
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            return self._scroll_through_library()

        except Exception as e:
            logger.error(f"Error getting book titles: {e}")
            return []

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

        # Log original title for debugging
        # logger.debug(f"Normalizing title: '{title}'")

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

        # Log normalized title for debugging
        # logger.debug(f"Normalized to: '{normalized}'")

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

    def _find_book_by_partial_match(self, book_title: str):
        """
        Fallback method to find a book by attempting various partial matching strategies.
        Used when normal title matching fails.

        Returns:
            Tuple of (parent_container, button, book_info) or (None, None, None)
        """
        logger.info(f"Attempting to find book by partial matching: '{book_title}'")

        try:
            # Try to find books with similar titles first
            all_books = self._scroll_through_library()

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

    def find_book(self, book_title: str) -> bool:
        """Find and click a book button by title. If the book isn't downloaded, initiate download and wait for completion."""
        try:
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
            if not self.scroll_to_list_top():
                logger.warning("Failed to scroll to top of list, continuing anyway...")

            # Search for the book
            parent_container, button, book_info = self._scroll_through_library(book_title)

            # If standard search failed, try partial matching as fallback
            if not parent_container:
                logger.info(f"Standard search failed for '{book_title}', trying partial matching fallback")
                parent_container, button, book_info = self._find_book_by_partial_match(book_title)

                if not parent_container:
                    logger.error(f"Failed to find book '{book_title}' using all search methods")
                    return False

                logger.info(f"Found book using partial match fallback: {book_info}")

            # Check download status and handle download if needed
            content_desc = parent_container.get_attribute("content-desc")
            logger.info(f"Book content description: {content_desc}")
            store_page_source(self.driver.page_source, "library_view_book_info")

            if "Book not downloaded" in content_desc:
                logger.info("Book is not downloaded yet, initiating download...")
                button.click()
                logger.info("Clicked book to start download")

                # Wait for download to complete (up to 60 seconds)
                max_attempts = 60
                for attempt in range(max_attempts):
                    try:
                        # Re-find the parent container since the page might have refreshed
                        # Using more reliable XPath that handles apostrophes better
                        title_text = book_info["title"]

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

                        parent_container = self.driver.find_element(AppiumBy.XPATH, xpath)
                        content_desc = parent_container.get_attribute("content-desc")
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
                                    AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
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

                        time.sleep(1)
                    except Exception as e:
                        logger.error(f"Error checking download status: {e}")
                        time.sleep(1)
                        continue

                logger.error("Timed out waiting for book to download")
                return False

            # For already downloaded books, just click and verify
            logger.info(f"Found downloaded book: {book_info.get('title', 'Unknown title')}")
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

            # Find and click the book button
            if not self.find_book(book_title):
                logger.error(f"Failed to find book: {book_title}")
                return False

            logger.info(f"Successfully clicked book: {book_title}")

            # Wait for reading view to load
            try:
                logger.info("Waiting for reading view to load...")
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(READER_DRAWER_LAYOUT_IDENTIFIERS[0])
                )
                logger.info("Reading view loaded")
                return True
            except Exception as e:
                filepath = store_page_source(self.driver.page_source, "unknown_library_timeout")
                logger.info(f"Stored unknown library timeout page source at: {filepath}")
                logger.error(f"Failed to wait for reading view: {e}")

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

                    # Check for "Title Not Available" dialog first
                    for strategy, locator in TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS:
                        try:
                            element = self.driver.find_element(strategy, locator)
                            if element and element.is_displayed():
                                # Store the dialog for debugging
                                filepath = store_page_source(
                                    self.driver.page_source, "title_not_available_dialog"
                                )

                                error_text = "Title Not Available"
                                try:
                                    # Try to get the message text if available
                                    message_element = self.driver.find_element(
                                        AppiumBy.ID, "android:id/message"
                                    )
                                    if message_element and message_element.is_displayed():
                                        error_text = f"Title Not Available: {message_element.text}"
                                except:
                                    pass

                                logger.error(f"Title Not Available dialog found: {error_text}")

                                # Try to click the Cancel button to dismiss the dialog
                                try:
                                    for btn_strategy, btn_locator in TITLE_NOT_AVAILABLE_DIALOG_BUTTONS:
                                        try:
                                            cancel_button = self.driver.find_element(
                                                btn_strategy, btn_locator
                                            )
                                            if cancel_button and cancel_button.is_displayed():
                                                cancel_button.click()
                                                logger.info(
                                                    "Clicked Cancel button on Title Not Available dialog"
                                                )
                                                break
                                        except:
                                            pass
                                except:
                                    logger.warning(
                                        "Failed to click Cancel button on Title Not Available dialog"
                                    )

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
                                logger.info(
                                    f"Download Limit dialog found after timeout: {strategy}={locator}"
                                )
                                return True  # ReaderHandler will handle the dialog
                        except:
                            pass

                    # Check for error text
                    for strategy, locator in DOWNLOAD_LIMIT_ERROR_TEXT:
                        try:
                            element = self.driver.find_element(strategy, locator)
                            if element and element.is_displayed():
                                logger.info(
                                    f"Download Limit error text found after timeout: {strategy}={locator}"
                                )
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

                    logger.info("No known dialogs found after explicit check")

                except Exception as dialog_e:
                    logger.error(f"Error checking for known dialogs: {dialog_e}")

                # We didn't find any expected dialogs, so return failure
                return False

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error opening book: {e}")
            return False

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
                        EC.presence_of_element_located(WEBVIEW_IDENTIFIERS[0])
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

    def _dump_library_view(self):
        """Dump the library view for debugging"""
        try:
            screenshot_path = os.path.join(self.screenshots_dir, "library_view.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved library view screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save library view screenshot: {e}")

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
