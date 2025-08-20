"""Screenshot resource for capturing current screen state."""

import logging
import os
import time

from flask import make_response, request
from flask_restful import Resource

from server.core.automation_server import AutomationServer
from server.logging_config import store_page_source
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
from server.middleware.response_handler import (
    get_image_path,
    handle_automator_response,
    serve_image,
)
from server.utils.appium_error_utils import is_appium_error
from server.utils.ocr_utils import (
    is_base64_requested,
    is_ocr_requested,
    process_screenshot_response,
)
from server.utils.request_utils import get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class ScreenshotResource(Resource):
    # Only use the automator_healthy decorator without the response handler for direct image responses
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
    def get(self):
        """Get current page screenshot and return a URL to access it or display it directly.
        If xml=1 is provided, returns the XML page source directly as text/xml.
        If text=1 is provided, OCRs the image and returns the text.
        If base64=1 is provided, returns the image encoded as base64 instead of a URL."""
        server = AutomationServer.get_instance()

        failed = None
        # Check if save parameter is provided
        save = request.args.get("save", "0") in ("1", "true")
        # Check if xml parameter is provided
        include_xml = request.args.get("xml", "0") in ("1", "true")
        # Check if OCR is requested via 'text' or 'ocr' parameter
        ocr_param = request.args.get("ocr", "0")
        text_param = request.args.get("text", "0")
        is_ocr = is_ocr_requested(default=False)
        logger.info(
            f"OCR debug - ocr param: {ocr_param}, text param: {text_param}, is_ocr_requested(): {is_ocr}"
        )

        perform_ocr = text_param in ("1", "true") or is_ocr

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()
        if perform_ocr and not use_base64:
            use_base64 = True

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Generate a unique filename with timestamp to avoid caching issues
        timestamp = int(time.time())
        filename = f"current_screen_{timestamp}.png"
        screenshot_path = os.path.join(automator.screenshots_dir, filename)

        # Take the screenshot
        try:
            # Check if we're in an auth-related state where we need to use secure screenshot
            current_state = automator.state_machine.current_state
            auth_states = [AppState.SIGN_IN, AppState.CAPTCHA, AppState.LIBRARY_SIGN_IN, AppState.UNKNOWN]

            # Check if the use_scrcpy parameter is explicitly set
            use_scrcpy = request.args.get("use_scrcpy", "0") in ("1", "true")

            if current_state == AppState.UNKNOWN and not use_scrcpy:
                # If state is unknown, update state first before deciding on screenshot method
                logger.info("State is UNKNOWN, updating state before choosing screenshot method")
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                logger.info(f"State after update: {current_state}")

            if current_state in auth_states or use_scrcpy:
                logger.info(
                    f"Using secure screenshot method for auth state: {current_state} or explicit scrcpy request"
                )
                # First attempt with secure screenshot method
                secure_path = automator.take_secure_screenshot(screenshot_path)
                if not secure_path:
                    # Try with standard method as fallback but catch FLAG_SECURE exceptions
                    logger.warning("Secure screenshot failed, falling back to standard method")
                    try:
                        automator.driver.save_screenshot(screenshot_path)
                    except Exception as inner_e:
                        # If this fails too, we'll log the error but continue with response processing
                        # so the error is properly reported to the client
                        logger.warning(f"Standard screenshot also failed: {inner_e}", exc_info=True)
                        failed = "Failed to take screenshot - FLAG_SECURE may be set"
            else:
                # Use standard screenshot for non-auth screens
                automator.driver.save_screenshot(screenshot_path)
        except Exception as e:
            if is_appium_error(e):
                raise
            logger.error(f"Error taking screenshot: {e}", exc_info=True)
            failed = "Failed to take screenshot"

        # Get the image ID for URLs
        image_id = os.path.splitext(filename)[0]

        # Default is to return the image directly unless explicitly requested otherwise
        logger.info(
            f"save: {save}, include_xml: {include_xml}, use_base64: {use_base64}, perform_ocr: {perform_ocr}"
        )

        # If xml=1, return XML directly as text/xml response
        if include_xml and not perform_ocr and not use_base64:
            try:
                # Get page source from the driver
                page_source = automator.driver.page_source

                # Store the XML for debugging purposes
                xml_filename = f"{image_id}.xml"
                xml_path = store_page_source(page_source, image_id)
                logger.info(f"Stored page source XML at {xml_path}")

                # Create a proper Flask response with XML content type
                # Flask-RESTful will respect this and not serialize it
                response = make_response(page_source)
                response.headers["Content-Type"] = "text/xml; charset=utf-8"
                return response
            except Exception as xml_error:
                logger.error(f"Error getting page source XML: {xml_error}", exc_info=True)
                return {"error": f"Failed to get XML: {str(xml_error)}"}, 500

        # If OCR is requested, we need the JSON response path
        if perform_ocr:
            logger.info("OCR requested, forcing JSON response path")
        elif not save and not include_xml and not use_base64:
            # For direct image responses, don't use the automator response handler
            # since it can't handle Flask Response objects
            if failed:
                return {"error": failed, "screenshot_url": None, "xml_url": None}, 200
            return serve_image(image_id, delete_after=False)

        # For JSON responses, we can wrap with the automator response handler
        @handle_automator_response
        def get_screenshot_json():
            # Prepare the response data
            response_data = {}

            # Process the screenshot (either base64 encode, add URL, or perform OCR)
            screenshot_path = get_image_path(image_id)
            screenshot_data = process_screenshot_response(image_id, screenshot_path, use_base64, perform_ocr)
            response_data.update(screenshot_data)

            # If xml=1, get and save the page source XML
            if include_xml:
                try:
                    # Get page source from the driver
                    page_source = automator.driver.page_source

                    # Store the XML with the same base name as the screenshot
                    xml_filename = f"{image_id}.xml"
                    xml_path = store_page_source(page_source, image_id)
                    logger.info(f"Stored page source XML at {xml_path}")

                    # Add the XML URL to the response
                    # Assuming the XML will be served via a dedicated endpoint or file location
                    xml_url = f"/fixtures/dumps/{xml_filename}"
                    response_data["xml_url"] = xml_url
                except Exception as xml_error:
                    logger.error(f"Error getting page source XML: {xml_error}", exc_info=True)
                    response_data["xml_error"] = str(xml_error)

            # OCR is now handled by process_screenshot_response

            # Return the response as a tuple that the decorator can handle
            if failed:
                response_data["error"] = failed
                return response_data, 500
            return response_data, 200

        # Call the nested function with automator response handling
        response, status_code = get_screenshot_json()
        if failed:
            response["error"] = failed
            return response, status_code
        return response, status_code
