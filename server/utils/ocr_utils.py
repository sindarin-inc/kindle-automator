"""
Utility functions for OCR (Optical Character Recognition) on Kindle screenshots.

This module provides functions to:
1. Process screenshots with OCR
2. Handle base64 image encoding/decoding
3. Manage OCR requests from the API
"""

import base64
import concurrent.futures
import logging
import os
from typing import Optional, Tuple

from flask import request
from mistralai import Mistral

logger = logging.getLogger(__name__)


class KindleOCR:
    """Utility class for OCR processing of Kindle screenshots."""

    @staticmethod
    def process_ocr(image_content) -> Tuple[Optional[str], Optional[str]]:
        """
        Process an image with Mistral's OCR API.

        Args:
            image_content: Either binary content (bytes) or a base64-encoded string

        Returns:
            A tuple of (OCR text result or None if processing failed, error message if an error occurred)
        """
        try:
            # Determine if the input is already a base64 string or binary data
            if isinstance(image_content, str):
                # It's already a base64 string
                base64_image = image_content
                # Verify it's valid base64 by attempting to decode a small part
                try:
                    base64.b64decode(base64_image[:20])
                except:
                    error_msg = "Invalid base64 string provided"
                    logger.error(error_msg)
                    return None, error_msg
            else:
                # It's binary data, encode it as base64
                base64_image = base64.b64encode(image_content).decode("utf-8")

            # Get API key from environment variables (loaded from .env)
            api_key = os.getenv("MISTRAL_API_KEY")
            if not api_key:
                error_msg = (
                    "MISTRAL_API_KEY not found in environment variables. Please add it to your .env file."
                )
                logger.error(error_msg)
                return None, error_msg

            # Initialize Mistral client
            client = Mistral(api_key=api_key)

            # Implement our own timeout using ThreadPoolExecutor
            TIMEOUT_SECONDS = 10

            # Define the OCR function that will run in a separate thread
            def run_ocr():
                ocr_response = client.ocr.process(
                    model="mistral-ocr-latest",
                    document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"},
                )

                if ocr_response and hasattr(ocr_response, "pages") and len(ocr_response.pages) > 0:
                    page = ocr_response.pages[0]
                    return page.markdown
                else:
                    logger.error(f"No OCR response or no pages found: {ocr_response}")
                return None

            # Execute with timeout
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Submit the OCR task to the executor
                    future = executor.submit(run_ocr)

                    try:
                        # Wait for the result with a timeout
                        ocr_text = future.result(timeout=TIMEOUT_SECONDS)

                        if ocr_text:
                            logger.info("OCR processing successful")
                            return ocr_text, None
                        else:
                            error_msg = "No OCR response or no pages found"
                            logger.error(error_msg)
                            return None, error_msg

                    except concurrent.futures.TimeoutError:
                        # Cancel the future if it times out
                        future.cancel()
                        error_msg = f"OCR request timed out after {TIMEOUT_SECONDS} seconds"
                        logger.error(error_msg)
                        return None, error_msg

            except Exception as e:
                error_msg = f"Error during OCR processing with timeout: {e}"
                logger.error(error_msg)
                return None, error_msg

        except Exception as e:
            error_msg = f"Error processing OCR: {e}"
            logger.error(error_msg)
            return None, error_msg


def is_base64_requested():
    """Check if base64 format is requested in query parameters or JSON body.

    Returns:
        Boolean indicating whether base64 was requested
    """
    # Check URL query parameters first
    use_base64 = request.args.get("base64", "0") == "1"

    # If not in URL parameters, check JSON body
    if not use_base64 and request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            base64_param = json_data.get("base64", False)
            if isinstance(base64_param, bool):
                use_base64 = base64_param
            elif isinstance(base64_param, str):
                use_base64 = base64_param == "1" or base64_param.lower() == "true"
            elif isinstance(base64_param, int):
                use_base64 = base64_param == 1
        except Exception as e:
            logger.warning(f"Error parsing JSON for base64 parameter: {e}")

    return use_base64


