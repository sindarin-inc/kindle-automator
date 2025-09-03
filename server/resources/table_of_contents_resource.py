"""
Table of Contents resource for Kindle Automator API.
"""

import logging

from flask import request
from flask_restful import Resource

from handlers.table_of_contents_handler import TableOfContentsHandler
from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
from server.middleware.response_handler import handle_automator_response

logger = logging.getLogger(__name__)


class TableOfContentsResource(Resource):
    """Resource for handling Table of Contents requests.

    NOTE: This endpoint should be accessed directly via the Flask server (port 4098)
    rather than through the proxy server (port 4096) since the proxy expects
    clients to provide kindle_uuid which we don't have upstream.

    Example: http://localhost:4098/table-of-contents?title=BookTitle&sindarin_email=user@email.com
    """

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
    @handle_automator_response
    def get(self):
        """Get the table of contents for the current or specified book.

        Query Parameters:
            title (str): Optional book title to ensure we're in the correct book.
            sindarin_email (str): Required - email to identify which automator to use.

        Returns:
            JSON response with table of contents data or error message.
        """
        server = AutomationServer.get_instance()

        # Get sindarin_email from request to determine which automator to use
        from server.utils.request_utils import get_sindarin_email

        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.warning("No email provided to identify which profile to use")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator - decorators ensure it exists and is healthy
        automator = server.automators.get(sindarin_email)
        if not automator:
            logger.error(f"No automator found for {sindarin_email}")
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Get optional title parameter
        title = request.args.get("title")
        if title:
            # URL decode the book title
            import urllib.parse

            decoded_title = urllib.parse.unquote_plus(title)
            if decoded_title != title:
                logger.info(f"Decoded book title: '{title}' -> '{decoded_title}'")
            title = decoded_title

        logger.info(f"Table of Contents request from {sindarin_email}, title: {title}")

        # Create the handler and get table of contents
        toc_handler = TableOfContentsHandler(automator)
        response_data, status_code = toc_handler.get_table_of_contents(title=title)

        # Add user email to response for consistency
        response_data["user_email"] = sindarin_email

        return response_data, status_code
