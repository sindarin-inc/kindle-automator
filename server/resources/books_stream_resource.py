"""Books stream resource for getting library books with server-sent events."""

import json
import logging
import time
import traceback

from flask import Response, request
from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.utils.cover_utils import (
    add_cover_urls_to_books,
    extract_book_covers_from_screen,
)
from server.utils.request_utils import get_automator_for_request, get_sindarin_email

logger = logging.getLogger(__name__)


class BooksStreamResource(Resource):
    """Resource for getting library books with server-sent events (SSE)."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """Get all books in the library using Server-Sent Events for real-time updates."""

        def generate():
            """Generator function for SSE streaming."""
            try:
                # Send initial connection event
                yield f"event: connection\ndata: {json.dumps({'status': 'connected', 'message': 'SSE stream established'})}\n\n"

                automator, _, error_response = get_automator_for_request(self.server)
                if error_response:
                    yield f"event: error\ndata: {json.dumps(error_response[0])}\n\n"
                    return

                sindarin_email = get_sindarin_email()

                # Check if covers parameter is provided (default to true)
                include_covers = request.args.get("covers", "1").lower() in ("1", "true", "yes")

                # If we need covers, check if extract parameter is provided
                extract_covers = False
                if include_covers and request.args.get("extract", "0").lower() in ("1", "true", "yes"):
                    extract_covers = True

                # Read the 'search' parameter to filter books by title
                search_query = request.args.get("search", "").strip()

                # Send status update
                yield f"event: status\ndata: {json.dumps({'action': 'transitioning_to_library', 'message': 'Navigating to library view'})}\n\n"

                # Get the library handler and fetch books
                library_handler = automator.state_machine.library_handler

                # Log when getting filtered results
                if search_query:
                    logger.info(f"Getting books filtered by search query: '{search_query}'")

                # Use get_all_books which transitions to library if needed
                books = library_handler.get_all_books(server=self.server)

                logger.info(f"Retrieved {len(books)} books from library")

                # Apply search filter if provided
                if search_query:
                    # Filter books by title (case-insensitive)
                    filtered_books = []
                    search_lower = search_query.lower()
                    for book in books:
                        if search_lower in book.get("title", "").lower():
                            filtered_books.append(book)

                    logger.info(
                        f"Filtered from {len(books)} to {len(filtered_books)} books matching '{search_query}'"
                    )
                    books = filtered_books

                # Send book count update
                yield f"event: book_count\ndata: {json.dumps({'count': len(books), 'search': search_query if search_query else None})}\n\n"

                # Add cover URLs if requested and not extracting
                if include_covers and not extract_covers:
                    yield f"event: status\ndata: {json.dumps({'action': 'adding_cover_urls', 'message': 'Adding cover URLs to books'})}\n\n"
                    books = add_cover_urls_to_books(books, sindarin_email)

                # Extract covers if requested
                if extract_covers:
                    yield f"event: status\ndata: {json.dumps({'action': 'extracting_covers', 'message': 'Extracting book covers from screen'})}\n\n"

                    # Take a screenshot of the current library view
                    screenshot_path = f"{automator.screenshots_dir}/library_covers_{int(time.time())}.png"
                    automator.driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved library screenshot for cover extraction: {screenshot_path}")

                    # Extract covers from the screenshot
                    extracted_covers = extract_book_covers_from_screen(
                        automator.driver, sindarin_email, screenshot_path, save_covers=True
                    )

                    # Add the extracted cover URLs to the books
                    if extracted_covers:
                        logger.info(f"Extracted {len(extracted_covers)} book covers")
                        yield f"event: covers_extracted\ndata: {json.dumps({'count': len(extracted_covers)})}\n\n"

                        # Match extracted covers to books by title
                        for book in books:
                            book_title = book.get("title", "")
                            for cover_info in extracted_covers:
                                if cover_info["title"] == book_title:
                                    book["cover_url"] = cover_info["cover_url"]
                                    book["cover_extracted"] = True
                                    break

                # Send complete response
                final_data = {
                    "books": books,
                    "count": len(books),
                    "search": search_query if search_query else None,
                    "covers_included": include_covers,
                    "covers_extracted": extract_covers,
                }

                yield f"event: complete\ndata: {json.dumps(final_data)}\n\n"

            except Exception as e:
                from server.utils.appium_error_utils import is_appium_error

                if is_appium_error(e):
                    # For Appium errors, send error event and re-raise
                    error_data = {
                        "error": str(e),
                        "type": "appium_error",
                        "message": "Driver communication error",
                    }
                    yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
                    raise
                else:
                    logger.error(f"Error retrieving books: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    error_data = {"error": str(e), "type": "general_error"}
                    yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

        # Return SSE response with proper headers
        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
                "Connection": "keep-alive",
            },
        )
