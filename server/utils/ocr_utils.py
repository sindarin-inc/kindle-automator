"""
Utility functions for OCR (Optical Character Recognition) on Kindle screenshots.

This module provides functions to:
1. Process screenshots with OCR
2. Handle base64 image encoding/decoding
3. Manage OCR requests from the API
"""

import base64
import concurrent.futures
import json
import logging
import os
import re
import tempfile
from typing import Optional, Tuple

from flask import request
from google.cloud import documentai
from google.oauth2 import service_account
from mistralai import Mistral

logger = logging.getLogger(__name__)


class KindleOCR:
    """Utility class for OCR processing of Kindle screenshots."""

    GOOGLE_PROCESSOR_ID = "cfe27fea8a15b664"
    GOOGLE_PROJECT_ID = "313170199812"
    GOOGLE_LOCATION = "us"

    @staticmethod
    def _setup_google_credentials():
        """Setup Google credentials from environment, supporting both file path and base64-encoded JSON."""
        # First check for base64-encoded JSON
        base64_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
        if base64_creds:
            try:
                # Decode the base64 string
                json_str = base64.b64decode(base64_creds).decode("utf-8")
                # Parse the JSON to validate it
                json.loads(json_str)

                # Create a temporary file for the credentials
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
                    temp_file.write(json_str)
                    temp_path = temp_file.name

                # Set the environment variable to point to the temp file
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
                logger.info(f"Created temporary credentials file at {temp_path}")
                return temp_path
            except Exception as e:
                logger.error(f"Failed to decode base64 Google credentials: {e}", exc_info=True)
                return None

        # Check if GOOGLE_APPLICATION_CREDENTIALS is already set
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.info("Using existing GOOGLE_APPLICATION_CREDENTIALS")
            return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        return None

    @staticmethod
    def _process_with_google_document_ai(image_content) -> Tuple[Optional[str], Optional[str]]:
        """
        Process an image with Google Document AI.

        Args:
            image_content: Either binary content (bytes) or a base64-encoded string

        Returns:
            A tuple of (OCR text result or None if processing failed, error message if an error occurred)
        """
        temp_creds_path = None
        try:
            # Setup credentials
            temp_creds_path = KindleOCR._setup_google_credentials()

            if not temp_creds_path and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                error_msg = "No Google credentials found. Please set GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 or GOOGLE_APPLICATION_CREDENTIALS"
                logger.error(error_msg, exc_info=True)
                return None, error_msg

            # Initialize the Document AI client
            client = documentai.DocumentProcessorServiceClient()

            # The full resource name of the processor
            processor_name = client.processor_path(
                KindleOCR.GOOGLE_PROJECT_ID, KindleOCR.GOOGLE_LOCATION, KindleOCR.GOOGLE_PROCESSOR_ID
            )

            # Convert image to bytes if it's a base64 string
            if isinstance(image_content, str):
                try:
                    image_bytes = base64.b64decode(image_content)
                except Exception:
                    error_msg = "Invalid base64 string provided for Google Document AI"
                    logger.error(error_msg, exc_info=True)
                    return None, error_msg
            else:
                image_bytes = image_content

            # Create a raw document from the image
            raw_document = documentai.RawDocument(
                content=image_bytes, mime_type="image/jpeg"  # Assuming JPEG, adjust if needed
            )

            # Configure the process request
            request = documentai.ProcessRequest(name=processor_name, raw_document=raw_document)

            # Use ThreadPoolExecutor for timeout handling
            TIMEOUT_SECONDS = 10

            def run_google_ocr():
                try:
                    result = client.process_document(request=request)
                    return result
                except Exception as e:
                    logger.error(f"Error processing Google Document AI OCR: {e}", exc_info=True)
                    return None

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_google_ocr)
                try:
                    result = future.result(timeout=TIMEOUT_SECONDS)
                    if result and result.document and result.document.text:
                        logger.info("Google Document AI OCR processing successful")
                        return result.document.text.strip(), None
                    else:
                        error_msg = "No text found in Google Document AI response"
                        logger.error(error_msg, exc_info=True)
                        return None, error_msg
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    error_msg = f"Google Document AI OCR request timed out after {TIMEOUT_SECONDS} seconds"
                    logger.error(error_msg, exc_info=True)
                    return None, error_msg

        except Exception as e:
            error_msg = f"Error processing Google Document AI OCR: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg
        finally:
            # Clean up temporary credentials file if created
            if temp_creds_path and temp_creds_path.startswith(tempfile.gettempdir()):
                try:
                    os.remove(temp_creds_path)
                    logger.info(f"Cleaned up temporary credentials file: {temp_creds_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp credentials file: {e}")

    @staticmethod
    def _process_with_mistral(image_content) -> Tuple[Optional[str], Optional[str]]:
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
                    error_msg = "Invalid base64 string provided for MistralAI"
                    logger.error(error_msg, exc_info=True)
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
                logger.error(error_msg, exc_info=True)
                return None, error_msg

            # Initialize Mistral client
            client = Mistral(api_key=api_key)

            # Implement our own timeout using ThreadPoolExecutor
            TIMEOUT_SECONDS = 10

            # Define the OCR function that will run in a separate thread
            def run_ocr():
                try:
                    ocr_response = client.ocr.process(
                        model="mistral-ocr-latest",
                        document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"},
                    )
                except Exception as e:
                    logger.error(f"Error processing MistralAI OCR: {e}", exc_info=True)
                    return None

                if ocr_response and hasattr(ocr_response, "pages") and len(ocr_response.pages) > 0:
                    page = ocr_response.pages[0]
                    return page.markdown
                else:
                    logger.error(
                        f"No MistralAI OCR response or no pages found: {ocr_response}", exc_info=True
                    )
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
                            logger.info("MistralAI OCR processing successful")
                            return ocr_text, None
                        else:
                            error_msg = "No MistralAI OCR response or no pages found"
                            logger.error(error_msg, exc_info=True)
                            return None, error_msg

                    except concurrent.futures.TimeoutError:
                        # Cancel the future if it times out
                        future.cancel()
                        error_msg = f"MistralAI OCR request timed out after {TIMEOUT_SECONDS} seconds"
                        logger.error(error_msg, exc_info=True)
                        return None, error_msg

            except Exception as e:
                error_msg = f"Error during MistralAI OCR processing with timeout: {e}"
                logger.error(error_msg, exc_info=True)
                return None, error_msg

        except Exception as e:
            error_msg = f"Error processing MistralAI OCR: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    @staticmethod
    def _clean_ocr_text(text: str) -> str:
        """
        Clean OCR text by removing Kindle UI elements like reading speed and progress.

        Args:
            text: Raw OCR text

        Returns:
            Cleaned text without UI elements
        """
        if not text:
            return text

        # Split text into lines
        lines = text.strip().split("\n")

        # Filter out lines that match common Kindle UI patterns
        cleaned_lines = []
        for line in lines:
            # Skip lines that match reading speed pattern (e.g., "Learning reading speed")
            if re.search(r"learning\s+reading\s+speed", line, re.IGNORECASE):
                continue

            # Skip lines that are just percentages (e.g., "87%")
            if re.match(r"^\s*\d{1,3}%\s*$", line):
                continue

            # Skip lines that match location/page patterns (e.g., "Location 123 of 456")
            if re.search(r"location\s+\d+\s+of\s+\d+", line, re.IGNORECASE):
                continue

            # Skip lines that are just page numbers or locations
            if re.match(r"^\s*(page\s+)?\d+\s*$", line, re.IGNORECASE):
                continue

            # Skip lines that match time left patterns (e.g., "5 min left in chapter", "2 mins left in chapter")
            if re.search(r"\d+\s*mins?\s*left\s*in\s*(chapter|book)", line, re.IGNORECASE):
                continue

            cleaned_lines.append(line)

        # Join the lines back together
        cleaned_text = "\n".join(cleaned_lines)

        # Handle hyphenated words at end of lines
        # Replace hyphen+newline with just the word (removing the hyphen)
        cleaned_text = re.sub(r"-\n([a-zA-Z])", r"\1", cleaned_text)

        # Replace single newlines with spaces, but preserve multiple newlines
        # First, temporarily replace 2+ newlines with a placeholder
        cleaned_text = re.sub(r"\n\n+", "\x00", cleaned_text)
        # Replace remaining single newlines with spaces
        cleaned_text = re.sub(r"\n", " ", cleaned_text)
        # Restore the multiple newlines
        cleaned_text = cleaned_text.replace("\x00", "\n\n")

        # Clean up any multiple spaces that may have been created
        cleaned_text = re.sub(r" +", " ", cleaned_text)

        # Remove any trailing whitespace
        cleaned_text = cleaned_text.strip()

        return cleaned_text

    @staticmethod
    def process_ocr(image_content) -> Tuple[Optional[str], Optional[str]]:
        """
        Process an image with OCR, trying Google Document AI first, then falling back to MistralAI.

        Args:
            image_content: Either binary content (bytes) or a base64-encoded string

        Returns:
            A tuple of (OCR text result or None if processing failed, error message if an error occurred)
        """
        # Try Google Document AI first
        logger.info("Attempting OCR with MistralAI...")
        ocr_text, mistral_error = KindleOCR._process_with_mistral(image_content)

        if ocr_text:
            cleaned_text = KindleOCR._clean_ocr_text(ocr_text)
            return cleaned_text, None

        # If Google fails, try MistralAI as fallback
        logger.warning(f"MistralAI failed: {mistral_error}. Falling back to Google Document AI...")
        ocr_text, google_error = KindleOCR._process_with_google_document_ai(image_content)

        if ocr_text:
            cleaned_text = KindleOCR._clean_ocr_text(ocr_text)
            return cleaned_text, None

        # Both failed, return combined error message
        combined_error = f"Both OCR services failed. Google: {google_error}; MistralAI: {mistral_error}"
        return None, combined_error


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


