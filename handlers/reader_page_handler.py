"""Page indicator and screenshot handling for the Kindle reader."""

import base64
import logging
import os
import re
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)


def extract_page_indicator_region(image_bytes):
    """Extract the page indicator region from a screenshot.

    Args:
        image_bytes: The screenshot as bytes

    Returns:
        bytes: page_indicator_bytes - Cropped region as bytes
    """
    try:
        # Load the image
        img = Image.open(BytesIO(image_bytes))
        width, height = img.size

        # Define crop region based on proportions
        # Bottom-left for page/location indicator
        # The page number is in the bottom 6% of screen (bottom 80px of 1400px)
        page_indicator_box = (
            0,  # Left edge
            int(height * 0.94),  # Start at 94% from top (bottom 6%)
            int(width * 0.5),  # Left 50% of width
            height,  # Bottom edge
        )

        # Crop the region
        page_indicator_img = img.crop(page_indicator_box)

        # Convert back to bytes
        page_indicator_bytes = BytesIO()
        page_indicator_img.save(page_indicator_bytes, format="PNG")
        page_indicator_bytes = page_indicator_bytes.getvalue()

        logger.debug(f"Cropped page indicator region: {page_indicator_box}")

        return page_indicator_bytes

    except Exception as e:
        logger.error(f"Error extracting page indicator region: {e}", exc_info=True)
        return None


def process_screenshot_with_regions(image_bytes):
    """Process a screenshot to extract both main text and page information.

    Args:
        image_bytes: The screenshot as bytes

    Returns:
        dict: Contains 'main_text', 'page_indicator_text', and any errors
    """
    result = {"main_text": None, "page_indicator_text": None, "errors": []}

    try:
        # Import OCR processor
        from server.utils.ocr_utils import KindleOCR

        # Load the image once
        img = Image.open(BytesIO(image_bytes))
        width, height = img.size

        # Crop main text area (top 94%, excluding page numbers which are in bottom 6%)
        main_text_box = (
            0,  # Left edge
            0,  # Top edge
            width,  # Right edge
            int(height * 0.94),  # Stop at 94% from top (excludes bottom 6% where page numbers are)
        )
        main_text_img = img.crop(main_text_box)

        # Convert main text to bytes and OCR
        main_text_bytes = BytesIO()
        main_text_img.save(main_text_bytes, format="PNG")
        main_text_data = main_text_bytes.getvalue()

        main_ocr_text, main_error = KindleOCR.process_ocr(main_text_data)
        if main_ocr_text:
            result["main_text"] = main_ocr_text
        elif main_error:
            result["errors"].append(f"Main text OCR error: {main_error}")

        # Extract page indicator region
        page_indicator_bytes = extract_page_indicator_region(image_bytes)

        # OCR page indicator
        if page_indicator_bytes:
            page_text, page_error = KindleOCR.process_ocr(page_indicator_bytes, clean_ui_elements=False)
            if page_text:
                # Clean up the text - remove any extra whitespace
                page_text = " ".join(page_text.split())
                result["page_indicator_text"] = page_text
                logger.info(f"OCR: Page indicator extracted: '{page_text}'")
            elif page_error:
                result["errors"].append(f"Page indicator OCR error: {page_error}")

        return result

    except Exception as e:
        logger.error(f"Error processing screenshot with regions: {e}", exc_info=True)
        result["errors"].append(f"Processing error: {str(e)}")
        return result


