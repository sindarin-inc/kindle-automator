"""
Navigation handler for Kindle Automator.

This module provides functionality to navigate between pages in the Kindle app,
with support for:
1. Navigating multiple pages at once
2. Previewing pages ahead or behind without changing current position
3. OCR processing of pages
"""

import logging
import os
import re
import time
from typing import Dict, Optional, Tuple, Union

from flask import request

from handlers.about_book_popover_handler import AboutBookPopoverHandler
from handlers.reader_page_handler import process_screenshot_response
from server.middleware.response_handler import get_image_path
from server.utils.ocr_utils import KindleOCR, is_base64_requested, is_ocr_requested
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class NavigationResourceHandler:
    """Handler for navigation-related requests in the Kindle Automator."""

    def __init__(self, automator, screenshots_dir: str = "screenshots"):
        """Initialize the navigation handler.

        Args:
            automator: The Kindle Automator instance.
            screenshots_dir: Directory for saving screenshots.
        """
        self.automator = automator
        self.screenshots_dir = screenshots_dir
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def navigate(
        self,
        navigate_count: int = 1,
        preview_count: int = 0,
        show_placemark: bool = False,
        use_base64: bool = False,
        perform_ocr: bool = False,
        book_title: Optional[str] = None,
        client_session_key: Optional[str] = None,
        target_position: Optional[int] = None,
        include_screenshot: bool = False,
    ) -> Tuple[Dict, int]:
        """Handle page navigation with support for multi-page navigation and preview.

        Args:
            navigate_count: Number of pages to navigate (defaults to 1).
                          Positive values navigate forward, negative values backward.
            preview_count: Number of pages to preview and then return (defaults to 0).
                         Positive values preview forward, negative values backward.
            show_placemark: Whether to show placemark in reading progress.
            use_base64: Whether to return base64 encoded image.
            perform_ocr: Whether to perform OCR on the image.
            book_title: Book title to reopen if not in reading view.
            client_session_key: Client's book session key to preserve when reopening.
            target_position: Target position for absolute navigation (if provided).

        Returns:
            Tuple of (response_data, status_code)
        """
        # Track if book needs reopening (will be set if we reopen the book)
        book_session_key_after_reopen = None

        # Determine the navigation direction from navigate_count
        direction_forward = navigate_count >= 0
        # Use absolute value for the actual navigation count
        abs_navigate_count = abs(navigate_count)

        # Similarly determine preview direction from preview_count
        preview_direction_forward = preview_count >= 0
        abs_preview_count = abs(preview_count)

        logger.info(
            f"Navigation request: navigate={navigate_count}, preview={preview_count}, "
            f"direction={'forward' if direction_forward else 'backward'}, "
            f"placemark={show_placemark}, base64={use_base64}, ocr={perform_ocr}, "
            f"book_title={book_title}"
        )

        # First check for and dismiss the About Book popover if present
        about_book_handler = AboutBookPopoverHandler(self.automator.driver)
        if about_book_handler.is_popover_present():
            logger.info("About Book popover detected at start of navigation - dismissing it")
            about_book_handler.dismiss_popover()
            # Small delay to let the popover dismiss animation complete
            time.sleep(0.5)

        # Then check for the 'last read page' dialog which indicates we're in reading view
        dialog_result = self._handle_last_read_page_dialog(click_yes_to_navigate=False)
        if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
            # Dialog found, return it to the client instead of navigating
            logger.info(
                "Found 'last read page' dialog at start of navigation - returning to client for decision"
            )

            response_data = {
                "success": True,
                "last_read_dialog": True,
                "dialog_text": dialog_result.get("dialog_text"),
                "message": "Last read page dialog detected",
            }

            # Add book_session_key if book was reopened
            if book_session_key_after_reopen:
                response_data["book_session_key"] = book_session_key_after_reopen
                response_data["book_was_reopened"] = True

            return response_data, 200

        # Check if we're in reading view using lightweight check
        if not self.automator.state_machine.is_reading_view():
            logger.warning("Not in reading view - checking if we need to reopen book")

            # If book_title is provided, try to reopen the book
            if book_title:
                logger.info(f"Book title provided: {book_title}, attempting to reopen book")

                # Get current state to understand where we are
                current_state = self.automator.state_machine.update_current_state()
                logger.info(f"Current state: {current_state}")

                # If we're in reading state, check for last read dialog before attempting to transition
                if current_state == AppState.READING:
                    # Check if we already have this book open
                    profile = self.automator.profile_manager.get_current_profile()
                    sindarin_email = profile.get("email") if profile else None

                    if sindarin_email and hasattr(self.automator, "server_ref") and self.automator.server_ref:
                        current_book = self.automator.server_ref.get_current_book(sindarin_email)
                        if current_book and current_book.lower() == book_title.lower():
                            logger.info(
                                f"Already in reading state with matching book loaded: '{book_title}' == '{current_book}'"
                            )
                        elif current_book:
                            logger.info(
                                f"In reading state but different book loaded: requested '{book_title}' != current '{current_book}'"
                            )
                        else:
                            logger.info(
                                f"In reading state but no current book tracked, requested: '{book_title}'"
                            )

                    dialog_result = self._handle_last_read_page_dialog(click_yes_to_navigate=False)
                    if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
                        # Dialog found, return it to the client instead of transitioning
                        logger.info(
                            "Found 'last read page' dialog while in reading state - returning to client for decision"
                        )

                        response_data = {
                            "success": True,
                            "last_read_dialog": True,
                            "dialog_text": dialog_result.get("dialog_text"),
                            "message": "Last read page dialog detected",
                        }

                        # Add book_session_key if book was reopened
                        if book_session_key_after_reopen:
                            response_data["book_session_key"] = book_session_key_after_reopen
                            response_data["book_was_reopened"] = True

                        return response_data, 200

                # Check if we're in an auth-required state
                if current_state.is_auth_state():
                    logger.error(
                        f"Cannot navigate - authentication required. Current state: {current_state}",
                        exc_info=True,
                    )

                    # Check if user was previously authenticated
                    profile_manager = self.automator.profile_manager
                    sindarin_email = profile_manager.get_current_profile().get("email")
                    auth_date = profile_manager.get_user_field(sindarin_email, "auth_date")

                    if auth_date:
                        # User was previously authenticated but lost auth
                        logger.warning(
                            f"User {sindarin_email} was previously authenticated on {auth_date} but is now in {current_state} - marking auth as failed"
                        )
                        profile_manager.update_auth_state(sindarin_email, authenticated=False)

                    return {
                        "error": "Authentication required",
                        "message": "Please authenticate before navigating",
                    }, 401

                # Try to transition to library first
                if self.automator.state_machine.transition_to_library() != AppState.LIBRARY:
                    logger.error("Failed to transition to library to reopen book", exc_info=True)
                    return {"error": "Failed to reach library to reopen book"}, 500

                # Now open the book
                logger.info(f"Opening book: {book_title}")
                if not self.automator.state_machine.library_handler.open_book(book_title):
                    logger.error(f"Failed to open book: {book_title}", exc_info=True)
                    return {"error": f"Failed to open book: {book_title}"}, 500

                # Wait for book to open
                time.sleep(2)

                # Verify we're now in reading view
                if not self.automator.state_machine.is_reading_view():
                    logger.error("Still not in reading view after opening book", exc_info=True)
                    return {"error": "Failed to reach reading view after opening book"}, 500

                logger.info("Successfully reopened book, now in reading view")

                # Set the session key to match the client's if provided
                from server.core.automation_server import AutomationServer

                server = AutomationServer.get_instance()
                profile = self.automator.profile_manager.get_current_profile()
                sindarin_email = profile.get("email") if profile else None

                # If client provided a session key, preserve it when reopening
                if client_session_key and sindarin_email:
                    logger.info(f"Preserving client session key {client_session_key} after reopening book")

                    # First, check if this session exists in the database
                    from database.connection import get_db
                    from database.repositories.book_session_repository import (
                        BookSessionRepository,
                    )

                    with get_db() as db_session:
                        repo = BookSessionRepository(db_session)
                        existing_session = repo.get_session(sindarin_email, book_title)

                        # Check if the client's session key matches current or previous session
                        restored_position = None
                        if existing_session:
                            if existing_session.session_key == client_session_key:
                                # Client has the current session key, use its position
                                restored_position = existing_session.position
                                logger.info(f"Found existing session with position {restored_position}")
                            elif existing_session.previous_session_key == client_session_key:
                                # Client has the previous session key, use previous position
                                restored_position = existing_session.previous_position or 0
                                logger.info(f"Found previous session with position {restored_position}")

                    # Set the book with the client's session key
                    server.set_current_book(book_title, sindarin_email, client_session_key)
                    book_session_key_after_reopen = client_session_key

                    # If we found a position to restore, set it
                    if restored_position is not None:
                        logger.info(f"Restoring position to {restored_position} after reopening book")
                        # Set the absolute position after reopening
                        server.set_position(sindarin_email, restored_position, book_title)

                        # Adjust navigation count to account for restored position
                        if target_position is not None:
                            # We've restored to restored_position, so adjust navigation
                            adjusted_navigate = target_position - restored_position
                            logger.info(
                                f"Adjusting navigation from {navigate_count} to {adjusted_navigate} (target {target_position} - restored {restored_position})"
                            )
                            navigate_count = adjusted_navigate
                            abs_navigate_count = abs(navigate_count)
                            direction_forward = navigate_count >= 0
                else:
                    book_session_key_after_reopen = server.get_book_session_key(sindarin_email)
            else:
                # No book title provided, can't recover
                logger.error("Not in reading view and no book_title provided to reopen", exc_info=True)
                return {"error": "Not in reading view. Please provide title parameter to reopen book."}, 400

        # If navigate_count is 0 and no preview is requested, just return current page info
        if navigate_count == 0 and preview_count == 0:
            # Get current page info without navigation
            progress = self.automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )

            response_data = {
                "success": True,
                "progress": progress,
                "message": "Current page info (no navigation)",
            }

            # Handle screenshot and/or OCR if requested
            if include_screenshot or perform_ocr:
                # Get the user email for unique screenshot naming
                profile = self.automator.profile_manager.get_current_profile()
                sindarin_email = profile.get("email") if profile else None
                if sindarin_email:
                    # Sanitize email for filename
                    email_safe = sindarin_email.replace("@", "_").replace(".", "_")
                    screenshot_id = f"{email_safe}_page_{int(time.time())}"
                else:
                    screenshot_id = f"page_{int(time.time())}"
                screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
                self.automator.driver.save_screenshot(screenshot_path)

                # Process the screenshot - this handles both screenshot and OCR independently
                screenshot_path = get_image_path(screenshot_id)
                screenshot_data = process_screenshot_response(
                    screenshot_id, screenshot_path, use_base64, perform_ocr
                )

                # If OCR detected time-based indicators, try to cycle to get page/location
                if perform_ocr and "progress" in screenshot_data:
                    from server.utils.ocr_utils import cycle_page_indicator_if_needed

                    progress = screenshot_data["progress"]
                    if progress and progress.get("time_left"):
                        # Try to cycle to get page/location information
                        page_text = progress.get("reading_time_indicator", "")
                        updated_progress = cycle_page_indicator_if_needed(self.automator.driver, page_text)
                        if updated_progress:
                            screenshot_data["progress"] = updated_progress

                # If only OCR was requested (not screenshot), only include OCR text in response
                if perform_ocr and not include_screenshot:
                    # Only include OCR-related fields
                    if "ocr_text" in screenshot_data:
                        response_data["ocr_text"] = screenshot_data["ocr_text"]
                    if "ocr_error" in screenshot_data:
                        response_data["ocr_error"] = screenshot_data["ocr_error"]
                    # Also include progress if page indicators were extracted
                    if "progress" in screenshot_data:
                        # Merge the OCR-extracted progress with existing progress
                        if response_data.get("progress"):
                            response_data["progress"].update(screenshot_data["progress"])
                        else:
                            response_data["progress"] = screenshot_data["progress"]
                else:
                    # Include all screenshot data
                    response_data.update(screenshot_data)

            # Add book_session_key if book was reopened
            if book_session_key_after_reopen:
                response_data["book_session_key"] = book_session_key_after_reopen
                response_data["book_was_reopened"] = True

            return response_data, 200

        # If we're doing a preview with navigate_count=0, handle it specially
        if preview_count != 0 and navigate_count == 0:
            # Check for last read page dialog again (which may appear after handling another dialog)
            dialog_result = self._handle_last_read_page_dialog(click_yes_to_navigate=False)
            if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
                # Dialog found, return it to the client instead of handling it
                logger.info("Found 'last read page' dialog during preview - returning to client for decision")

                # We don't need screenshots or page source

                # Build response with dialog info
                response_data = {
                    "success": True,
                    "last_read_dialog": True,
                    "dialog_text": dialog_result.get("dialog_text"),
                    "message": "Last read page dialog detected during preview",
                }
                # No screenshot data to add

                # Add book_session_key if book was reopened
                if book_session_key_after_reopen:
                    response_data["book_session_key"] = book_session_key_after_reopen
                    response_data["book_was_reopened"] = True

                return response_data, 200

            if preview_direction_forward:
                return self._preview_pages_forward(abs_preview_count, show_placemark)
            else:
                return self._preview_pages_backward(abs_preview_count, show_placemark)

        # First handle regular navigation
        success = self._navigate_pages(direction_forward, abs_navigate_count)

        if not success:
            return {"error": "Navigation failed"}, 500

        # After navigation, capture page info at the user's actual position (not preview position)
        # This is only needed when we're doing a preview, to get the correct page number
        navigation_page_info = None
        if success and preview_count != 0:
            navigation_page_info = self._extract_page_info_only("nav_pos")

        # If preview was requested, handle it after navigating
        preview_ocr_text = None
        if success and preview_count != 0:
            if preview_direction_forward:
                preview_success, preview_ocr_text, _ = self._preview_multiple_pages_forward(abs_preview_count)
            else:
                preview_success, preview_ocr_text, _ = self._preview_multiple_pages_backward(
                    abs_preview_count
                )

            if preview_success and preview_ocr_text:
                # Use the page info from the navigation position, NOT the preview position
                if navigation_page_info:
                    # Use the page info extracted at navigation position
                    progress = navigation_page_info
                else:
                    # Fall back to getting current page data after navigation
                    progress = self.automator.state_machine.reader_handler.get_reading_progress(
                        show_placemark=show_placemark
                    )

                # When preview is requested, we're primarily interested in the OCR text
                response_data = {"success": True, "progress": progress, "ocr_text": preview_ocr_text}
                # Add book_session_key if book was reopened
                if book_session_key_after_reopen:
                    response_data["book_session_key"] = book_session_key_after_reopen
                    response_data["book_was_reopened"] = True

                return response_data, 200

        # Standard navigation response
        # Get current page number and progress
        progress = self.automator.state_machine.reader_handler.get_reading_progress(
            show_placemark=show_placemark
        )

        response_data = {
            "success": True,
            "progress": progress,
        }

        # Handle screenshot and/or OCR if requested
        if include_screenshot or perform_ocr:
            # Save screenshot with unique ID
            # Get the user email for unique screenshot naming
            profile = self.automator.profile_manager.get_current_profile()
            sindarin_email = profile.get("email") if profile else None
            if sindarin_email:
                # Sanitize email for filename
                email_safe = sindarin_email.replace("@", "_").replace(".", "_")
                screenshot_id = f"{email_safe}_page_{int(time.time())}"
            else:
                screenshot_id = f"page_{int(time.time())}"
            time.sleep(0.5)
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.automator.driver.save_screenshot(screenshot_path)

            # Process the screenshot (either base64 encode, add URL, or OCR)
            screenshot_path = get_image_path(screenshot_id)
            screenshot_data = process_screenshot_response(
                screenshot_id, screenshot_path, use_base64, perform_ocr
            )

            # If OCR detected time-based indicators, try to cycle to get page/location
            if perform_ocr and "progress" in screenshot_data:
                from server.utils.ocr_utils import cycle_page_indicator_if_needed

                progress = screenshot_data["progress"]
                if progress and progress.get("time_left"):
                    # Try to cycle to get page/location information
                    page_text = progress.get("reading_time_indicator", "")
                    updated_progress = cycle_page_indicator_if_needed(self.automator.driver, page_text)
                    if updated_progress:
                        screenshot_data["progress"] = updated_progress

            # If only OCR was requested (not screenshot), only include OCR text in response
            if perform_ocr and not include_screenshot:
                # Only include OCR-related fields
                if "ocr_text" in screenshot_data:
                    response_data["ocr_text"] = screenshot_data["ocr_text"]
                if "ocr_error" in screenshot_data:
                    response_data["ocr_error"] = screenshot_data["ocr_error"]
                # If OCR extracted page progress, use it to override the default progress
                if "progress" in screenshot_data:
                    response_data["progress"] = screenshot_data["progress"]
            else:
                # Include all screenshot data
                response_data.update(screenshot_data)

        # Add book_session_key if book was reopened
        if book_session_key_after_reopen:
            response_data["book_session_key"] = book_session_key_after_reopen
            response_data["book_was_reopened"] = True

        return response_data, 200

    def _handle_last_read_page_dialog(self, click_yes_to_navigate=False):
        """Check for and get the 'last read page' dialog or 'Go to that location?' dialog.
        Can optionally click YES to navigate to the last read location.

        Args:
            click_yes_to_navigate (bool): If True, clicks YES to navigate user to last read location.
                                         If False, only detects the dialog without interacting.

        Returns:
            dict or bool: If click_yes_to_navigate is False and dialog is found, returns a dict with dialog info.
                        If click_yes_to_navigate is True, returns True if dialog was found and YES was clicked.
                        Returns False if dialog was not found or error occurred.
        """
        from selenium.common.exceptions import NoSuchElementException

        from views.reading.interaction_strategies import LAST_READ_PAGE_DIALOG_BUTTONS
        from views.reading.view_strategies import (
            GO_TO_LOCATION_DIALOG_IDENTIFIERS,
            LAST_READ_PAGE_DIALOG_IDENTIFIERS,
        )

        try:
            dialog_found = False
            dialog_text = None

            # Check for Last read page dialog
            for strategy, locator in LAST_READ_PAGE_DIALOG_IDENTIFIERS:
                try:
                    message = self.automator.driver.find_element(strategy, locator)
                    if message.is_displayed() and (
                        "You are currently on page" in message.text
                        or "You are currently at location" in message.text
                        or "Go to that page?" in message.text
                    ):
                        dialog_found = True
                        dialog_text = message.text
                        logger.info(f"Found 'last read page/location' dialog with text: {dialog_text}")
                        break
                except NoSuchElementException:
                    continue

            # Also check for Go to that location dialog if we didn't find the Last read page dialog
            if not dialog_found:
                for strategy, locator in GO_TO_LOCATION_DIALOG_IDENTIFIERS:
                    try:
                        message = self.automator.driver.find_element(strategy, locator)
                        if message.is_displayed() and (
                            "Go to that location?" in message.text or "Go to that page?" in message.text
                        ):
                            dialog_found = True
                            dialog_text = message.text
                            logger.info(f"Found 'Go to that location/page' dialog with text: {dialog_text}")
                            break
                    except NoSuchElementException:
                        continue

            if dialog_found:
                if click_yes_to_navigate:
                    logger.info(
                        "click_yes_to_navigate is True - clicking YES to navigate to last read location"
                    )
                    for btn_strategy, btn_locator in LAST_READ_PAGE_DIALOG_BUTTONS:
                        try:
                            yes_button = self.automator.driver.find_element(btn_strategy, btn_locator)
                            if yes_button.is_displayed():
                                yes_button.click()
                                logger.info("Clicked YES button to navigate to last read location")
                                time.sleep(0.5)  # Give dialog time to dismiss
                                return True
                        except NoSuchElementException:
                            continue
                else:
                    # Return dialog info instead of clicking
                    return {"dialog_found": True, "dialog_text": dialog_text, "dialog_type": "last_read_page"}

            if not dialog_found:
                return False

            if click_yes_to_navigate:
                # If we got here with click_yes_to_navigate=True, it means we found the dialog but failed to click YES
                logger.warning("Found dialog but failed to click YES button")
                return False

        except Exception as e:
            logger.error(f"Error handling 'last read page/location' dialog: {e}", exc_info=True)
            return False

    def _navigate_pages(self, forward: bool, count: int) -> bool:
        """Navigate multiple pages forward or backward.

        Args:
            forward: True to navigate forward, False to navigate backward
            count: Number of pages to navigate.

        Returns:
            bool: True if navigation was successful, False otherwise.
        """
        if count <= 0:
            # No navigation needed
            return True

        # Check for and handle the 'last read page' dialog before navigating
        # When navigating pages, we want to click YES to go to the last read location
        dialog_result = self._handle_last_read_page_dialog(click_yes_to_navigate=True)

        logger.info(f"Navigating {count} pages {'forward' if forward else 'backward'}")

        success = True
        for i in range(count):
            if forward:
                page_success = self.automator.state_machine.reader_handler.turn_page_forward()
            else:
                page_success = self.automator.state_machine.reader_handler.turn_page_backward()

            if not page_success:
                logger.error(f"Failed to navigate on page {i+1} of {count}", exc_info=True)
                success = False
                break

            # Add a small delay between page turns
            if i < count - 1:
                time.sleep(0.5)

        return success

    def _preview_multiple_pages_forward(self, count: int) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Preview multiple pages forward, then return to original position.

        Args:
            count: Number of pages to preview forward.

        Returns:
            Tuple of (success, ocr_text, page_info)
        """
        if count <= 0:
            return False, None, None

        logger.info(f"Previewing {count} pages forward")

        # Navigate forward the specified number of pages
        forward_success = self._navigate_pages(forward=True, count=count)
        if not forward_success:
            logger.error("Failed to navigate forward during preview", exc_info=True)
            return False, None, None

        # Capture OCR from the preview page (text only, no page info)
        ocr_text, error_msg = self._extract_text_only_for_preview(f"preview_forward_{count}")

        # Now navigate back to original position
        backward_success = self._navigate_pages(forward=False, count=count)
        if not backward_success:
            logger.error("Failed to navigate back to original page after preview", exc_info=True)
            # Still continue to return the OCR text even if we couldn't navigate back

        if ocr_text:
            logger.info(f"Successfully previewed {count} pages forward and extracted OCR text")
            # Return OCR text but NO page info (we'll use navigation position page info instead)
            return True, ocr_text, None
        else:
            logger.error(f"Failed to extract OCR text from preview: {error_msg}", exc_info=True)
            return False, None, None

    def _preview_multiple_pages_backward(self, count: int) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Preview multiple pages backward, then return to original position.

        Args:
            count: Number of pages to preview backward.

        Returns:
            Tuple of (success, ocr_text, page_info)
        """
        if count <= 0:
            return False, None, None

        logger.info(f"Previewing {count} pages backward")

        # Navigate backward the specified number of pages
        backward_success = self._navigate_pages(forward=False, count=count)
        if not backward_success:
            logger.error("Failed to navigate backward during preview", exc_info=True)
            return False, None, None

        # Capture OCR from the preview page (text only, no page info)
        ocr_text, error_msg = self._extract_text_only_for_preview(f"preview_backward_{count}")

        # Now navigate forward to original position
        forward_success = self._navigate_pages(forward=True, count=count)
        if not forward_success:
            logger.error("Failed to navigate back to original page after preview", exc_info=True)
            # Still continue to return the OCR text even if we couldn't navigate back

        if ocr_text:
            logger.info(f"Successfully previewed {count} pages backward and extracted OCR text")
            # Return OCR text but NO page info (we'll use navigation position page info instead)
            return True, ocr_text, None
        else:
            logger.error(f"Failed to extract OCR text from preview: {error_msg}", exc_info=True)
            return False, None, None

    def _preview_pages_forward(self, count: int, show_placemark: bool) -> Tuple[Dict, int]:
        """Preview pages forward without navigating from current position.

        Args:
            count: Number of pages to preview forward.
            show_placemark: Whether to show placemark in reading progress.

        Returns:
            Tuple of (response_data, status_code)
        """
        logger.info(f"Handling _preview_pages_forward with count={count}")
        success, ocr_text, page_info = self._preview_multiple_pages_forward(count)
        if success and ocr_text:
            response_data = {"success": True, "ocr_text": ocr_text}
            # Use page info from OCR if available, otherwise get reading progress
            if page_info:
                response_data["progress"] = page_info
            else:
                # Get reading progress but don't show placemark
                progress = self.automator.state_machine.reader_handler.get_reading_progress(
                    show_placemark=show_placemark
                )
                if progress:
                    response_data["progress"] = progress
            return response_data, 200
        else:
            return {"error": f"Failed to preview {count} pages forward"}, 500

    def _preview_pages_backward(self, count: int, show_placemark: bool) -> Tuple[Dict, int]:
        """Preview pages backward without navigating from current position.

        Args:
            count: Number of pages to preview backward.
            show_placemark: Whether to show placemark in reading progress.

        Returns:
            Tuple of (response_data, status_code)
        """
        logger.info(f"Handling _preview_pages_backward with count={count}")
        success, ocr_text, page_info = self._preview_multiple_pages_backward(count)
        if success and ocr_text:
            response_data = {"success": True, "ocr_text": ocr_text}
            # Use page info from OCR if available, otherwise get reading progress
            if page_info:
                response_data["progress"] = page_info
            else:
                # Get reading progress but don't show placemark
                progress = self.automator.state_machine.reader_handler.get_reading_progress(
                    show_placemark=show_placemark
                )
                if progress:
                    response_data["progress"] = progress
            return response_data, 200
        else:
            return {"error": f"Failed to preview {count} pages backward"}, 500

    def _extract_text_only_for_preview(self, prefix: str) -> Tuple[Optional[str], Optional[str]]:
        """Take a screenshot and extract ONLY the main text (top 94%) for preview.

        Used when previewing pages - we only want text content, not page numbers.

        Args:
            prefix: Prefix for the screenshot filename

        Returns:
            tuple: (ocr_text, error_message) - OCR text if successful, error message if failed
        """
        try:
            # Give the page a moment to render fully
            time.sleep(0.5)

            # Get the user email for unique screenshot naming
            profile = self.automator.profile_manager.get_current_profile()
            sindarin_email = profile.get("email") if profile else None
            if sindarin_email:
                # Sanitize email for filename
                email_safe = sindarin_email.replace("@", "_").replace(".", "_")
                screenshot_id = f"{email_safe}_{prefix}_{int(time.time())}"
            else:
                screenshot_id = f"{prefix}_{int(time.time())}"

            # Take screenshot
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.automator.driver.save_screenshot(screenshot_path)

            # Extract ONLY main text for preview (no page indicators)
            ocr_text = None
            error_msg = None

            try:
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                # Import PIL to crop just the main text area
                from io import BytesIO

                from PIL import Image

                # Load the image
                img = Image.open(BytesIO(image_data))
                width, height = img.size

                # Crop main text area (top 94%, excluding page numbers which are in bottom 6%)
                main_text_box = (
                    0,  # Left edge
                    0,  # Top edge
                    width,  # Right edge
                    int(height * 0.94),  # Stop at 94% from top (excludes bottom 6% where page numbers are)
                )
                main_text_img = img.crop(main_text_box)

                # Convert to bytes for OCR
                main_text_bytes = BytesIO()
                main_text_img.save(main_text_bytes, format="PNG")
                main_text_data = main_text_bytes.getvalue()

                # OCR just the main text
                from server.utils.ocr_utils import KindleOCR

                ocr_text, ocr_error = KindleOCR.process_ocr(main_text_data)

                if ocr_error:
                    error_msg = ocr_error

                # Delete the screenshot file after processing
                try:
                    os.remove(screenshot_path)
                    logger.info(f"Deleted screenshot after text OCR processing: {screenshot_path}")
                except Exception as del_e:
                    logger.error(f"Failed to delete screenshot {screenshot_path}: {del_e}", exc_info=True)

            except Exception as e:
                logger.error(f"Error processing OCR: {e}", exc_info=True)
                error_msg = str(e)

            # Return OCR text only (no page info)
            return ocr_text, error_msg

        except Exception as e:
            logger.error(f"Error taking screenshot for text OCR: {e}", exc_info=True)
            return None, str(e)

    def _extract_page_info_only(self, prefix="page_only"):
        """Extract only page indicator information from current screen position.

        Args:
            prefix: Prefix for screenshot naming.

        Returns:
            dict: Page progress information (current_page, total_pages, etc.) or None if failed
        """
        try:
            # Take a screenshot
            screenshot_id = f"{prefix}_{int(time.time())}"
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.automator.driver.save_screenshot(screenshot_path)

            # Read the screenshot
            with open(screenshot_path, "rb") as img_file:
                image_data = img_file.read()

            # Import functions from reader_page_handler
            from handlers.reader_page_handler import (
                cycle_page_indicator_if_needed,
                extract_page_indicator_region,
            )

            # Extract only the page indicator region
            page_indicator_bytes = extract_page_indicator_region(image_data)

            if page_indicator_bytes:
                # OCR just the page indicator region
                from server.utils.ocr_utils import KindleOCR

                page_text, page_error = KindleOCR.process_ocr(page_indicator_bytes, clean_ui_elements=False)

                if page_text:
                    # Clean up the text
                    page_text = " ".join(page_text.split())
                    logger.info(f"Extracted page indicator at navigation position: '{page_text}'")

                    # Parse and potentially cycle the page indicator
                    page_info = cycle_page_indicator_if_needed(self.automator.driver, page_text)

                    # Clean up screenshot
                    try:
                        os.remove(screenshot_path)
                    except Exception:
                        pass

                    return page_info
                else:
                    logger.warning(f"Failed to OCR page indicator: {page_error}")

            # Clean up screenshot on failure
            try:
                os.remove(screenshot_path)
            except Exception:
                pass

            return None

        except Exception as e:
            logger.error(f"Error extracting page info: {e}", exc_info=True)
            return None

    @staticmethod
    def parse_navigation_params(request_obj) -> Dict[str, Union[int, bool, str]]:
        """Parse navigation parameters from request.

        Args:
            request_obj: The Flask request object.

        Returns:
            Dictionary of parsed parameters.
        """
        # Initialize with default values
        params = {
            "navigate_count": 0,  # Default to no navigation (caller will specify)
            "preview_count": 0,  # Default to no preview
            "show_placemark": False,
            "use_base64": False,
            "perform_ocr": True,  # Default to True - must be explicitly disabled with ocr=0
            "title": None,  # Book title for fallback if not in reading view
            "navigate_to": None,  # Absolute navigation position
            "preview_to": None,  # Absolute preview position
        }

        # Check for navigate_to parameter (absolute position)
        navigate_to_param = request_obj.args.get("navigate_to")
        if navigate_to_param is not None:
            try:
                params["navigate_to"] = int(navigate_to_param)
            except ValueError:
                logger.warning(f"Invalid navigate_to value: {navigate_to_param}, ignoring")

        # Check for preview_to parameter (absolute position)
        preview_to_param = request_obj.args.get("preview_to")
        if preview_to_param is not None:
            try:
                params["preview_to"] = int(preview_to_param)
                # Set perform_ocr to True if preview_to is set
                params["perform_ocr"] = True
            except ValueError:
                logger.warning(f"Invalid preview_to value: {preview_to_param}, ignoring")

        # Check for navigate parameter in query string (relative movement)
        navigate_param = request_obj.args.get("navigate")
        if navigate_param:
            try:
                params["navigate_count"] = int(navigate_param)
            except ValueError:
                logger.warning(f"Invalid navigate value: {navigate_param}, using default")

        # Check for preview parameter in query string (relative movement)
        preview_param = request_obj.args.get("preview")
        if preview_param:
            try:
                params["preview_count"] = int(preview_param)
                # Only set perform_ocr to True if preview is non-zero
                if params["preview_count"] != 0:
                    params["perform_ocr"] = True
            except ValueError:
                # Handle "1" or "true" values
                if preview_param.lower() in ("1", "true"):
                    params["preview_count"] = 1
                    params["perform_ocr"] = True

        # Check for position parameter (maps to show_placemark internally)
        position_param = request_obj.args.get("position", "0")
        params["show_placemark"] = position_param.lower() in ("1", "true", "yes")

        # Check for screenshot parameter
        screenshot_param = request_obj.args.get("screenshot", "0")
        params["include_screenshot"] = screenshot_param.lower() in ("1", "true", "yes")

        # Check for title parameter (same as /open-book endpoint)
        title = request_obj.args.get("title")
        if title:
            # URL decode the book title to handle plus signs and other encoded characters
            import urllib.parse

            decoded_title = urllib.parse.unquote_plus(title)
            if decoded_title != title:
                logger.info(f"Decoded book title: '{title}' -> '{decoded_title}'")
            params["title"] = decoded_title

        # Check if base64 parameter is provided
        params["use_base64"] = is_base64_requested()

        # Check if OCR is requested via query params - default to True for navigate
        params["perform_ocr"] = is_ocr_requested(default=True)

        # If OCR is requested, force base64 encoding
        if params["perform_ocr"] and not params["use_base64"]:
            params["use_base64"] = True

        # If request has JSON body, check for parameters there too
        if request_obj.is_json:
            try:
                json_data = request_obj.get_json(silent=True) or {}

                # Override action if provided in JSON
                if "action" in json_data and json_data["action"]:
                    params["action"] = json_data["action"]

                # Override navigate_to if provided in JSON (absolute position)
                if "navigate_to" in json_data:
                    try:
                        params["navigate_to"] = int(json_data["navigate_to"])
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid navigate_to in JSON: {json_data['navigate_to']}, ignoring")

                # Override preview_to if provided in JSON (absolute position)
                if "preview_to" in json_data:
                    try:
                        params["preview_to"] = int(json_data["preview_to"])
                        params["perform_ocr"] = True
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid preview_to in JSON: {json_data['preview_to']}, ignoring")

                # Override navigate_count if provided in JSON (relative movement)
                if "navigate" in json_data:
                    try:
                        params["navigate_count"] = int(json_data["navigate"])
                    except (ValueError, TypeError):
                        # If it's a boolean true, treat as 1
                        if isinstance(json_data["navigate"], bool) and json_data["navigate"]:
                            params["navigate_count"] = 1

                # Override preview_count if provided in JSON (relative movement)
                if "preview" in json_data:
                    try:
                        params["preview_count"] = int(json_data["preview"])
                        # Only set perform_ocr to True if preview is non-zero
                        if params["preview_count"] != 0:
                            params["perform_ocr"] = True
                    except (ValueError, TypeError):
                        # If it's a boolean true, treat as 1
                        if isinstance(json_data["preview"], bool) and json_data["preview"]:
                            params["preview_count"] = 1
                            params["perform_ocr"] = True

                # Override position if provided in JSON (maps to show_placemark internally)
                if "position" in json_data:
                    position_param = json_data["position"]
                    if isinstance(position_param, bool):
                        params["show_placemark"] = position_param
                    elif isinstance(position_param, str):
                        params["show_placemark"] = position_param.lower() in ("1", "true", "yes")
                    elif isinstance(position_param, int):
                        params["show_placemark"] = position_param == 1

                # Override screenshot if provided in JSON
                if "screenshot" in json_data:
                    screenshot_param = json_data["screenshot"]
                    if isinstance(screenshot_param, bool):
                        params["include_screenshot"] = screenshot_param
                    elif isinstance(screenshot_param, str):
                        params["include_screenshot"] = screenshot_param.lower() in ("1", "true", "yes")
                    elif isinstance(screenshot_param, int):
                        params["include_screenshot"] = screenshot_param == 1

                # Override title if provided in JSON (same as /open-book endpoint)
                if "title" in json_data and json_data["title"]:
                    # URL decode the book title to handle plus signs and other encoded characters
                    import urllib.parse

                    title = json_data["title"]
                    decoded_title = urllib.parse.unquote_plus(title)
                    if decoded_title != title:
                        logger.info(f"Decoded book title from JSON: '{title}' -> '{decoded_title}'")
                    params["title"] = decoded_title

            except Exception as e:
                logger.warning(f"Error parsing JSON request body: {e}")

        return params