def is_ocr_requested():
    """Check if OCR is requested in query parameters or JSON body.

    Returns:
        Boolean indicating whether OCR was requested
    """
    # Check URL query parameters first - match exactly how other query params are checked
    ocr_param = request.args.get("ocr", "0")
    text_param = request.args.get("text", "0")
    preview_param = request.args.get("preview", "0")

    perform_ocr = ocr_param in ("1", "true") or text_param in ("1", "true") or preview_param in ("1", "true")

    logger.debug(
        f"is_ocr_requested check - query params 'ocr': {ocr_param}, 'text': {text_param}, 'preview': {preview_param}, result: {perform_ocr}"
    )

    # If not in URL parameters, check JSON body
    if not perform_ocr and request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            ocr_param = json_data.get("ocr", False)
            text_param = json_data.get("text", False)
            preview_param = json_data.get("preview", False)

            # Check OCR parameter
            if isinstance(ocr_param, bool):
                perform_ocr = ocr_param
            elif isinstance(ocr_param, str):
                perform_ocr = ocr_param == "1" or ocr_param.lower() == "true"
            elif isinstance(ocr_param, int):
                perform_ocr = ocr_param == 1

            # Check text parameter if OCR is still False
            if not perform_ocr:
                if isinstance(text_param, bool):
                    perform_ocr = text_param
                elif isinstance(text_param, str):
                    perform_ocr = text_param == "1" or text_param.lower() == "true"
                elif isinstance(text_param, int):
                    perform_ocr = text_param == 1

            # Check preview parameter if OCR is still False
            if not perform_ocr:
                if isinstance(preview_param, bool):
                    perform_ocr = preview_param
                elif isinstance(preview_param, str):
                    perform_ocr = preview_param == "1" or preview_param.lower() == "true"
                elif isinstance(preview_param, int):
                    perform_ocr = preview_param == 1

            logger.debug(
                f"is_ocr_requested check - JSON params 'ocr': {ocr_param}, 'text': {text_param}, 'preview': {preview_param}, result: {perform_ocr}"
            )
        except Exception as e:
            logger.warning(f"Error parsing JSON for OCR parameters: {e}")

    return perform_ocr


def process_screenshot_response(screenshot_id, screenshot_path, use_base64=False, perform_ocr=False):
    """Process screenshot for API response - either adding URL, base64-encoded image, or OCR text.

    Args:
        screenshot_id: The ID of the screenshot
        screenshot_path: The full path to the screenshot file
        use_base64: Whether to use base64 encoding
        perform_ocr: Whether to perform OCR on the image

    Returns:
        Dictionary with screenshot information (URL, base64, or OCR text)
    """
    result = {}
    delete_after = use_base64 or perform_ocr  # Delete the image if we're encoding it or OCR'ing it

    # If OCR is requested, we need to process the image
    if perform_ocr:
        try:
            # Read the image file
            with open(screenshot_path, "rb") as img_file:
                image_data = img_file.read()

            # Process the image with OCR
            ocr_text, error = KindleOCR.process_ocr(image_data)

            if ocr_text:
                # If OCR successful, just add the text to the result and don't include the image
                # Don't include base64 or URL to save bandwidth and storage
                result["ocr_text"] = ocr_text
                # Always delete the image after successful OCR
                delete_after = True
            else:
                # If OCR failed, add the error and fall back to regular image handling
                result["ocr_error"] = error or "Unknown OCR error"
                # Fall back to base64 or URL
                if use_base64:
                    encoded_image = base64.b64encode(image_data).decode("utf-8")
                    result["screenshot_base64"] = encoded_image
                else:
                    # Return URL to image and don't delete file
                    image_url = f"/image/{screenshot_id}"
                    result["screenshot_url"] = image_url
                    delete_after = False
        except Exception as e:
            logger.error(f"Error processing OCR: {e}")
            result["ocr_error"] = f"Failed to process image for OCR: {str(e)}"
            # Fall back to regular image handling
            if use_base64:
                try:
                    with open(screenshot_path, "rb") as img_file:
                        encoded_image = base64.b64encode(img_file.read()).decode("utf-8")
                        result["screenshot_base64"] = encoded_image
                except Exception as e2:
                    logger.error(f"Error encoding image to base64: {e2}")
                    result["error"] = f"Failed to encode image to base64: {str(e2)}"
            else:
                # Return URL to image and don't delete file
                image_url = f"/image/{screenshot_id}"
                result["screenshot_url"] = image_url
                delete_after = False
    elif use_base64:
        # Base64 encoding without OCR
        try:
            with open(screenshot_path, "rb") as img_file:
                encoded_image = base64.b64encode(img_file.read()).decode("utf-8")
                result["screenshot_base64"] = encoded_image
        except Exception as e:
            logger.error(f"Error encoding image to base64: {e}")
            result["error"] = f"Failed to encode image to base64: {str(e)}"
    else:
        # Regular URL handling
        image_url = f"/image/{screenshot_id}"
        result["screenshot_url"] = image_url
        delete_after = False  # Don't delete file when using URL

    # Delete the image file if needed
    if delete_after:
        try:
            os.remove(screenshot_path)
            logger.info(f"Deleted image after processing: {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to delete image {screenshot_path}: {e}")

    return result
