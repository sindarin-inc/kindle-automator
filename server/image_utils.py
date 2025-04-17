import base64
import concurrent.futures
import logging
import os
import random
import string
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from flask import Response, make_response, send_file
from mistralai import Mistral

logger = logging.getLogger(__name__)


def get_image_path(image_id: str, server_instance=None) -> Optional[str]:
    """Get full path for an image file.

    Args:
        image_id: Image identifier
        server_instance: The server instance

    Returns:
        Full path to the image file or None if not found
    """
    if server_instance and server_instance.automator:
        # Try in the screenshots directory
        image_path = os.path.join(server_instance.automator.screenshots_dir, f"{image_id}.png")
        if os.path.exists(image_path):
            return image_path
    return None


def serve_image(image_id: str, server_instance=None, delete_after_serve: bool = False):
    """Serve an image by ID with option to delete after serving.

    Args:
        image_id: Image identifier
        server_instance: The server instance
        delete_after_serve: Whether to delete the image after serving

    Returns:
        Response with the image or error
    """
    image_path = get_image_path(image_id, server_instance)

    if not image_path:
        return {"error": f"Image not found: {image_id}"}, 404

    try:
        response = make_response(send_file(image_path, mimetype="image/png"))

        # If requested, delete the image after serving
        if delete_after_serve:
            try:
                # Use os.remove to delete file
                os.remove(image_path)
                logger.info(f"Deleted image after serving: {image_path}")
            except Exception as del_e:
                logger.error(f"Error deleting image {image_path}: {del_e}")

        return response
    except Exception as e:
        logger.error(f"Error serving image {image_path}: {e}")
        return {"error": f"Failed to serve image: {str(e)}"}, 500


def is_base64_requested() -> bool:
    """Check if base64 encoding is requested in a request.

    Returns:
        True if base64 encoding is requested
    """
    from flask import request

    # Check if base64 parameter is provided as URL param
    base64_param = request.args.get("base64", "0")
    if base64_param in ("1", "true"):
        return True

    # Check if encoding parameter is provided as URL param with value 'base64'
    encoding_param = request.args.get("encoding", "")
    if encoding_param.lower() == "base64":
        return True

    # Check JSON body if present
    if request.is_json:
        json_data = request.get_json(silent=True) or {}
        if json_data.get("base64", False) or json_data.get("encoding", "").lower() == "base64":
            return True

    # Check form data
    if request.form:
        if request.form.get("base64", "0") in ("1", "true"):
            return True
        if request.form.get("encoding", "").lower() == "base64":
            return True

    return False


def is_ocr_requested() -> bool:
    """Check if OCR is requested in a request.

    Returns:
        True if OCR is requested
    """
    from flask import request

    # Check if ocr parameter is provided as URL param
    ocr_param = request.args.get("ocr", "0")
    if ocr_param in ("1", "true"):
        return True

    # Check if text parameter is provided as URL param
    text_param = request.args.get("text", "0")
    if text_param in ("1", "true"):
        return True

    # Check JSON body if present
    if request.is_json:
        json_data = request.get_json(silent=True) or {}
        if json_data.get("ocr", False) or json_data.get("text", False):
            return True

    # Check form data
    if request.form:
        if request.form.get("ocr", "0") in ("1", "true"):
            return True
        if request.form.get("text", "0") in ("1", "true"):
            return True

    return False