def parse_page_indicators(page_indicator_text):
    """Parse page indicator text to extract structured progress data.

    Args:
        page_indicator_text: OCR text from page indicator region (e.g., "Page 123 of 456", "8 mins left in chapter")

    Returns:
        dict: Progress information with current_page/location, total_pages/locations, and/or time_left
    """
    progress = {}

    # Parse page indicator text
    if page_indicator_text:
        # Check for "Learning reading speed" - Kindle's initial state before showing time/page
        if re.search(r"learning\s+reading\s+speed", page_indicator_text, re.IGNORECASE):
            # This is a temporary state that needs cycling to get actual page/time info
            progress["time_left"] = "calculating"
            progress["needs_cycling"] = True
            logger.info(f"Detected 'Learning reading speed' - needs cycling to get actual indicator")
            progress["current_page"] = None
            progress["total_pages"] = None
        # Try to match page numbers
        elif match := re.search(r"(?:Page|page)\s+(\d+)\s+of\s+(\d+)", page_indicator_text):
            progress["current_page"] = int(match.group(1))
            progress["total_pages"] = int(match.group(2))
            logger.info(f"Extracted page info: {match.group(1)}/{match.group(2)}")
        # Try to match locations
        elif match := re.search(r"(?:Location|location)\s+(\d+)\s+of\s+(\d+)", page_indicator_text):
            progress["current_location"] = int(match.group(1))
            progress["total_locations"] = int(match.group(2))
        # Try to match time indicators
        elif match := re.search(
            r"(\d+)\s+(min|mins|minute|minutes|hour|hours|hr|hrs)\s+left", page_indicator_text
        ):
            unit = "min" if "min" in match.group(2) else "hour"
            progress["time_left"] = f"{match.group(1)} {unit}"
            logger.info(f"Extracted time-based indicator: {progress['time_left']}")
            progress["current_page"] = None
            progress["total_pages"] = None

    return progress


def cycle_page_indicator_if_needed(reader_handler, page_indicator_text):
    """If time-based indicator is detected, tap to cycle through formats to get page/location.

    Args:
        reader_handler: The ReaderHandler instance
        page_indicator_text: The OCR'd text from the page indicator region

    Returns:
        dict: Updated progress information with page/location data if found
    """
    # First parse what we have
    progress = parse_page_indicators(page_indicator_text)

    # Check if we got a time-based indicator or "Learning reading speed" instead of page/location
    if (
        progress
        and (progress.get("time_left") or progress.get("needs_cycling"))
        and not progress.get("current_page")
        and not progress.get("current_location")
    ):
        indicator_type = (
            "Learning reading speed" if progress.get("needs_cycling") else progress.get("time_left")
        )
        logger.info(
            f"Detected indicator requiring cycling: {indicator_type}. Attempting to cycle to page/location format"
        )

        try:
            # Use the rotate_page_format_with_ocr method to cycle through formats
            cycled_progress = reader_handler.rotate_page_format_with_ocr(max_taps=5)

            if cycled_progress:
                logger.info(f"Successfully cycled to format: {cycled_progress.get('display_format')}")
                # Update the progress with the cycled data
                if cycled_progress.get("current_page"):
                    progress["current_page"] = cycled_progress["current_page"]
                    progress["total_pages"] = cycled_progress.get("total_pages")
                elif cycled_progress.get("current_location"):
                    progress["current_location"] = cycled_progress["current_location"]
                    progress["total_locations"] = cycled_progress.get("total_locations")
            else:
                logger.warning("Could not find page/location format after cycling")
        except Exception as e:
            logger.error(f"Error cycling page indicator: {e}", exc_info=True)

    return progress


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

            # Use process_screenshot_with_regions to extract both main text and page indicators
            ocr_results = process_screenshot_with_regions(image_data)

            ocr_text = ocr_results.get("main_text")
            page_indicator_text = ocr_results.get("page_indicator_text")
            errors = ocr_results.get("errors", [])

            if ocr_text:
                # If OCR successful, add the text to the result
                result["ocr_text"] = ocr_text
                # Log the length of the OCR text
                logger.info(f"OCR text extracted successfully, length: {len(ocr_text)} characters")

                # Log what we got from the page regions
                logger.info(f"Page indicator text: '{page_indicator_text}'")

                # Parse and add page progress information if extracted
                # Note: We can't use cycle_page_indicator_if_needed here because we don't have access to the reader_handler
                # The cycling should be handled by the calling code that has access to the driver
                progress = parse_page_indicators(page_indicator_text)

                # Log the parsed progress
                logger.info(f"Parsed progress: {progress}")

                # Add progress to result if any info was extracted
                if progress:
                    result["progress"] = progress

                # Always delete the image after successful OCR
                delete_after = True
            else:
                # If OCR failed, add the error and fall back to regular image handling
                error_msg = "; ".join(errors) if errors else "Unknown OCR error"
                result["ocr_error"] = error_msg
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
