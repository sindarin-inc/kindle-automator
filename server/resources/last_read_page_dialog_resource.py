"""Last read page dialog resource for handling dialog decisions."""

import logging
import os
import time
import traceback

from flask import request
from flask_restful import Resource
from selenium.common.exceptions import NoSuchElementException

from handlers.navigation_handler import NavigationResourceHandler
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.ocr_utils import KindleOCR, is_base64_requested, is_ocr_requested
from server.utils.request_utils import get_sindarin_email
from views.reading.interaction_strategies import LAST_READ_PAGE_DIALOG_BUTTONS
from views.reading.view_strategies import LAST_READ_PAGE_DIALOG_IDENTIFIERS

logger = logging.getLogger(__name__)


class LastReadPageDialogResource(Resource):
    """Resource for handling the 'Last read page' dialog decisions.

    This endpoint allows the client to decide whether to click "Yes" or "No"
    on the "Last read page" dialog that appears when opening a book or navigating.
    """

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
        """Handle Last read page dialog choice from the client via GET request."""
        # Call the implementation method that handles both GET and POST requests
        return self._handle_last_read_page_dialog_choice()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Handle Last read page dialog choice from the client via POST request."""
        # Call the implementation method that handles both GET and POST requests
        return self._handle_last_read_page_dialog_choice()

    def _handle_last_read_page_dialog_choice(self):
        """Implementation for handling Last read page dialog choice from both GET and POST requests."""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = self.server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

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

        # Check if placemark is requested - default is FALSE
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for this request")
        else:
            logger.info("Placemark mode disabled - will avoid tapping to prevent placemark display")

        # Get the goto_last_read_page parameter from either query params or JSON body
        # First check query params
        goto_last_read_page = None
        goto_last_read_page_param = request.args.get("goto_last_read_page")
        if goto_last_read_page_param is not None:
            goto_last_read_page = goto_last_read_page_param.lower() in ("1", "true", "yes")
            logger.info(f"Found goto_last_read_page in query params: {goto_last_read_page}")

        # Then check JSON body if not found in query params
        if goto_last_read_page is None:
            data = request.get_json(silent=True) or {}
            if "goto_last_read_page" in data:
                goto_last_read_page_json = data.get("goto_last_read_page")
                if isinstance(goto_last_read_page_json, bool):
                    goto_last_read_page = goto_last_read_page_json
                elif isinstance(goto_last_read_page_json, str):
                    goto_last_read_page = goto_last_read_page_json.lower() in ("1", "true", "yes")
                elif isinstance(goto_last_read_page_json, int):
                    goto_last_read_page = goto_last_read_page_json == 1
                logger.info(f"Found goto_last_read_page in JSON body: {goto_last_read_page}")

        # If parameter wasn't provided, return an error
        if goto_last_read_page is None:
            return {
                "error": "Parameter 'goto_last_read_page' is required (boolean)",
                "message": (
                    "Must specify whether to go to the last read page (true) or start from beginning (false)"
                ),
            }, 400

        # Value is already converted to boolean when extracted from either source

        logger.info(f"Last read page dialog choice: goto_last_read_page={goto_last_read_page}")

        # Use NavigationResourceHandler to handle the dialog
        nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)

        # First check if the dialog is still visible before trying to click
        dialog_result = nav_handler._handle_last_read_page_dialog(auto_accept=False)
        if not dialog_result or not isinstance(dialog_result, dict) or not dialog_result.get("dialog_found"):
            logger.warning("Last read page dialog no longer visible - may have timed out or been dismissed")
            return {"error": "Last read page dialog not found"}, 404

        # Get dialog info for response
        dialog_text = dialog_result.get("dialog_text", "")

        # Now click the appropriate button based on the client's choice
        try:
            # Try to click YES or NO based on the goto_last_read_page value
            button_clicked = False

            # YES button - go to last read page
            if goto_last_read_page:
                logger.info("Client chose to go to last read page - clicking YES")
                for btn_strategy, btn_locator in LAST_READ_PAGE_DIALOG_BUTTONS:
                    try:
                        yes_button = automator.driver.find_element(btn_strategy, btn_locator)
                        if yes_button.is_displayed():
                            yes_button.click()
                            logger.info("Clicked YES button")
                            button_clicked = True
                            time.sleep(0.5)  # Give dialog time to dismiss
                            break
                    except NoSuchElementException:
                        continue
            # NO button - start from the beginning
            else:
                logger.info("Client chose to start from beginning - clicking NO")
                # The NO button is usually the second button (button2)
                try:
                    no_button = automator.driver.find_element("id", "android:id/button2")
                    if no_button.is_displayed():
                        no_button.click()
                        logger.info("Clicked NO button")
                        button_clicked = True
                        time.sleep(0.5)  # Give dialog time to dismiss
                except NoSuchElementException:
                    # Try another approach - look for "NO" text
                    try:
                        no_button = automator.driver.find_element(
                            "xpath", "//android.widget.Button[@text='NO']"
                        )
                        if no_button.is_displayed():
                            no_button.click()
                            logger.info("Clicked NO button by text")
                            button_clicked = True
                            time.sleep(0.5)  # Give dialog time to dismiss
                    except NoSuchElementException:
                        logger.warning("NO button not found by text")

            if not button_clicked:
                logger.error(f"Failed to click {'YES' if goto_last_read_page else 'NO'} button")
                return {"error": f"Failed to click {'YES' if goto_last_read_page else 'NO'} button"}, 500

            # Get reading progress
            progress = automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )

            # Build response
            response_data = {
                "success": True,
                "message": (
                    f"Successfully clicked {'YES' if goto_last_read_page else 'NO'} on Last read page dialog"
                ),
                "dialog_text": dialog_text,
                "progress": progress,
            }

            # We need OCR text if requested, but without screenshots
            if perform_ocr:
                # Take a screenshot just for OCR then discard it
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
                    logger.error(f"Error removing temporary OCR screenshot: {e}")

            return response_data, 200

        except Exception as e:
            logger.error(f"Error handling Last read page dialog choice: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"Failed to handle dialog choice: {str(e)}"}, 500
