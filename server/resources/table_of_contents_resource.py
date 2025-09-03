"""
Table of Contents resource for Kindle Automator API.
"""

import logging

from flask import request
from flask_restful import Resource

from handlers.table_of_contents_handler import TableOfContentsHandler
from server.core.automation_server import AutomationServer

logger = logging.getLogger(__name__)


class TableOfContentsResource(Resource):
    """Resource for handling Table of Contents requests."""

    def get(self):
        """Get the table of contents for the current or specified book.

        Query Parameters:
            title (str): Optional book title to ensure we're in the correct book.

        Returns:
            JSON response with table of contents data or error message.
        """
        try:
            # Get user email for tracking
            user_email = request.args.get("user_email")
            if not user_email:
                return {"error": "User email is required"}, 400

            # Get optional title parameter
            title = request.args.get("title")
            if title:
                # URL decode the book title
                import urllib.parse

                decoded_title = urllib.parse.unquote_plus(title)
                if decoded_title != title:
                    logger.info(f"Decoded book title: '{title}' -> '{decoded_title}'")
                title = decoded_title

            logger.info(f"Table of Contents request from {user_email}, title: {title}")

            # Get the server and automator
            server = AutomationServer.get_instance()
            if not server:
                return {"error": "Server not initialized"}, 503

            automator = server.get_automator(user_email)
            if not automator:
                return {"error": "No active session for user"}, 503

            # Create the handler and get table of contents
            toc_handler = TableOfContentsHandler(automator)
            response_data, status_code = toc_handler.get_table_of_contents(title=title)

            # Add user email to response
            response_data["user_email"] = user_email

            return response_data, status_code
        except Exception as e:
            logger.error(f"Error getting table of contents: {e}", exc_info=True)
            return {"error": str(e)}, 500
