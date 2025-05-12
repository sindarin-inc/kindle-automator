"""
Navigation handler for Kindle Automator.

This module provides functionality to navigate between pages in the Kindle app,
with support for:
1. Navigating multiple pages at once
2. Previewing pages ahead or behind without changing current position
3. OCR processing of pages
"""

import logging
import os
import time
from typing import Dict, Optional, Tuple, Union

from flask import request

from server.middleware.response_handler import get_image_path
from server.utils.ocr_utils import (
    KindleOCR,
    is_base64_requested,
    is_ocr_requested,
    process_screenshot_response,
)

logger = logging.getLogger(__name__)


class NavigationResourceHandler:
    """Handler for navigation-related requests in the Kindle Automator."""

    def __init__(self, automator, screenshots_dir: str = "screenshots"):
        """Initialize the navigation handler.

        Args:
            automator: The Kindle Automator instance.
            screenshots_dir: Directory for saving screenshots.
        """
        self.automator = automator
        self.screenshots_dir = screenshots_dir
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def navigate(
        self,
        navigate_count: int = 1,
        preview_count: int = 0,
        show_placemark: bool = False,
        use_base64: bool = False,
        perform_ocr: bool = False,
    ) -> Tuple[Dict, int]:
        """Handle page navigation with support for multi-page navigation and preview.

        Args:
            navigate_count: Number of pages to navigate (defaults to 1).
                          Positive values navigate forward, negative values backward.
            preview_count: Number of pages to preview and then return (defaults to 0).
                         Positive values preview forward, negative values backward.
            show_placemark: Whether to show placemark in reading progress.
            use_base64: Whether to return base64 encoded image.
            perform_ocr: Whether to perform OCR on the image.

        Returns:
            Tuple of (response_data, status_code)
        """
        # Determine the navigation direction from navigate_count
        direction_forward = navigate_count >= 0
        # Use absolute value for the actual navigation count
        abs_navigate_count = abs(navigate_count)

        # Similarly determine preview direction from preview_count
        preview_direction_forward = preview_count >= 0
        abs_preview_count = abs(preview_count)

        logger.info(
            f"Navigation request: navigate={navigate_count}, preview={preview_count}, "
            f"direction={'forward' if direction_forward else 'backward'}, "
            f"placemark={show_placemark}, base64={use_base64}, ocr={perform_ocr}"
        )

        # If navigate_count is 0 and no preview is requested, just return current page info
        if navigate_count == 0 and preview_count == 0:
            # Get current page info without navigation
            progress = self.automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )

            # Take screenshot
            screenshot_id = f"page_{int(time.time())}"
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.automator.driver.save_screenshot(screenshot_path)

            response_data = {
                "success": True,
                "progress": progress,
                "message": "Current page info (no navigation)",
            }

            # Process the screenshot
            screenshot_path = get_image_path(screenshot_id)
            screenshot_data = process_screenshot_response(
                screenshot_id, screenshot_path, use_base64, perform_ocr
            )
            response_data.update(screenshot_data)

            return response_data, 200

        # If we're doing a preview with navigate_count=0, handle it specially
        if preview_count != 0 and navigate_count == 0:
            if preview_direction_forward:
                return self._preview_pages_forward(abs_preview_count, show_placemark)
            else:
                return self._preview_pages_backward(abs_preview_count, show_placemark)

        # First handle regular navigation
        success = self._navigate_pages(direction_forward, abs_navigate_count)

        if not success:
            return {"error": "Navigation failed"}, 500

        # If preview was requested, handle it after navigating
        preview_ocr_text = None
        if success and preview_count != 0:
            if preview_direction_forward:
                preview_success, preview_ocr_text = self._preview_multiple_pages_forward(abs_preview_count)
            else:
                preview_success, preview_ocr_text = self._preview_multiple_pages_backward(abs_preview_count)

            if preview_success and preview_ocr_text:
                # Get current page data after navigation
                progress = self.automator.state_machine.reader_handler.get_reading_progress(
                    show_placemark=show_placemark
                )

                # When preview is requested, we're primarily interested in the OCR text
                response_data = {"success": True, "progress": progress, "ocr_text": preview_ocr_text}
                return response_data, 200

        # Standard navigation response with screenshot
        # Get current page number and progress
        progress = self.automator.state_machine.reader_handler.get_reading_progress(
            show_placemark=show_placemark
        )

        # Save screenshot with unique ID
        screenshot_id = f"page_{int(time.time())}"
        time.sleep(0.5)
        screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
        self.automator.driver.save_screenshot(screenshot_path)

        response_data = {
            "success": True,
            "progress": progress,
        }

        # Process the screenshot (either base64 encode, add URL, or OCR)
        screenshot_path = get_image_path(screenshot_id)
        screenshot_data = process_screenshot_response(screenshot_id, screenshot_path, use_base64, perform_ocr)
        response_data.update(screenshot_data)

        return response_data, 200

    def _navigate_pages(self, forward: bool, count: int) -> bool:
        """Navigate multiple pages forward or backward.

        Args:
            forward: True to navigate forward, False to navigate backward
            count: Number of pages to navigate.

        Returns:
            bool: True if navigation was successful, False otherwise.
        """
        if count <= 0:
            # No navigation needed
            return True

        logger.info(f"Navigating {count} pages {'forward' if forward else 'backward'}")

        success = True
        for i in range(count):
            if forward:
                page_success = self.automator.state_machine.reader_handler.turn_page_forward()
            else:
                page_success = self.automator.state_machine.reader_handler.turn_page_backward()

            if not page_success:
                logger.error(f"Failed to navigate on page {i+1} of {count}")
                success = False
                break

            # Add a small delay between page turns
            if i < count - 1:
                time.sleep(0.5)

        return success

    def _preview_multiple_pages_forward(self, count: int) -> Tuple[bool, Optional[str]]:
        """Preview multiple pages forward, then return to original position.

        Args:
            count: Number of pages to preview forward.

        Returns:
            Tuple of (success, ocr_text)
        """
        if count <= 0:
            return False, None

        logger.info(f"Previewing {count} pages forward")

        # Navigate forward the specified number of pages
        forward_success = self._navigate_pages(forward=True, count=count)
        if not forward_success:
            logger.error("Failed to navigate forward during preview")
            return False, None

        # Capture OCR from the preview page
        ocr_text, error_msg = self._extract_screenshot_for_ocr(f"preview_forward_{count}")

        # Now navigate back to original position
        backward_success = self._navigate_pages(forward=False, count=count)
        if not backward_success:
            logger.error("Failed to navigate back to original page after preview")
            # Still continue to return the OCR text even if we couldn't navigate back

        if ocr_text:
            logger.info(f"Successfully previewed {count} pages forward and extracted OCR text")
            return True, ocr_text
        else:
            logger.error(f"Failed to extract OCR text from preview: {error_msg}")
            return False, None

    def _preview_multiple_pages_backward(self, count: int) -> Tuple[bool, Optional[str]]:
        """Preview multiple pages backward, then return to original position.

        Args:
            count: Number of pages to preview backward.

        Returns:
            Tuple of (success, ocr_text)
        """
        if count <= 0:
            return False, None

        logger.info(f"Previewing {count} pages backward")

        # Navigate backward the specified number of pages
        backward_success = self._navigate_pages(forward=False, count=count)
        if not backward_success:
            logger.error("Failed to navigate backward during preview")
            return False, None

        # Capture OCR from the preview page
        ocr_text, error_msg = self._extract_screenshot_for_ocr(f"preview_backward_{count}")

        # Now navigate forward to original position
        forward_success = self._navigate_pages(forward=True, count=count)
        if not forward_success:
            logger.error("Failed to navigate back to original page after preview")
            # Still continue to return the OCR text even if we couldn't navigate back

        if ocr_text:
            logger.info(f"Successfully previewed {count} pages backward and extracted OCR text")
            return True, ocr_text
        else:
            logger.error(f"Failed to extract OCR text from preview: {error_msg}")
            return False, None

    def _preview_pages_forward(self, count: int, show_placemark: bool) -> Tuple[Dict, int]:
        """Preview pages forward without navigating from current position.

        Args:
            count: Number of pages to preview forward.
            show_placemark: Whether to show placemark in reading progress.

        Returns:
            Tuple of (response_data, status_code)
        """
        logger.info(f"Handling _preview_pages_forward with count={count}")
        success, ocr_text = self._preview_multiple_pages_forward(count)
        if success and ocr_text:
            response_data = {"success": True, "ocr_text": ocr_text}
            # Get reading progress but don't show placemark
            progress = self.automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )
            if progress:
                response_data["progress"] = progress
            return response_data, 200
        else:
            return {"error": f"Failed to preview {count} pages forward"}, 500

    def _preview_pages_backward(self, count: int, show_placemark: bool) -> Tuple[Dict, int]:
        """Preview pages backward without navigating from current position.

        Args:
            count: Number of pages to preview backward.
            show_placemark: Whether to show placemark in reading progress.

        Returns:
            Tuple of (response_data, status_code)
        """
        logger.info(f"Handling _preview_pages_backward with count={count}")
        success, ocr_text = self._preview_multiple_pages_backward(count)
        if success and ocr_text:
            response_data = {"success": True, "ocr_text": ocr_text}
            # Get reading progress but don't show placemark
            progress = self.automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )
            if progress:
                response_data["progress"] = progress
            return response_data, 200
        else:
            return {"error": f"Failed to preview {count} pages backward"}, 500

    def _extract_screenshot_for_ocr(self, prefix: str) -> Tuple[Optional[str], Optional[str]]:
        """Take a screenshot and perform OCR on it.

        Args:
            prefix: Prefix for the screenshot filename

        Returns:
            tuple: (ocr_text, error_message) - OCR text if successful, error message if failed
        """
        try:
            # Give the page a moment to render fully
            time.sleep(0.5)

            # Take screenshot
            screenshot_id = f"{prefix}_{int(time.time())}"
            screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")
            self.automator.driver.save_screenshot(screenshot_path)

            # Get OCR text from screenshot
            ocr_text = None
            error_msg = None

            try:
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                ocr_text, error_msg = KindleOCR.process_ocr(image_data)

                # Delete the screenshot file after processing
                try:
                    os.remove(screenshot_path)
                    logger.info(f"Deleted screenshot after OCR processing: {screenshot_path}")
                except Exception as del_e:
                    logger.error(f"Failed to delete screenshot {screenshot_path}: {del_e}")

            except Exception as e:
                logger.error(f"Error processing OCR: {e}")
                error_msg = str(e)

            return ocr_text, error_msg

        except Exception as e:
            logger.error(f"Error taking screenshot for OCR: {e}")
            return None, str(e)

    @staticmethod
    def parse_navigation_params(request_obj) -> Dict[str, Union[int, bool]]:
        """Parse navigation parameters from request.

        Args:
            request_obj: The Flask request object.

        Returns:
            Dictionary of parsed parameters.
        """
        # Initialize with default values
        params = {
            "navigate_count": 1,  # Default to 1 page navigation
            "preview_count": 0,  # Default to no preview
            "show_placemark": False,
            "use_base64": False,
            "perform_ocr": False,
        }

        # Check for navigate parameter in query string
        navigate_param = request_obj.args.get("navigate")
        if navigate_param:
            try:
                params["navigate_count"] = int(navigate_param)
            except ValueError:
                logger.warning(f"Invalid navigate value: {navigate_param}, using default")

        # Check for preview parameter in query string
        preview_param = request_obj.args.get("preview")
        if preview_param:
            try:
                params["preview_count"] = int(preview_param)
                # Only set perform_ocr to True if preview is non-zero
                if params["preview_count"] != 0:
                    params["perform_ocr"] = True
            except ValueError:
                # Handle "1" or "true" values
                if preview_param.lower() in ("1", "true"):
                    params["preview_count"] = 1
                    params["perform_ocr"] = True

        # Check for placemark parameter
        placemark_param = request_obj.args.get("placemark", "0")
        params["show_placemark"] = placemark_param.lower() in ("1", "true", "yes")

        # Check if base64 parameter is provided
        params["use_base64"] = is_base64_requested()

        # Check if OCR is requested via query params
        # Note: This will already be True if preview was requested
        if not params["perform_ocr"]:
            params["perform_ocr"] = is_ocr_requested()

        # If OCR is requested, force base64 encoding
        if params["perform_ocr"] and not params["use_base64"]:
            params["use_base64"] = True

        # If request has JSON body, check for parameters there too
        if request_obj.is_json:
            try:
                json_data = request_obj.get_json(silent=True) or {}

                # Override action if provided in JSON
                if "action" in json_data and json_data["action"]:
                    params["action"] = json_data["action"]

                # Override navigate_count if provided in JSON
                if "navigate" in json_data:
                    try:
                        params["navigate_count"] = int(json_data["navigate"])
                    except (ValueError, TypeError):
                        # If it's a boolean true, treat as 1
                        if isinstance(json_data["navigate"], bool) and json_data["navigate"]:
                            params["navigate_count"] = 1

                # Override preview_count if provided in JSON
                if "preview" in json_data:
                    try:
                        params["preview_count"] = int(json_data["preview"])
                        # Only set perform_ocr to True if preview is non-zero
                        if params["preview_count"] != 0:
                            params["perform_ocr"] = True
                    except (ValueError, TypeError):
                        # If it's a boolean true, treat as 1
                        if isinstance(json_data["preview"], bool) and json_data["preview"]:
                            params["preview_count"] = 1
                            params["perform_ocr"] = True

                # Override placemark if provided in JSON
                if "placemark" in json_data:
                    placemark_param = json_data["placemark"]
                    if isinstance(placemark_param, bool):
                        params["show_placemark"] = placemark_param
                    elif isinstance(placemark_param, str):
                        params["show_placemark"] = placemark_param.lower() in ("1", "true", "yes")
                    elif isinstance(placemark_param, int):
                        params["show_placemark"] = placemark_param == 1

            except Exception as e:
                logger.warning(f"Error parsing JSON request body: {e}")

        return params
