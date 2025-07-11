import logging
from typing import Dict, Optional, Tuple, Union

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from server.logging_config import store_page_source
from views.common.dialog_strategies import (
    APP_NOT_RESPONDING_DIALOG_IDENTIFIERS,
    DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS,
    READ_AND_LISTEN_CLOSE_BUTTON,
    READ_AND_LISTEN_DIALOG_IDENTIFIERS,
    VIEWING_FULL_SCREEN_DIALOG_IDENTIFIERS,
    VIEWING_FULL_SCREEN_GOT_IT_BUTTON,
)
from views.library.interaction_strategies import INVALID_ITEM_DIALOG_BUTTONS
from views.library.view_strategies import INVALID_ITEM_DIALOG_IDENTIFIERS

logger = logging.getLogger(__name__)


class DialogHandler:
    """Centralized handler for detecting and interacting with dialogs.

    This class provides methods to check for common dialogs that might appear
    across the application, especially when in AlertActivity which puts
    the app in an UNKNOWN state.
    """

    def __init__(self, driver):
        self.driver = driver

    def check_for_invalid_item_dialog(self, book_title=None, context=""):
        """Check for and handle the 'Invalid Item' dialog.

        Args:
            book_title: Optional title of the book being accessed
            context: Context description for logging (e.g., "after clicking book")

        Returns:
            bool: True if dialog was found and handled, False otherwise
        """
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
            logger.error(f"Error in check_for_invalid_item_dialog: {e}", exc_info=True)
            return False

    def check_for_app_not_responding_dialog(self):
        """Check for and handle the 'App Not Responding' dialog.

        Returns:
            bool: True if dialog was found and handled (by clicking 'Wait'),
                False otherwise
        """
        try:
            for strategy, locator in APP_NOT_RESPONDING_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info("Detected 'App Not Responding' dialog")

                        # Try to click the "Wait" button
                        try:
                            wait_btn = self.driver.find_element(
                                AppiumBy.XPATH,
                                "//android.widget.Button[@resource-id='android:id/aerr_wait' and @text='Wait']",
                            )
                            wait_btn.click()
                            logger.info("Clicked 'Wait' button on App Not Responding dialog")
                            return True
                        except Exception as btn_error:
                            logger.error(f"Failed to click 'Wait' button: {btn_error}", exc_info=True)

                        return True  # Dialog was detected, even if handling failed
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for App Not Responding dialog: {e}")

            return False
        except Exception as e:
            logger.error(f"Error in check_for_app_not_responding_dialog: {e}", exc_info=True)
            return False

    def check_for_read_and_listen_dialog(self):
        """Check for and handle the 'Read and Listen' dialog.

        Returns:
            bool: True if dialog was found and handled (by clicking the X button),
                False otherwise
        """
        try:
            for strategy, locator in READ_AND_LISTEN_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info("Found 'Read and Listen' dialog")

                        # Store page source for diagnostics
                        store_page_source(
                            self.driver.page_source,
                            "read_and_listen_dialog_detected",
                        )

                        # Click the X button
                        x_clicked = False
                        for btn_strategy, btn_locator in READ_AND_LISTEN_CLOSE_BUTTON:
                            try:
                                x_btn = self.driver.find_element(btn_strategy, btn_locator)
                                if x_btn.is_displayed():
                                    x_btn.click()
                                    logger.info("Clicked X button on 'Read and Listen' dialog")
                                    x_clicked = True
                                    break
                            except:
                                continue

                        if not x_clicked:
                            logger.warning("Could not click X button on 'Read and Listen' dialog")

                        # Return True to indicate dialog was found and handled
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for 'Read and Listen' dialog: {e}")

            # Dialog not found
            return False
        except Exception as e:
            logger.error(f"Error in check_for_read_and_listen_dialog: {e}", exc_info=True)
            return False

    def check_for_viewing_full_screen_dialog(self):
        """Check for and handle the 'Viewing full screen' dialog.

        Returns:
            bool: True if dialog was found and handled (by clicking 'Got it'),
                False otherwise
        """
        try:
            for strategy, locator in VIEWING_FULL_SCREEN_DIALOG_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element.is_displayed():
                        logger.info("Found 'Viewing full screen' dialog")

                        # Store page source for diagnostics
                        store_page_source(
                            self.driver.page_source,
                            "viewing_full_screen_dialog_detected",
                        )

                        # Click the "Got it" button
                        got_it_clicked = False
                        for btn_strategy, btn_locator in VIEWING_FULL_SCREEN_GOT_IT_BUTTON:
                            try:
                                got_it_btn = self.driver.find_element(btn_strategy, btn_locator)
                                if got_it_btn.is_displayed():
                                    got_it_btn.click()
                                    logger.info("Clicked 'Got it' button on 'Viewing full screen' dialog")
                                    got_it_clicked = True
                                    break
                            except:
                                continue

                        if not got_it_clicked:
                            logger.warning("Could not click 'Got it' button on 'Viewing full screen' dialog")

                        # Return True to indicate dialog was found and handled
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking for 'Viewing full screen' dialog: {e}")

            # Dialog not found
            return False
        except Exception as e:
            logger.error(f"Error in check_for_viewing_full_screen_dialog: {e}", exc_info=True)
            return False

    def check_all_dialogs(self, book_title=None, context=""):
        """Check for all known dialogs and handle them appropriately.

        Args:
            book_title: Optional title of the book being accessed
            context: Context description for logging

        Returns:
            Tuple[bool, str]: (handled, dialog_type) where handled is True if a dialog
                was found and handled, and dialog_type is a string description of
                which dialog was handled ('invalid_item', 'app_not_responding', etc.)
                or None if no dialog was handled.
        """
        # Check for Invalid Item dialog
        if self.check_for_invalid_item_dialog(book_title, context):
            return True, "invalid_item"

        # Check for App Not Responding dialog
        if self.check_for_app_not_responding_dialog():
            return True, "app_not_responding"

        # Check for Read and Listen dialog
        if self.check_for_read_and_listen_dialog():
            return True, "read_and_listen"

        # Check for Viewing full screen dialog
        if self.check_for_viewing_full_screen_dialog():
            return True, "viewing_full_screen"

        # Add checks for other dialogs as needed

        # No dialogs handled
        return False, None