class KindleOCR:
    """Class to process images for OCR using Mistral API."""

    def __init__(self, api_key=None):
        """Initialize the OCR processor.

        Args:
            api_key: Mistral API key
        """
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        self.client = Mistral(api_key=self.api_key) if self.api_key else None
        self.max_retries = 3

    def encode_image(self, image_data_or_path):
        """Encode an image as base64.

        Args:
            image_data_or_path: Path to the image file or binary image data

        Returns:
            Base64 encoded image data
        """
        # Check if input is a string (file path) or bytes (image data)
        if isinstance(image_data_or_path, str):
            # Input is a file path
            with open(image_data_or_path, "rb") as img_file:
                return base64.b64encode(img_file.read()).decode("utf-8")
        elif isinstance(image_data_or_path, bytes):
            # Input is binary data
            return base64.b64encode(image_data_or_path).decode("utf-8")
        else:
            raise TypeError("Input must be a file path or binary image data")

    def _process_with_base64_image(self, base64_image, max_timeout=60):
        """Internal method to process a base64 encoded image with OCR.
        
        Args:
            base64_image: Base64 encoded image
            max_timeout: Maximum timeout in seconds
            
        Returns:
            Tuple of (success, text or error)
        """
        if not self.client:
            return False, "Mistral API key not found"
            
        for attempt in range(self.max_retries):
            try:
                # Define a function to call the Mistral API
                def call_mistral_api():
                    return self.client.chat(
                        model="mistral-large-latest",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Extract all visible text from this Kindle app screenshot. Return ONLY the text content, with proper paragraphs preserved.",
                                    },
                                    {
                                        "type": "image",
                                        "image": base64_image,
                                    },
                                ],
                            }
                        ],
                        max_tokens=1024,
                    )
                    
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Submit the function as the callable
                    future = executor.submit(call_mistral_api)
                    # Wait for the result with a timeout
                    response = future.result(timeout=max_timeout)
                    return True, response.choices[0].message.content
                    
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"OCR processing timed out after {max_timeout} seconds (attempt {attempt+1}/{self.max_retries})"
                )
                if attempt == self.max_retries - 1:
                    return False, f"OCR processing timed out after {max_timeout} seconds"
            except Exception as e:
                logger.error(f"OCR processing failed on attempt {attempt+1}/{self.max_retries}: {e}")
                if attempt == self.max_retries - 1:
                    return False, f"OCR processing failed: {str(e)}"
                    
        return False, "OCR processing failed after all retries"
        
    def process_image(self, image_path, max_timeout=60):
        """Process an image with OCR.

        Args:
            image_path: Path to the image file
            max_timeout: Maximum timeout in seconds

        Returns:
            Tuple of (success, text or error)
        """
        if not self.client:
            return False, "Mistral API key not found"

        base64_image = self.encode_image(image_path)
        return self._process_with_base64_image(base64_image, max_timeout)
        
    def process_image_data(self, image_data, max_timeout=60):
        """Process image data with OCR.

        Args:
            image_data: Binary image data
            max_timeout: Maximum timeout in seconds

        Returns:
            Tuple of (success, text or error)
        """
        if not self.client:
            return False, "Mistral API key not found"

        base64_image = self.encode_image(image_data)
        return self._process_with_base64_image(base64_image, max_timeout)
        
    @staticmethod
    def process_ocr(image_data, max_timeout=60):
        """Static method to process image data with OCR.
        
        This is a convenience method for direct use without creating an instance.
        
        Args:
            image_data: Binary image data
            max_timeout: Maximum timeout in seconds
            
        Returns:
            Tuple of (ocr_text, error_message)
        """
        # Get API key from environment
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            return None, "Mistral API key not found"
            
        # Create instance and process
        ocr = KindleOCR(api_key=api_key)
        success, result = ocr.process_image_data(image_data, max_timeout)
        
        if success:
            return result, None
        else:
            return None, result


def process_screenshot_response(
    screenshot_path, include_xml=False, perform_ocr=False, use_base64=False, automator=None
):
    """Process a screenshot for API responses.

    Args:
        screenshot_path: Path to the screenshot
        include_xml: Whether to include XML page source
        perform_ocr: Whether to perform OCR on the image
        use_base64: Whether to encode the image as base64
        automator: The automator instance

    Returns:
        Processed response with requested data
    """
    response_data = {}

    # Handle non-existent screenshot
    if not screenshot_path or not os.path.exists(screenshot_path):
        response_data["error"] = "Failed to take screenshot"
        return response_data, 500

    # Get filename without path
    filename = os.path.basename(screenshot_path)
    screenshot_id = filename.split(".")[0]  # Remove extension

    # Include paths and URLs in response
    response_data["screenshot_id"] = screenshot_id
    response_data["image_url"] = f"/image/{screenshot_id}"

    # Include XML page source if requested and available
    if include_xml and automator and hasattr(automator, "driver") and automator.driver:
        try:
            # Store page source to file
            from pathlib import Path

            xml_filename = f"{screenshot_id}.xml"
            xml_path = os.path.join(Path(screenshot_path).parent, xml_filename)
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(automator.driver.page_source)
            response_data["xml_url"] = f"/xml/{screenshot_id}"
        except Exception as e:
            logger.error(f"Error capturing XML source: {e}")
            response_data["xml_error"] = str(e)

    # Add base64 image data if requested
    if use_base64:
        try:
            with open(screenshot_path, "rb") as img_file:
                img_data = base64.b64encode(img_file.read()).decode("utf-8")
                response_data["base64_image"] = img_data
        except Exception as e:
            logger.error(f"Error encoding image as base64: {e}")
            response_data["base64_error"] = str(e)

    # Perform OCR if requested
    if perform_ocr:
        try:
            # Get API key from environment
            api_key = os.environ.get("MISTRAL_API_KEY")
            if not api_key:
                logger.warning("Mistral API key not found for OCR")
                response_data["ocr_error"] = "OCR requires Mistral API key"
            else:
                # Create OCR instance and process the image
                ocr = KindleOCR(api_key=api_key)
                success, text = ocr.process_image(screenshot_path)
                if success:
                    # Use the "ocr_text" key to match previous implementation
                    response_data["ocr_text"] = text
                    response_data["text"] = text  # Also keep "text" for backward compatibility
                else:
                    response_data["ocr_error"] = text
        except Exception as e:
            logger.error(f"Error performing OCR: {e}")
            response_data["ocr_error"] = str(e)

    return response_data, 200
