"""
Table of Contents resource for Kindle Automator API.
"""

import logging
import time
import urllib.parse

from flask import g, request
from flask_restful import Resource

from handlers.table_of_contents_handler import TableOfContentsHandler
from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
from server.middleware.response_handler import handle_automator_response
from server.utils.ocr_utils import KindleOCR, is_base64_requested, is_ocr_requested

logger = logging.getLogger(__name__)


class TableOfContentsResource(Resource):
    """Resource for handling Table of Contents requests.

    NOTE: This endpoint should be accessed directly via the Flask server (port 4098)
    rather than through the proxy server (port 4096) since the proxy expects
    clients to provide kindle_uuid which we don't have upstream.

    Example: http://localhost:4098/table-of-contents?title=BookTitle&sindarin_email=user@email.com
    """

    def _check_cancellation(self):
        """Check if the current request has been cancelled."""
        # Get request manager from Flask context
        manager = getattr(g, "request_manager", None)
        if manager and manager.is_cancelled():
            from server.utils.ansi_colors import BOLD, BRIGHT_BLUE, RESET

            logger.info(
                f"{BRIGHT_BLUE}Request {BOLD}{BRIGHT_BLUE}{manager.request_key}{RESET}{BRIGHT_BLUE} "
                f"detected it was cancelled in table_of_contents handler{RESET}"
            )
            return True
        return False

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
    @handle_automator_response
    def get(self):
        """Get the table of contents or navigate to a chapter.

        Query Parameters:
            title (str): Optional book title to ensure we're in the correct book.
            chapter (str): Optional chapter name to navigate to. If provided, navigates to that chapter.
            page (int): Optional page number of the target chapter to optimize scroll direction.
            sindarin_email (str): Required - email to identify which automator to use.

        Returns:
            JSON response with table of contents data or navigation result.
        """
        server = AutomationServer.get_instance()

        # Check for cancellation at the start
        if self._check_cancellation():
            return {"error": "Request was cancelled by higher priority operation"}, 409

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

        # Get optional parameters from query string or JSON body
        # For GET requests, use query parameters; for POST, check JSON body first, then query params
        if request.method == "POST" and request.is_json:
            data = request.get_json()
            title = data.get("title") or request.args.get("title")
            chapter_name = data.get("chapter") or request.args.get("chapter")
            page = data.get("page") or request.args.get("page")
        else:
            title = request.args.get("title")
            chapter_name = request.args.get("chapter")
            page = request.args.get("page")

        if title:
            # URL decode the book title
            decoded_title = urllib.parse.unquote_plus(title)
            if decoded_title != title:
                logger.info(f"Decoded book title: '{title}' -> '{decoded_title}'")
            title = decoded_title

        if chapter_name:
            # URL decode the chapter name
            decoded_chapter = urllib.parse.unquote_plus(chapter_name)
            if decoded_chapter != chapter_name:
                logger.info(f"Decoded chapter name: '{chapter_name}' -> '{decoded_chapter}'")
            chapter_name = decoded_chapter

        # If chapter is provided, navigate to it
        if chapter_name:
            logger.info(f"Chapter navigation request from {sindarin_email}, chapter: {chapter_name}")

            # Check if base64 and OCR are requested (default True for navigation)
            use_base64 = is_base64_requested()
            perform_ocr = is_ocr_requested(default=True)
            if perform_ocr and not use_base64:
                use_base64 = True

            # Convert page to int if provided
            target_page = None
            if page:
                try:
                    target_page = int(page)
                    logger.info(f"Target page number: {target_page}")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid page number provided: {page}")

            # Create the handler with cancellation check
            toc_handler = TableOfContentsHandler(automator)
            # Pass cancellation check to the handler
            toc_handler.set_cancellation_check(self._check_cancellation)
            result = toc_handler.navigate_to_chapter(chapter_name, target_page=target_page)

            if not result.get("success"):
                return result, 400

            # Get OCR text after navigation if requested
            if perform_ocr:
                time.sleep(0.5)  # Wait for page to settle

                # Take a screenshot for OCR
                import os

                profile = automator.profile_manager.get_current_profile()
                user_email = profile.get("email") if profile else None
                if user_email:
                    email_safe = user_email.replace("@", "_").replace(".", "_")
                    screenshot_id = f"{email_safe}_chapter_nav_{int(time.time())}"
                else:
                    screenshot_id = f"chapter_nav_{int(time.time())}"

                screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
                automator.driver.save_screenshot(screenshot_path)

                # Get OCR text
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                ocr_text, _ = KindleOCR.process_ocr(image_data)
                if ocr_text:
                    result["ocr_text"] = ocr_text

                # Delete the temporary screenshot
                try:
                    os.remove(screenshot_path)
                except Exception as e:
                    logger.warning(f"Error removing temporary OCR screenshot: {e}")

            # Add navigation info to result
            result["navigation_type"] = "chapter_jump"
            result["jumped_to_chapter"] = chapter_name
            result["non_continuous_jump"] = True  # Signal to clear buffer on client side
            result["authenticated"] = True
            result["user_email"] = sindarin_email

            return result, 200
        else:
            # No chapter specified, just get the table of contents
            logger.info(f"Table of Contents request from {sindarin_email}, title: {title}")

            # Create the handler with cancellation check
            toc_handler = TableOfContentsHandler(automator)
            # Pass cancellation check to the handler
            toc_handler.set_cancellation_check(self._check_cancellation)
            response_data, status_code = toc_handler.get_table_of_contents(title=title)

            # Add user email to response for consistency
            response_data["user_email"] = sindarin_email

            return response_data, status_code

    def post(self):
        """Get the table of contents or navigate to a chapter via POST.

        JSON Body:
            title (str): Optional book title to ensure we're in the correct book.
            chapter (str): Optional chapter name to navigate to. If provided, navigates to that chapter.
            page (int): Optional page number of the target chapter to optimize scroll direction.
            sindarin_email (str): Required - email to identify which automator to use.

        Returns:
            JSON response with table of contents data or navigation result.
        """
        # Validate that we can parse the request properly
        # If the request has a body but it's not valid JSON, Flask will have already returned 400
        # But we can check if it's a POST without proper content type
        if request.method == "POST" and not request.is_json and request.data:
            # This means there's a body but it's not JSON or doesn't have the right content-type
            logger.warning("POST request to /table-of-contents without proper JSON content-type")
            # Return error with proper metadata for consistency
            from server.utils.request_utils import is_request_authenticated

            return {
                "error": "POST requests must have Content-Type: application/json",
                "authenticated": is_request_authenticated(),
            }, 400

        # POST method now works exactly like GET
        # This allows both GET and POST requests to either list TOC or navigate to chapters
        # Note: We don't need decorators here since get() already has them
        return self.get()
