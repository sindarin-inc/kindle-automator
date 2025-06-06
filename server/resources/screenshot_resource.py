"""Screenshot resource for taking screenshots of the current screen."""

import logging
import time
import traceback

from flask import request
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
    get_sindarin_email,
    is_websockets_requested,
)
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class ScreenshotResource(Resource):
    """Resource for taking screenshots."""

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
    def _capture_screenshot(self):
        """Shared implementation for capturing screenshots."""
        try:
            automator, _, error_response = get_automator_for_request(self.server)
            if error_response:
                return error_response

            # Get sindarin_email for context
            sindarin_email = get_sindarin_email()

            # Update the current state before taking screenshot
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state

            # Create a unique screenshot filename
            screenshot_id = f"screen_{sindarin_email}_{int(time.time())}"
            screenshot_path = f"{automator.screenshots_dir}/{screenshot_id}.png"

            # Take the screenshot
            automator.driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")

            # Log the action
            logger.info(f"SCREENSHOT: email={sindarin_email}, state={current_state}, path={screenshot_path}")

            # Get the external path for serving the image
            image_path = get_image_path(screenshot_id)

            # Check if base64 parameter is provided
            use_base64 = is_base64_requested()

            # Check if OCR is requested
            perform_ocr = is_ocr_requested()
            if perform_ocr:
                logger.info("OCR requested, will process screenshot with OCR")
                if not use_base64:
                    # Force base64 encoding for OCR
                    use_base64 = True
                    logger.info("Forcing base64 encoding for OCR processing")

            # Check if websockets parameter is provided
            use_websockets = is_websockets_requested()

            # Build base response
            response_data = {"success": True, "state": current_state.name}

            # Process screenshot based on parameters
            screenshot_result = process_screenshot_response(
                screenshot_id,
                screenshot_path,
                use_base64=use_base64,
                perform_ocr=perform_ocr,
            )
            
            # Merge screenshot results into response data
            response_data.update(screenshot_result)
            
            # Add websocket URL if requested
            if use_websockets:
                from server.utils.request_utils import get_vnc_and_websocket_urls
                _, ws_url = get_vnc_and_websocket_urls(sindarin_email)
                if ws_url:
                    response_data["websocket_url"] = ws_url

            # Add reading progress if in reading state
            if current_state == AppState.READING:
                try:
                    # Check if placemark is requested
                    show_placemark = False
                    placemark_param = request.args.get("placemark", "0")
                    if placemark_param.lower() in ("1", "true", "yes"):
                        show_placemark = True
                        logger.info("Placemark mode enabled for screenshot")

                    # Also check in POST data
                    if not show_placemark and request.is_json:
                        data = request.get_json(silent=True) or {}
                        placemark_param = data.get("placemark", "0")
                        if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                            show_placemark = True
                            logger.info("Placemark mode enabled from POST data for screenshot")

                    progress = automator.state_machine.reader_handler.get_reading_progress(
                        show_placemark=show_placemark
                    )
                    response_data["progress"] = progress
                except Exception as e:
                    logger.warning(f"Failed to get reading progress: {e}")

            # If everything went well, return success
            return response_data, 200

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error taking screenshot: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Take a screenshot of the current screen."""
        return self._capture_screenshot()

    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Take a screenshot of the current screen (POST version for potential future parameters)."""
        return self._capture_screenshot()
