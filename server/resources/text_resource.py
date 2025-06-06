"""Text resource for OCR text extraction."""

import logging
import os
import time
import traceback

from flask import request
from flask_restful import Resource
from selenium.common import exceptions as selenium_exceptions

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.ocr_utils import KindleOCR
from server.utils.request_utils import get_automator_for_request
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class TextResource(Resource):
    """Resource for extracting text from the current reading page."""

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
    def _extract_text(self):
        """Shared implementation for extracting text from the current reading page."""
        try:
            automator, _, error_response = get_automator_for_request(self.server)
            if error_response:
                return error_response

            # Make sure we're in the READING state
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state

            if current_state != AppState.READING:
                return {
                    "error": f"Must be in reading state to extract text, current state: {current_state.name}",
                }, 400

            # Before proceeding, manually check and dismiss the "About this book" slideover
            # This is needed because it can prevent accessing the reading controls
            try:
                from views.reading.interaction_strategies import (
                    ABOUT_BOOK_SLIDEOVER_IDENTIFIERS,
                    BOTTOM_SHEET_IDENTIFIERS,
                )

                # Check if About Book slideover is visible
                about_book_visible = False
                for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                    try:
                        slideover = automator.driver.find_element(strategy, locator)
                        if slideover.is_displayed():
                            about_book_visible = True
                            logger.info("Found 'About this book' slideover that must be dismissed before OCR")
                            break
                    except selenium_exceptions.NoSuchElementException:
                        continue

                if about_book_visible:
                    # Try multiple dismissal methods

                    # Method 1: Try tapping at the very top of the screen
                    window_size = automator.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    top_y = int(window_size["height"] * 0.05)  # 5% from top
                    automator.driver.tap([(center_x, top_y)])
                    logger.info("Tapped at the very top of the screen to dismiss 'About this book' slideover")
                    time.sleep(1)

                    # Verify if it worked
                    still_visible = False
                    for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = automator.driver.find_element(strategy, locator)
                            if slideover.is_displayed():
                                still_visible = True
                                break
                        except selenium_exceptions.NoSuchElementException:
                            continue

                    if still_visible:
                        # Method 2: Try swiping down (from 30% to 70% of screen height)
                        logger.info("First dismissal attempt failed. Trying swipe down method...")
                        start_y = int(window_size["height"] * 0.3)
                        end_y = int(window_size["height"] * 0.7)
                        automator.driver.swipe(center_x, start_y, center_x, end_y, 300)
                        logger.info("Swiped down to dismiss 'About this book' slideover")
                        time.sleep(1)

                        # Method 3: Try clicking the pill if it exists
                        try:
                            pill = automator.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[1])
                            if pill.is_displayed():
                                pill.click()
                                logger.info("Clicked pill to dismiss 'About this book' slideover")
                                time.sleep(1)
                        except selenium_exceptions.NoSuchElementException:
                            logger.info("Pill not found or not visible")

                    # Report final status
                    still_visible = False
                    for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = automator.driver.find_element(strategy, locator)
                            if slideover.is_displayed():
                                still_visible = True
                                logger.warning(
                                    "'About this book' slideover is still visible after multiple dismissal attempts"
                                )
                                break
                        except selenium_exceptions.NoSuchElementException:
                            continue

                    if not still_visible:
                        logger.info("Successfully dismissed the 'About this book' slideover")
            except Exception as e:
                logger.error(f"Error while attempting to dismiss 'About this book' slideover: {e}")

            # Save screenshot with unique ID
            screenshot_id = f"text_extract_{int(time.time())}"
            screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
            automator.driver.save_screenshot(screenshot_path)

            # Get current page number and progress for context
            # Check if placemark is requested
            show_placemark = False
            placemark_param = request.args.get("placemark", "0")
            if placemark_param.lower() in ("1", "true", "yes"):
                show_placemark = True
                logger.info("Placemark mode enabled for OCR")

            # Also check in POST data
            if not show_placemark and request.is_json:
                data = request.get_json(silent=True) or {}
                placemark_param = data.get("placemark", "0")
                if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                    show_placemark = True
                    logger.info("Placemark mode enabled from POST data for OCR")

            progress = automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )

            # Process the screenshot with OCR
            try:
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                # Process the image with OCR
                ocr_text, error = KindleOCR.process_ocr(image_data)

                # Delete the screenshot file after processing
                try:
                    os.remove(screenshot_path)
                    logger.info(f"Deleted screenshot after OCR processing: {screenshot_path}")
                except Exception as del_e:
                    logger.error(f"Failed to delete screenshot {screenshot_path}: {del_e}")

                if ocr_text:
                    return {"success": True, "progress": progress, "text": ocr_text}, 200
                else:
                    return {
                        "success": False,
                        "progress": progress,
                        "error": error or "OCR processing failed",
                    }, 500

            except Exception as e:
                logger.error(f"Error processing OCR: {e}")
                return {
                    "success": False,
                    "progress": progress,
                    "error": f"Failed to extract text: {str(e)}",
                }, 500

        except Exception as e:
            logger.error(f"Error extracting text: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Get OCR text of the current reading page without turning the page."""
        return self._extract_text()

    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """POST endpoint for OCR text extraction (identical to GET but allows for future parameters)."""
        return self._extract_text()
