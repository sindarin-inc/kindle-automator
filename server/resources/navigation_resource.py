"""Navigation resource for page navigation in reading mode."""

import logging
import os
import time
import traceback

from flask import request
from flask_restful import Resource

from handlers.navigation_handler import NavigationResourceHandler
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.ocr_utils import KindleOCR, is_base64_requested, is_ocr_requested
from server.utils.request_utils import get_automator_for_request, get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class NavigationResource(Resource):
    """Resource for navigation operations."""

    def __init__(self, server_instance=None, default_direction=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
            default_direction: Default navigation direction (1 for next, -1 for previous, 0 for no navigation)
        """
        self.server = server_instance
        self.default_direction = default_direction
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _navigate(self):
        """Shared implementation for navigation."""
        try:
            automator, _, error_response = get_automator_for_request(self.server)
            if error_response:
                return error_response

            # Validate we're in reading state
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state

            if current_state != AppState.READING:
                return {
                    "error": f"Navigation requires reading state, current state: {current_state.name}",
                }, 400

            # Get sindarin_email for context
            sindarin_email = get_sindarin_email()

            # Check for preview parameter from query string, form data or JSON body
            preview_direction = None

            # First check query parameters
            preview_param = request.args.get("preview")
            if preview_param:
                try:
                    preview_direction = int(preview_param)
                except ValueError:
                    logger.warning(f"Invalid preview parameter: {preview_param}")

            # Then check JSON body if available and preview not already set
            if preview_direction is None and request.is_json:
                data = request.get_json(silent=True) or {}
                if "preview" in data:
                    try:
                        preview_direction = int(data["preview"])
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid preview parameter in JSON: {data.get('preview')}")

            # For preview endpoints, set navigate=0 and use preview parameter for direction
            if self.default_direction == 0:  # This indicates a preview endpoint
                navigate_param = 0
                # Get preview direction from URL or use 1 for preview-next, -1 for preview-previous
                if preview_direction is None:
                    # Infer from endpoint name
                    if "preview-next" in str(request.url_rule):
                        preview_direction = 1
                    elif "preview-previous" in str(request.url_rule):
                        preview_direction = -1
                    else:
                        preview_direction = 1  # Default to next
            else:
                # For regular navigation endpoints
                # Get navigation parameter from query string, form data or JSON body
                # First check query parameters
                navigate_param = request.args.get("navigate", str(self.default_direction or 1))
                try:
                    navigate_param = int(navigate_param)
                except ValueError:
                    navigate_param = self.default_direction or 1

                # Then check JSON body if available
                if request.is_json:
                    data = request.get_json(silent=True) or {}
                    if "navigate" in data:
                        try:
                            navigate_param = int(data["navigate"])
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid navigate parameter in JSON: {data.get('navigate')}")

            # Check if placemark is requested - default is FALSE
            show_placemark = False
            placemark_param = request.args.get("placemark", "0")
            if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
                show_placemark = True
                logger.info("Placemark mode enabled for navigation")
            else:
                logger.info("Placemark mode disabled - will avoid tapping to prevent placemark display")

            # Also check in JSON body
            if not show_placemark and request.is_json:
                data = request.get_json(silent=True) or {}
                placemark_param = data.get("placemark", "0")
                if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                    show_placemark = True
                    logger.info("Placemark mode enabled from JSON body for navigation")

            # Check if base64 screenshot is requested
            use_base64 = is_base64_requested()

            # Check if OCR is requested
            perform_ocr = is_ocr_requested()
            if perform_ocr:
                logger.info("OCR requested, will process screenshot with OCR")
                if not use_base64:
                    # Force base64 encoding for OCR
                    use_base64 = True
                    logger.info("Forcing base64 encoding for OCR processing")

            # Initialize navigation handler
            nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)

            # Log navigation request
            logger.info(
                f"Navigation: navigate={navigate_param}, preview={preview_direction}, placemark={show_placemark}, ocr={perform_ocr}"
            )

            # For preview mode (navigate=0, preview=1 or -1)
            if navigate_param == 0 and preview_direction:
                result = nav_handler.preview_page(
                    preview_direction, show_placemark=show_placemark, perform_ocr=perform_ocr
                )
                return result, 200

            # For standard navigation (navigate=1 or -1)
            result = nav_handler.navigate_page(
                navigate_param,
                use_base64=use_base64,
                perform_ocr=perform_ocr,
                show_placemark=show_placemark,
            )

            # Check for "Last read page" dialog in the result
            if result.get("last_read_page_dialog"):
                # Return the dialog info to the client for decision
                return result, 200

            # Normal navigation result
            return result, 200

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error during navigation: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Navigate pages via GET request."""
        return self._navigate()

    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Navigate pages via POST request."""
        return self._navigate()