def is_ocr_requested(default=False):
    """Check if OCR is requested in query parameters or JSON body.

    Args:
        default: Boolean indicating the default value if no OCR parameter is specified

    Returns:
        Boolean indicating whether OCR was requested
    """
    # Check URL query parameters first - default based on the provided default
    default_value = "1" if default else "0"
    ocr_param = request.args.get("ocr", default_value)
    text_param = request.args.get("text", "0")
    preview_param = request.args.get("preview", "0")

    # OCR is enabled if set to "1" or "true", or if using default and not explicitly disabled
    if default:
        perform_ocr = (
            ocr_param not in ("0", "false") or text_param in ("1", "true") or preview_param in ("1", "true")
        )
    else:
        perform_ocr = (
            ocr_param in ("1", "true") or text_param in ("1", "true") or preview_param in ("1", "true")
        )

    logger.debug(
        f"is_ocr_requested check - query params 'ocr': {ocr_param}, 'text': {text_param}, 'preview': {preview_param}, result: {perform_ocr}"
    )

    # Check JSON body for override if needed
    if request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}

            # Only check JSON if 'ocr' key is present (don't use default here)
            if "ocr" in json_data:
                ocr_param = json_data["ocr"]
                # Check OCR parameter
                if isinstance(ocr_param, bool):
                    perform_ocr = ocr_param
                elif isinstance(ocr_param, str):
                    perform_ocr = ocr_param not in ("0", "false")
                elif isinstance(ocr_param, int):
                    perform_ocr = ocr_param != 0

            # Always check text and preview params if present
            text_param = json_data.get("text", False)
            preview_param = json_data.get("preview", False)

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
                # Log the length of the OCR text
                logger.info(f"OCR text extracted successfully, length: {len(ocr_text)} characters")
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
            logger.error(f"Error processing OCR: {e}", exc_info=True)
            result["ocr_error"] = f"Failed to process image for OCR: {str(e)}"
            # Fall back to regular image handling
            if use_base64:
                try:
                    with open(screenshot_path, "rb") as img_file:
                        encoded_image = base64.b64encode(img_file.read()).decode("utf-8")
                        result["screenshot_base64"] = encoded_image
                except Exception as e2:
                    logger.error(f"Error encoding image to base64: {e2}", exc_info=True)
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
            logger.error(f"Error encoding image to base64: {e}", exc_info=True)
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
            logger.error(f"Failed to delete image {screenshot_path}: {e}", exc_info=True)

    return result
