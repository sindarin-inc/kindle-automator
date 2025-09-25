"""Utilities for handling Kindle page indicators and progress information."""

import logging
import re

logger = logging.getLogger(__name__)


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


def cycle_page_indicator_if_needed(driver, page_indicator_text):
    """If time-based indicator is detected, tap to cycle through formats to get page/location.

    Args:
        driver: The Appium driver instance
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
            # Import reader handler to use its tap-to-cycle functionality
            from handlers.reader_handler import ReaderHandler

            # Create a reader handler instance
            reader = ReaderHandler(driver)

            # Use the rotate_page_format_with_ocr method to cycle through formats
            cycled_progress = reader.rotate_page_format_with_ocr(max_taps=5)

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
