"""Book open resource for opening a specific book."""

import logging
import os
import time
import traceback
import urllib.parse

from flask import Response, make_response, request, send_file
from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import get_image_path, handle_automator_response
from server.utils.ocr_utils import (
    KindleOCR,
    is_base64_requested,
    is_ocr_requested,
    process_screenshot_response,
)
from server.utils.request_utils import (
    get_automator_for_request,
    get_formatted_vnc_url,
    get_sindarin_email,
    get_vnc_and_websocket_urls,
    is_websockets_requested,
)
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class BookOpenResource(Resource):
    """Resource for opening books."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    def _open_book(self, book_title):
        """Implementation for opening a book - returns response directly without decorator processing."""
        if not book_title:
            return {"error": "Book title is required"}, 400

        logger.info(f"Opening book: {book_title}")

        # Decode URL-encoded title
        book_title = urllib.parse.unquote(book_title)

        # Get the automator
        automator, sindarin_email, error_response = get_automator_for_request(self.server)
        if error_response:
            return error_response

        # Log email context
        logger.info(f"Opening book '{book_title}' for {sindarin_email}")

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Check if OCR is requested
        perform_ocr = is_ocr_requested()
        if perform_ocr:
            logger.info("OCR requested, will process image with OCR")
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True
                logger.info("Forcing base64 encoding for OCR processing")

        # Check if websockets parameter is provided
        use_websockets = is_websockets_requested()

        # Check if placemark is requested - default is FALSE
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for open-book request")
        else:
            logger.info("Placemark mode disabled - will avoid tapping to prevent placemark display")

        # Also check in POST data
        if not show_placemark and request.is_json:
            data = request.get_json(silent=True) or {}
            placemark_param = data.get("placemark", "0")
            if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                show_placemark = True
                logger.info("Placemark mode enabled from POST data for open-book request")

        def capture_book_state(already_open=False):
            """Capture the current state of the book being read."""
            if not already_open:
                # Wait a bit for the book to fully load
                time.sleep(2)

            # Get current state and progress
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state

            # Save the actively reading title
            automator.profile_manager.set_style_setting(
                "actively_reading_title", book_title, email=sindarin_email
            )
            logger.info(f"Saved actively reading title: '{book_title}' for {sindarin_email}")

            # Take a screenshot
            screenshot_id = f"book_opened_{int(time.time())}"
            screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
            automator.driver.save_screenshot(screenshot_path)

            # Get the external path for serving the image
            image_path = get_image_path(screenshot_id)

            # Build base response
            response_data = {
                "success": True,
                "state": current_state.name,
                "book_title": book_title,
            }

            # Get reading progress
            try:
                progress = automator.state_machine.reader_handler.get_reading_progress(
                    show_placemark=show_placemark
                )
                response_data["progress"] = progress
            except Exception as e:
                logger.warning(f"Failed to get reading progress: {e}")

            # Process screenshot based on parameters
            response_data = process_screenshot_response(
                response_data,
                screenshot_path,
                screenshot_id,
                image_path,
                use_base64=use_base64,
                perform_ocr=perform_ocr,
                use_websockets=use_websockets,
                sindarin_email=sindarin_email,
            )

            return response_data

        # Check if we're already reading this book
        current_state = automator.state_machine.update_current_state()

        # Get the current book being read if any
        current_book = self.server.current_books.get(sindarin_email, None)
        logger.info(f"Current book tracked for {sindarin_email}: '{current_book}'")

        # Normalize book titles for comparison
        if current_state == AppState.READING:
            if current_book:
                # Normalize titles for comparison
                normalized_request_title = "".join(
                    c for c in book_title if c.isalnum() or c.isspace()
                ).lower()
                normalized_current_title = "".join(
                    c for c in current_book if c.isalnum() or c.isspace()
                ).lower()

                logger.info(
                    f"Title comparison: requested='{normalized_request_title}', current='{normalized_current_title}'"
                )

                # Try exact match first
                if normalized_request_title == normalized_current_title:
                    logger.info(f"Already reading book (exact match): {book_title}, returning current state")
                    return capture_book_state(already_open=True)

                # For longer titles, try to match the first 30+ characters or check if one title contains the other
                if (
                    len(normalized_request_title) > 30
                    and len(normalized_current_title) > 30
                    and (
                        normalized_request_title[:30] == normalized_current_title[:30]
                        or normalized_request_title in normalized_current_title
                        or normalized_current_title in normalized_request_title
                    )
                ):
                    logger.info(
                        f"Already reading book (partial match): {book_title}, returning current state"
                    )
                    return capture_book_state(already_open=True)

                # If no match, also try to get the current book title from the UI
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.state_machine.reader_handler.get_book_title()
                    if current_title_from_ui:
                        logger.info(
                            f"Got book title from UI: '{current_title_from_ui}' vs requested: '{book_title}'"
                        )

                        # Compare with the requested book
                        normalized_ui_title = "".join(
                            c for c in current_title_from_ui if c.isalnum() or c.isspace()
                        ).lower()

                        # Check exact match with UI title
                        if normalized_request_title == normalized_ui_title:
                            logger.info(
                                f"Already reading book (UI title exact match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            self.server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)

                        # Check partial match with UI title
                        if (
                            len(normalized_request_title) > 30
                            and len(normalized_ui_title) > 30
                            and (
                                normalized_request_title[:30] == normalized_ui_title[:30]
                                or normalized_request_title in normalized_ui_title
                                or normalized_ui_title in normalized_request_title
                            )
                        ):
                            logger.info(
                                f"Already reading book (UI title partial match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            self.server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)
                except Exception as e:
                    logger.warning(f"Failed to get book title from UI: {e}")

                logger.info(
                    f"No match found for book: {book_title} ({normalized_request_title}) != {current_book}, transitioning to library"
                )
            else:
                # We're in reading state but don't have current_book set
                # First check if we have an actively reading title stored in profile settings
                actively_reading_title = automator.profile_manager.get_style_setting(
                    "actively_reading_title", email=sindarin_email
                )

                if actively_reading_title:
                    # Compare with the requested book
                    normalized_request_title = "".join(
                        c for c in book_title if c.isalnum() or c.isspace()
                    ).lower()
                    normalized_active_title = "".join(
                        c for c in actively_reading_title if c.isalnum() or c.isspace()
                    ).lower()

                    logger.info(
                        f"Title comparison with stored active title: requested='{normalized_request_title}', active='{normalized_active_title}'"
                    )

                    # Try exact match first
                    if normalized_request_title == normalized_active_title:
                        logger.info(
                            f"Already reading book (stored active title exact match): {book_title}, returning current state"
                        )
                        # Update server's current book tracking
                        self.server.set_current_book(actively_reading_title, sindarin_email)
                        return capture_book_state(already_open=True)

                    # For longer titles, try to match the first 30+ characters or check if one title contains the other
                    if (
                        len(normalized_request_title) > 30
                        and len(normalized_active_title) > 30
                        and (
                            normalized_request_title[:30] == normalized_active_title[:30]
                            or normalized_request_title in normalized_active_title
                            or normalized_active_title in normalized_request_title
                        )
                    ):
                        logger.info(
                            f"Already reading book (stored active title partial match): {book_title}, returning current state"
                        )
                        # Update server's current book tracking
                        self.server.set_current_book(actively_reading_title, sindarin_email)
                        return capture_book_state(already_open=True)

                # If no match with stored title, try to get it from UI
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.state_machine.reader_handler.get_book_title()
                    if current_title_from_ui:
                        logger.info(
                            f"In reading state with no tracked book. Got book title from UI: '{current_title_from_ui}'"
                        )

                        # Compare with the requested book
                        normalized_request_title = "".join(
                            c for c in book_title if c.isalnum() or c.isspace()
                        ).lower()
                        normalized_ui_title = "".join(
                            c for c in current_title_from_ui if c.isalnum() or c.isspace()
                        ).lower()

                        # Check exact match with UI title
                        if normalized_request_title == normalized_ui_title:
                            logger.info(
                                f"Already reading book (UI title exact match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            self.server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)

                        # Check partial match with UI title
                        if (
                            len(normalized_request_title) > 30
                            and len(normalized_ui_title) > 30
                            and (
                                normalized_request_title[:30] == normalized_ui_title[:30]
                                or normalized_request_title in normalized_ui_title
                                or normalized_ui_title in normalized_request_title
                            )
                        ):
                            logger.info(
                                f"Already reading book (UI title partial match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            self.server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)
                except Exception as e:
                    logger.warning(f"Failed to get book title from UI: {e}")
        # Not in reading state but have tracked book - clear it
        elif current_book:
            logger.info(
                f"Not in reading state: {current_state}, but have book '{current_book}' tracked - clearing it"
            )
            self.server.clear_current_book(sindarin_email)

        logger.info(f"Reloaded current state: {current_state}")

        # If we get here, we need to go to library or handle search results directly
        logger.info(
            f"Not already reading requested book: {book_title} != {current_book}, current state: {current_state}"
        )

        # If we're in search results view, we can open books directly without transitioning to library
        if current_state == AppState.SEARCH_RESULTS:
            logger.info("Currently in SEARCH_RESULTS view, opening book directly")

            # Set book_to_open attribute on automator for the state handler to use
            automator.book_to_open = book_title
            logger.info(f"Set automator.book_to_open to '{book_title}' for handle_search_results")

            # First try to handle the search results state which will look for the book
            if automator.state_machine.handle_state():
                logger.info("Successfully handled SEARCH_RESULTS state")
                # Check if we've moved to READING state
                automator.state_machine.update_current_state()
                if automator.state_machine.current_state == AppState.READING:
                    # Set the current book in the server state
                    self.server.set_current_book(book_title, sindarin_email)
                    return capture_book_state()

            # If handle_state didn't succeed or we're not in READING state, try direct approach
            logger.info("Falling back to direct library_handler.open_book for search results")
            result = automator.state_machine.library_handler.open_book(book_title)
            logger.info(f"Book open result from search results: {result}")

            # Handle dictionary response from library handler
            if result.get("status") == "title_not_available":
                # Return the error response directly
                return result, 400
            elif result.get("success"):
                # Set the current book in the server state
                self.server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500

        # For other states, transition to library and open the book
        logger.info(f"Transitioning from {current_state} to library")
        if automator.state_machine.transition_to_library(server=self.server):
            # Use library_handler to open the book instead of reader_handler
            result = automator.state_machine.library_handler.open_book(book_title)
            logger.info(f"Book open result: {result}")

            # Handle dictionary response from library handler
            if result.get("status") == "title_not_available":
                # Return the error response directly
                return result, 400
            elif result.get("success"):
                # Set the current book in the server state
                self.server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500
        else:
            # Failed to transition to library
            logger.error(f"Failed to transition from {current_state} to library")
            return {"success": False, "error": f"Failed to transition from {current_state} to library"}, 500

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def post(self):
        """Open a specific book via POST request."""
        data = request.get_json()
        book_title = data.get("title")

        # Handle placemark parameter from POST data
        placemark_param = data.get("placemark", "0")
        if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
            request.args = request.args.copy()
            request.args["placemark"] = "1"

        # Call the implementation without the handle_automator_response decorator
        # since it might return a Response object that can't be JSON serialized
        result = self._open_book(book_title)

        # Directly return the result, as Flask can handle Response objects
        return result

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """Open a specific book via GET request."""
        book_title = request.args.get("title")

        # Call the implementation without the handle_automator_response decorator
        # since it might return a Response object that can't be JSON serialized
        result = self._open_book(book_title)

        # Directly return the result, as Flask can handle Response objects
        return result
