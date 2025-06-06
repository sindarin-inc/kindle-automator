"""State resource for getting current app state."""

import logging

from flask import request
from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_automator_for_request, get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class StateResource(Resource):
    """Resource for getting current app state."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Get the current app state."""
        try:
            automator, _, error_response = get_automator_for_request(self.server)
            if error_response:
                return error_response

            # Get sindarin email for state tracking
            sindarin_email = get_sindarin_email()

            logger.info(
                f"CROSS_USER_DEBUG: State endpoint called for email={sindarin_email}, automator={id(automator)}"
            )

            # Update state before returning it
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state

            # Log the current book for this profile from the server
            current_book = self.server.current_books.get(sindarin_email, None)
            logger.info(
                f"CROSS_USER_DEBUG: State for email={sindarin_email}: state={current_state}, current_book='{current_book}'"
            )

            # Get page source if in an unhandled state and parameter is requested
            page_source = None
            if request.args.get("page_source") == "1":
                try:
                    page_source = automator.driver.page_source
                    logger.info(
                        f"Retrieved page source for state {current_state} (length: {len(page_source)})"
                    )
                except Exception as e:
                    logger.error(f"Failed to get page source: {e}")
                    page_source = None

            # Check if we're in the reader state and add reading progress
            if current_state == AppState.READING:
                # Get reading progress
                progress = automator.state_machine.reader_handler.get_reading_progress()

                # Get current book title - try multiple sources
                current_book_title = None

                # First check server's current books
                if sindarin_email in self.server.current_books:
                    current_book_title = self.server.current_books[sindarin_email]
                    logger.info(f"Got current book from server state: '{current_book_title}'")

                # If not available, try to get from actively_reading_title in profile
                if not current_book_title:
                    actively_reading_title = automator.profile_manager.get_style_setting(
                        "actively_reading_title", email=sindarin_email
                    )
                    if actively_reading_title:
                        current_book_title = actively_reading_title
                        logger.info(
                            f"Got current book from profile actively_reading_title: '{current_book_title}'"
                        )

                # If still not available, try to get from reader UI
                if not current_book_title:
                    try:
                        current_book_title = automator.state_machine.reader_handler.get_book_title()
                        if current_book_title:
                            logger.info(f"Got current book from reader UI: '{current_book_title}'")
                            # Update server state with the book title
                            self.server.set_current_book(current_book_title, sindarin_email)
                    except Exception as e:
                        logger.warning(f"Failed to get book title from UI: {e}")

                response = {
                    "state": current_state.name,
                    "progress": progress,
                }

                # Include current book title if available
                if current_book_title:
                    response["current_book"] = current_book_title

                # Add page source if requested
                if page_source:
                    response["page_source"] = page_source

                return response, 200
            else:
                # For non-reading states, clear any tracked current book
                if current_book:
                    logger.info(
                        f"Not in reading state ({current_state}), clearing tracked book: '{current_book}'"
                    )
                    self.server.clear_current_book(sindarin_email)

                response = {"state": current_state.name}

                # Add page source if requested
                if page_source:
                    response["page_source"] = page_source

                return response, 200

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error getting state: {e}")
            return {"error": str(e)}, 500
