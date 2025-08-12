"""Book opening resource for opening specific books."""

import logging
import os
import time
import urllib.parse

from flask import request
from flask_restful import Resource

from handlers.about_book_popover_handler import AboutBookPopoverHandler
from handlers.navigation_handler import NavigationResourceHandler
from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
from server.utils.ocr_utils import KindleOCR, is_base64_requested, is_ocr_requested
from server.utils.request_utils import get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class BookOpenResource(Resource):
    def _open_book(self, book_title):
        """Open a specific book - shared implementation for GET and POST."""
        server = AutomationServer.get_instance()

        # URL decode the book title to handle plus signs and other encoded characters
        if book_title:
            decoded_book_title = urllib.parse.unquote_plus(book_title)
            if decoded_book_title != book_title:
                logger.info(f"Decoded book title: '{book_title}' -> '{decoded_book_title}'")
                book_title = decoded_book_title

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Check if OCR is requested - default to True for open-book
        perform_ocr = is_ocr_requested(default=True)
        if perform_ocr:
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True

        # Check if placemark is requested - default is FALSE which means DO NOT show placemark
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for this request")

        logger.info(f"Opening book: {book_title}")

        if not book_title:
            return {"error": "Book title is required in the request"}, 400

        # Common function to capture progress and screenshot
        def capture_book_state(already_open=False):
            # Check for and dismiss the About Book popover if present
            about_book_handler = AboutBookPopoverHandler(automator.driver)
            if about_book_handler.is_popover_present():
                logger.info("About Book popover detected - dismissing it")
                about_book_handler.dismiss_popover()
                # Small delay to let the popover dismiss animation complete
                time.sleep(0.5)

            # Check for the 'last read page' dialog without auto-accepting
            nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)
            dialog_result = nav_handler._handle_last_read_page_dialog(auto_accept=False)

            # If dialog was found, return it to the client for decision
            if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
                logger.info(
                    "Found 'last read page' dialog in open-book endpoint - returning to client for decision"
                )

                # We don't need screenshots or page source

                # Build response with dialog info
                response_data = {
                    "success": True,
                    "last_read_dialog": True,
                    "dialog_text": dialog_result.get("dialog_text"),
                    "message": "Last read page dialog detected",
                }

                # Add flag if book was already open
                if already_open:
                    response_data["already_open"] = True

                # No screenshot data to add

                return response_data, 200

            # No dialog found, continue with normal flow
            # Get reading progress
            progress = automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )
            logger.info(f"Progress: {progress}")

            # Create response data with progress info
            response_data = {"success": True, "progress": progress}

            # Add flag if book was already open
            if already_open:
                response_data["already_open"] = True

            # We need OCR text if requested, but without screenshots
            if perform_ocr:
                # Take a screenshot just for OCR then discard it
                # Get the user email for unique screenshot naming
                profile = automator.profile_manager.get_current_profile()
                user_email = profile.get("email") if profile else None
                if user_email:
                    # Sanitize email for filename
                    email_safe = user_email.replace("@", "_").replace(".", "_")
                    screenshot_id = f"{email_safe}_ocr_temp_{int(time.time())}"
                else:
                    screenshot_id = f"ocr_temp_{int(time.time())}"
                screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
                automator.driver.save_screenshot(screenshot_path)

                # Get OCR text
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                ocr_text, _ = KindleOCR.process_ocr(image_data)
                if ocr_text:
                    response_data["ocr_text"] = ocr_text

                # Delete the temporary screenshot
                try:
                    os.remove(screenshot_path)
                except Exception as e:
                    logger.warning(f"Error removing temporary OCR screenshot: {e}", exc_info=True)

            return response_data, 200

        # Ensure state_machine is initialized
        if not automator.state_machine:
            logger.error("State machine not initialized for automator", exc_info=True)
            return {
                "error": "State machine not initialized. Please ensure the automator is properly initialized."
            }, 500

        # Check initial state and restart if UNKNOWN
        current_state = automator.state_machine.check_initial_state_with_restart()

        # IMPORTANT: For new app installation or first run, current_book may be None
        # even though we're already in reading state - we need to check that too

        # Get current book for this email
        current_book = server.current_books.get(sindarin_email)

        # If we're already in READING state, we should NOT close the book - get the title!
        if current_state == AppState.READING:
            # First check for Download Limit dialog which needs to be handled even for already-open books
            try:
                # Check if we're dealing with the Download Limit dialog
                if automator.state_machine.reader_handler._check_for_download_limit_dialog():
                    logger.info("Found Download Limit dialog for current book - handling it")
                    # Handle the dialog
                    if automator.state_machine.reader_handler.handle_download_limit_dialog():
                        logger.info("Successfully handled Download Limit dialog")
                        # Continue with normal flow after handling dialog
                    else:
                        logger.error("Failed to handle Download Limit dialog", exc_info=True)
                        return {"error": "Failed to handle Download Limit dialog"}, 500
            except Exception as e:
                logger.warning(f"Error checking for Download Limit dialog: {e}", exc_info=True)

            # Then, check if we have current_book set
            if current_book:
                # Compare with the requested book
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

                # If we're in reading state but current_book doesn't match, try to get book title from UI
                logger.info(
                    f"In reading state but current book '{current_book}' doesn't match requested '{book_title}'"
                )
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.state_machine.reader_handler.get_book_title()
                    if current_title_from_ui:
                        logger.info(f"Got book title from UI: '{current_title_from_ui}'")

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
                            server.set_current_book(current_title_from_ui, sindarin_email)
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
                            server.set_current_book(current_title_from_ui, sindarin_email)
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
                        server.set_current_book(actively_reading_title, sindarin_email)
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
                        server.set_current_book(actively_reading_title, sindarin_email)
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
                            server.set_current_book(current_title_from_ui, sindarin_email)
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
                            server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)
                except Exception as e:
                    logger.warning(f"Failed to get book title from UI: {e}")
        # Not in reading state but have tracked book - clear it
        elif current_book:
            logger.info(
                f"Not in reading state: {current_state}, but have book '{current_book}' tracked - clearing it"
            )
            server.clear_current_book(sindarin_email)

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
                    server.set_current_book(book_title, sindarin_email)
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
                server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500

        # For other states, transition to library and open the book
        logger.info(f"Transitioning from {current_state} to library")
        final_state = automator.state_machine.transition_to_library(server=server)

        if final_state == AppState.LIBRARY:
            # Successfully transitioned to library
            # Use library_handler to open the book instead of reader_handler
            result = automator.state_machine.library_handler.open_book(book_title)
            logger.info(f"Book open result: {result}")

            # Handle dictionary response from library handler
            if result.get("status") == "title_not_available":
                # Return the error response directly
                return result, 400
            elif result.get("success"):
                # Set the current book in the server state
                server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500
        else:
            # Did not reach library state
            logger.info(f"Transition ended in state: {final_state} instead of LIBRARY")

            # Check if we ended up in an auth state
            auth_response = automator.state_machine.handle_auth_state_detection(final_state, sindarin_email)
            if auth_response:
                return auth_response, 401

            # Not in an auth state, return generic error
            return {
                "success": False,
                "error": f"Failed to transition from {current_state} to library (ended in {final_state})",
                "current_state": final_state.name,
                "authenticated": (
                    True
                ),  # User is authenticated but we couldn't reach library for other reasons
            }, 500

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
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
    @deduplicate_request
    def get(self):
        """Open a specific book via GET request."""
        book_title = request.args.get("title")

        # Call the implementation without the handle_automator_response decorator
        # since it might return a Response object that can't be JSON serialized
        result = self._open_book(book_title)

        # Directly return the result, as Flask can handle Response objects
        return result
