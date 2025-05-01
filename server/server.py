"""Main Kindle Automator server module."""

import base64
import concurrent.futures
import logging
import os
import platform
import signal
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import flask
import requests
import urllib3
from appium.webdriver.common.appiumby import AppiumBy
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, redirect, request, send_file
from flask_restful import Api, Resource
from mistralai import Mistral
from selenium.common import exceptions as selenium_exceptions

from automator import KindleAutomator
from handlers.auth_handler import LoginVerificationState
from handlers.test_fixtures_handler import TestFixturesHandler
from server.config import VNC_BASE_URL
from server.core.automation_server import AutomationServer
from server.logging_config import setup_logger
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_logger import setup_request_logger
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_formatted_vnc_url, get_sindarin_email
from views.core.app_state import AppState

# Load environment variables from .env file
setup_logger()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")

# Load .env files with secrets
if ENVIRONMENT.lower() == "prod":
    logger.info(f"Loading prod environment variables from {os.path.join(BASE_DIR, '.env.prod')}")
    load_dotenv(os.path.join(BASE_DIR, ".env.prod"), override=True)
elif ENVIRONMENT.lower() == "staging":
    logger.info(f"Loading staging environment variables from {os.path.join(BASE_DIR, '.env.staging')}")
    load_dotenv(os.path.join(BASE_DIR, ".env.staging"), override=True)
else:
    logger.info(f"Loading dev environment variables from {os.path.join(BASE_DIR, '.env')}")
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


# Development mode detection
IS_DEVELOPMENT = os.getenv("FLASK_ENV") == "development"

# We'll handle captcha solutions at runtime when passed via API, not from environment

app = Flask(__name__)
api = Api(app)

# Set up request and response logging middleware
setup_request_logger(app)

# Create the server instance
server = AutomationServer()

# Store server instance in app config for access in middleware
app.config["server_instance"] = server


class InitializeResource(Resource):
    def post(self):
        """Explicitly initialize the automation driver.

        Note: This endpoint is optional as the system automatically initializes
        when needed on other endpoints. It can be used for pre-initialization.
        """
        try:
            # Initialize automator
            server.initialize_automator()
            success = server.automator.initialize_driver()

            if not success:
                return {"error": "Failed to initialize driver"}, 500

            # Clear the current book since we're reinitializing the app
            server.clear_current_book()

            return {
                "status": "initialized",
                "message": "Device initialized. Use /auth endpoint with VNC for manual authentication.",
            }, 200

        except Exception as e:
            logger.error(f"Initialization error: {e}")
            return {"error": str(e)}, 500


class StateResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        try:
            logger.info(f"Getting state, currently in {server.automator.state_machine.current_state}")
            server.automator.state_machine.update_current_state()
            current_state = server.automator.state_machine.current_state
            logger.info(f"Getting state, now in {current_state}")
            return {"state": current_state.name}, 200
        except Exception as e:
            logger.error(f"Error getting state: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class CaptchaResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Get current captcha status and image if present"""
        # Return simple success response - the response handler will
        # intercept if we're in CAPTCHA state
        return {"status": "no_captcha"}, 200

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Submit captcha solution"""
        data = request.get_json()
        solution = data.get("solution")

        if not solution:
            return {"error": "Captcha solution required"}, 400

        # Update captcha solution using our update method
        server.automator.update_captcha_solution(solution)

        success = server.automator.transition_to_library()

        if success:
            return {"status": "success"}, 200
        return {"error": "Failed to process captcha solution"}, 500


class BooksResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def _get_books(self):
        """Get list of available books with metadata"""
        current_state = server.automator.state_machine.current_state
        logger.info(f"Current state when getting books: {current_state}")

        # Handle different states
        if current_state != AppState.LIBRARY:
            # Check if we're on the sign-in screen
            if current_state == AppState.SIGN_IN or current_state == AppState.LIBRARY_SIGN_IN:
                # Get current email to include in VNC URL
                sindarin_email = get_sindarin_email(default_email=server.current_email)

                # Get the emulator ID for this email if possible
                emulator_id = None
                if sindarin_email and sindarin_email in server.automators:
                    automator = server.automators.get(sindarin_email)
                    if (
                        automator
                        and hasattr(automator, "emulator_manager")
                        and hasattr(automator.emulator_manager, "emulator_launcher")
                    ):
                        emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                            sindarin_email
                        )
                        logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                # Get the formatted VNC URL with the email and emulator ID
                formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

                logger.info("Authentication required - providing VNC URL for manual authentication")
                return {
                    "error": "Authentication required",
                    "requires_auth": True,
                    "current_state": current_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            # Try to transition to library state
            logger.info("Not in library state, attempting to transition...")
            transition_success = server.automator.state_machine.transition_to_library(server=server)

            # Get the updated state after transition attempt
            new_state = server.automator.state_machine.current_state
            logger.info(f"State after transition attempt: {new_state}")

            # Check for auth requirement regardless of transition success
            if new_state == AppState.SIGN_IN:
                # Get current email to include in VNC URL
                sindarin_email = get_sindarin_email(default_email=server.current_email)

                # Get the emulator ID for this email if possible
                emulator_id = None
                if sindarin_email and sindarin_email in server.automators:
                    automator = server.automators.get(sindarin_email)
                    if (
                        automator
                        and hasattr(automator, "emulator_manager")
                        and hasattr(automator.emulator_manager, "emulator_launcher")
                    ):
                        emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                            sindarin_email
                        )
                        logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                # Get the formatted VNC URL with the email and emulator ID
                formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

                logger.info("Authentication required after transition attempt - providing VNC URL")
                return {
                    "error": "Authentication required",
                    "requires_auth": True,
                    "current_state": new_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            if transition_success:
                logger.info("Successfully transitioned to library state")
                # Get books with metadata from library handler
                books = server.automator.library_handler.get_book_titles()

                # If books is None, it means authentication is required
                if books is None:
                    # Get current email to include in VNC URL
                    sindarin_email = get_sindarin_email(default_email=server.current_email)

                    # Get the emulator ID for this email if possible
                    emulator_id = None
                    if sindarin_email and sindarin_email in server.automators:
                        automator = server.automators.get(sindarin_email)
                        if (
                            automator
                            and hasattr(automator, "emulator_manager")
                            and hasattr(automator.emulator_manager, "emulator_launcher")
                        ):
                            emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                                sindarin_email
                            )
                            logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                    # Get the formatted VNC URL with the email and emulator ID
                    formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

                    logger.info("Authentication required - providing VNC URL for manual authentication")
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "message": "Authentication is required via VNC",
                        "emulator_id": emulator_id,
                    }, 401

                return {"books": books}, 200
            else:
                # If transition failed, check for auth requirement
                updated_state = server.automator.state_machine.current_state

                if updated_state == AppState.SIGN_IN:
                    # Get current email to include in VNC URL
                    sindarin_email = get_sindarin_email(default_email=server.current_email)

                    # Get the emulator ID for this email if possible
                    emulator_id = None
                    if sindarin_email and sindarin_email in server.automators:
                        automator = server.automators.get(sindarin_email)
                        if (
                            automator
                            and hasattr(automator, "emulator_manager")
                            and hasattr(automator.emulator_manager, "emulator_launcher")
                        ):
                            emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                                sindarin_email
                            )
                            logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                    # Get the formatted VNC URL with the email and emulator ID
                    formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

                    logger.info("Transition failed - authentication required - providing VNC URL")
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "current_state": updated_state.name,
                        "message": "Authentication is required via VNC",
                        "emulator_id": emulator_id,
                    }, 401
                else:
                    return {
                        "error": f"Cannot get books in current state: {updated_state.name}",
                        "current_state": updated_state.name,
                    }, 400

        # Get books with metadata from library handler
        books = server.automator.library_handler.get_book_titles()

        # If books is None, it means authentication is required
        if books is None:
            # Get current email to include in VNC URL
            sindarin_email = get_sindarin_email(default_email=server.current_email)

            # Get the emulator ID for this email if possible
            emulator_id = None
            if sindarin_email and sindarin_email in server.automators:
                automator = server.automators.get(sindarin_email)
                if (
                    automator
                    and hasattr(automator, "emulator_manager")
                    and hasattr(automator.emulator_manager, "emulator_launcher")
                ):
                    emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(sindarin_email)
                    logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

            # Get the formatted VNC URL with the email and emulator ID
            formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

            logger.info("Authentication required - providing VNC URL for manual authentication")
            return {
                "error": "Authentication required",
                "requires_auth": True,
                "message": "Authentication is required via VNC",
                "emulator_id": emulator_id,
            }, 401

        return {"books": books}, 200

    def get(self):
        """Handle GET request for books list"""
        return self._get_books()

    def post(self):
        """Handle POST request for books list"""
        return self._get_books()


class ScreenshotResource(Resource):
    # Only use the automator_healthy decorator without the response handler for direct image responses
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """Get current page screenshot and return a URL to access it or display it directly.
        If xml=1 is provided, also returns the XML page source.
        If text=1 is provided, OCRs the image and returns the text.
        If base64=1 is provided, returns the image encoded as base64 instead of a URL."""
        failed = None
        # Check if save parameter is provided
        save = request.args.get("save", "0") in ("1", "true")
        # Check if xml parameter is provided
        include_xml = request.args.get("xml", "0") in ("1", "true")
        # Check if OCR is requested via 'text' or 'ocr' parameter
        ocr_param = request.args.get("ocr", "0")
        text_param = request.args.get("text", "0")
        is_ocr = is_ocr_requested()
        logger.info(
            f"OCR debug - ocr param: {ocr_param}, text param: {text_param}, is_ocr_requested(): {is_ocr}"
        )

        perform_ocr = text_param in ("1", "true") or is_ocr

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()
        if perform_ocr and not use_base64:
            use_base64 = True

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email(default_email=server.current_email)

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Generate a unique filename with timestamp to avoid caching issues
        timestamp = int(time.time())
        filename = f"current_screen_{timestamp}.png"
        screenshot_path = os.path.join(automator.screenshots_dir, filename)

        # Take the screenshot
        try:
            # Check if we're in an auth-related state where we need to use secure screenshot
            current_state = automator.state_machine.current_state
            auth_states = [AppState.SIGN_IN, AppState.CAPTCHA, AppState.LIBRARY_SIGN_IN, AppState.UNKNOWN]

            # Check if the use_scrcpy parameter is explicitly set
            use_scrcpy = request.args.get("use_scrcpy", "0") in ("1", "true")

            if current_state == AppState.UNKNOWN and not use_scrcpy:
                # If state is unknown, update state first before deciding on screenshot method
                logger.info("State is UNKNOWN, updating state before choosing screenshot method")
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                logger.info(f"State after update: {current_state}")

            if current_state in auth_states or use_scrcpy:
                logger.info(
                    f"Using secure screenshot method for auth state: {current_state} or explicit scrcpy request"
                )
                # First attempt with secure screenshot method
                secure_path = automator.take_secure_screenshot(screenshot_path)
                if not secure_path:
                    # Try with standard method as fallback but catch FLAG_SECURE exceptions
                    logger.warning("Secure screenshot failed, falling back to standard method")
                    try:
                        automator.driver.save_screenshot(screenshot_path)
                    except Exception as inner_e:
                        # If this fails too, we'll log the error but continue with response processing
                        # so the error is properly reported to the client
                        logger.error(f"Standard screenshot also failed: {inner_e}")
                        failed = "Failed to take screenshot - FLAG_SECURE may be set"
            else:
                # Use standard screenshot for non-auth screens
                automator.driver.save_screenshot(screenshot_path)
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            failed = "Failed to take screenshot"

        # Get the image ID for URLs
        image_id = os.path.splitext(filename)[0]

        # Default is to return the image directly unless explicitly requested otherwise
        logger.info(
            f"save: {save}, include_xml: {include_xml}, use_base64: {use_base64}, perform_ocr: {perform_ocr}"
        )

        # If OCR is requested, we need the JSON response path
        if perform_ocr:
            logger.info("OCR requested, forcing JSON response path")
        elif not save and not include_xml and not use_base64:
            # For direct image responses, don't use the automator response handler
            # since it can't handle Flask Response objects
            if failed:
                return {"error": failed, "screenshot_url": None, "xml_url": None}, 200
            return serve_image(image_id, delete_after=False)

        # For JSON responses, we can wrap with the automator response handler
        @handle_automator_response(server)
        def get_screenshot_json():
            # Prepare the response data
            response_data = {}

            # Skip screenshot in LIBRARY state unless explicitly requested with save=1
            current_state = automator.state_machine.current_state
            if current_state == AppState.LIBRARY and not save:
                logger.info("Skipping screenshot in LIBRARY state since it's not needed")
                response_data["message"] = "Screenshot skipped in LIBRARY state"
            else:
                # Process the screenshot (either base64 encode, add URL, or perform OCR)
                screenshot_data = process_screenshot_response(image_id, use_base64, perform_ocr)
                response_data.update(screenshot_data)

            # If xml=1, get and save the page source XML
            if include_xml:
                try:
                    # Get page source from the driver
                    page_source = automator.driver.page_source

                    # Store the XML with the same base name as the screenshot
                    xml_filename = f"{image_id}.xml"
                    from server.logging_config import store_page_source

                    xml_path = store_page_source(page_source, image_id)
                    logger.info(f"Stored page source XML at {xml_path}")

                    # Add the XML URL to the response
                    # Assuming the XML will be served via a dedicated endpoint or file location
                    xml_url = f"/fixtures/dumps/{xml_filename}"
                    response_data["xml_url"] = xml_url
                except Exception as xml_error:
                    logger.error(f"Error getting page source XML: {xml_error}")
                    response_data["xml_error"] = str(xml_error)

            # OCR is now handled by process_screenshot_response

            # Return the response as a tuple that the decorator can handle
            if failed:
                response_data["error"] = failed
                return response_data, 500
            return response_data, 200

        # Call the nested function with automator response handling
        response, status_code = get_screenshot_json()
        if failed:
            response["error"] = failed
            return response, status_code
        return response, status_code


class NavigationResource(Resource):
    def __init__(self, default_action=None):
        self.default_action = default_action
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self, action=None):
        """Handle page navigation"""
        # Use provided action parameter if available
        if action is None:
            # Otherwise check if we have a default action from initialization
            if self.default_action:
                action = self.default_action
            else:
                # Fall back to action from request JSON
                data = request.get_json()
                action = data.get("action")

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()
        if use_base64:
            logger.info("Base64 parameter is provided, will return base64 encoded image")
        else:
            logger.info("Base64 parameter is not provided, will return URL to image")

        # Check if OCR is requested
        perform_ocr = is_ocr_requested()
        if perform_ocr:
            logger.info("OCR requested, will process image with OCR")
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True
                logger.info("Forcing base64 encoding for OCR processing")

        if not action:
            return {"error": "Navigation action is required"}, 400

        if action == "next_page":
            success = server.automator.reader_handler.turn_page_forward()
        elif action == "previous_page":
            success = server.automator.reader_handler.turn_page_backward()
        elif action == "preview_next_page":
            success, ocr_text = server.automator.reader_handler.preview_page_forward()
            # Add OCR text to response if available
            if success and ocr_text:
                response_data = {"success": True, "ocr_text": ocr_text}
                # Get reading progress but don't show placemark
                progress = server.automator.reader_handler.get_reading_progress(show_placemark=False)
                if progress:
                    response_data["progress"] = progress
                return response_data, 200
        elif action == "preview_previous_page":
            success, ocr_text = server.automator.reader_handler.preview_page_backward()
            # Add OCR text to response if available
            if success and ocr_text:
                response_data = {"success": True, "ocr_text": ocr_text}
                # Get reading progress but don't show placemark
                progress = server.automator.reader_handler.get_reading_progress(show_placemark=False)
                if progress:
                    response_data["progress"] = progress
                return response_data, 200
        else:
            return {"error": f"Invalid action: {action}"}, 400

        if success:
            # Get current page number and progress
            # Check if placemark is requested
            show_placemark = False
            placemark_param = request.args.get("placemark", "0")
            if placemark_param.lower() in ("1", "true", "yes"):
                show_placemark = True
                logger.info("Placemark mode enabled for navigation")

            # Also check in POST data
            if not show_placemark and request.is_json:
                data = request.get_json(silent=True) or {}
                placemark_param = data.get("placemark", "0")
                if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                    show_placemark = True
                    logger.info("Placemark mode enabled from POST data for navigation")

            progress = server.automator.reader_handler.get_reading_progress(show_placemark=show_placemark)

            # Save screenshot with unique ID
            screenshot_id = f"page_{int(time.time())}"
            time.sleep(0.5)
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
            server.automator.driver.save_screenshot(screenshot_path)

            response_data = {
                "success": True,
                "progress": progress,
            }

            # Process the screenshot (either base64 encode, add URL, or OCR)
            screenshot_data = process_screenshot_response(screenshot_id, use_base64, perform_ocr)
            response_data.update(screenshot_data)

            return response_data, 200

        return {"error": "Navigation failed"}, 500

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Handle navigation via GET requests, using query parameters or default_action"""
        # Check if action is provided in query parameters
        action = request.args.get("action")

        # If no action in query params, use the default action configured for this endpoint
        if not action:
            if not self.default_action:
                return {"error": "Navigation action is required"}, 400
            action = self.default_action

        # Since we're using query params and moving them to POST,
        # we don't need to do anything special here - the POST method
        # already checks for the presence of base64 and ocr in both
        # query params and request body.

        # Pass the action to the post method to handle navigation
        return self.post(action)


class BookOpenResource(Resource):
    def _open_book(self, book_title):
        """Open a specific book - shared implementation for GET and POST."""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email(default_email=server.current_email)

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Set this as the current email for backward compatibility
        server.current_email = sindarin_email

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Check if OCR is requested
        perform_ocr = is_ocr_requested()
        if perform_ocr:
            logger.info("OCR requested for open-book, will process image with OCR")
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True
                logger.info("Forcing base64 encoding for OCR processing")

        # Check if placemark is requested - default is FALSE which means DO NOT show placemark
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for this request")
        else:
            logger.info("Placemark mode disabled - will avoid tapping to prevent placemark display")

        logger.info(f"Opening book: {book_title}")

        if not book_title:
            return {"error": "Book title is required in the request"}, 400

        # Common function to capture progress and screenshot
        def capture_book_state(already_open=False):
            # Get reading progress
            progress = automator.reader_handler.get_reading_progress(show_placemark=show_placemark)
            logger.info(f"Progress: {progress}")

            # Save screenshot with unique ID
            screenshot_id = f"page_{int(time.time())}"
            screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
            time.sleep(0.5)
            automator.driver.save_screenshot(screenshot_path)

            # Create response data with progress info
            response_data = {"success": True, "progress": progress}

            # Add flag if book was already open
            if already_open:
                response_data["already_open"] = True

            # Process the screenshot (either base64 encode, add URL, or OCR)
            screenshot_data = process_screenshot_response(screenshot_id, use_base64, perform_ocr)
            response_data.update(screenshot_data)

            return response_data, 200

        # Reload the current state to be sure
        automator.state_machine.update_current_state()
        current_state = automator.state_machine.current_state

        # IMPORTANT: For new app installation or first run, current_book may be None
        # even though we're already in reading state - we need to check that too

        # Get current book for this email
        current_book = server.current_books.get(sindarin_email)

        # If we're already in READING state, we should NOT close the book - get the title!
        if current_state == AppState.READING:
            # First, check if we have current_book set
            if current_book:
                # Compare with the requested book
                normalized_request_title = "".join(
                    c for c in book_title if c.isalnum() or c.isspace()
                ).lower()
                normalized_current_title = "".join(
                    c for c in current_book if c.isalnum() or c.isspace()
                ).lower()

                logger.info(
                    f"Title comparison: requested='{normalized_request_title}', current='{normalized_current_title}'"
                )

                # Try exact match first
                if normalized_request_title == normalized_current_title:
                    logger.info(f"Already reading book (exact match): {book_title}, returning current state")
                    return capture_book_state(already_open=True)

                # For longer titles, try to match the first 30+ characters or check if one title contains the other
                if (
                    len(normalized_request_title) > 30
                    and len(normalized_current_title) > 30
                    and (
                        normalized_request_title[:30] == normalized_current_title[:30]
                        or normalized_request_title in normalized_current_title
                        or normalized_current_title in normalized_request_title
                    )
                ):
                    logger.info(
                        f"Already reading book (partial match): {book_title}, returning current state"
                    )
                    return capture_book_state(already_open=True)

                # If we're in reading state but current_book doesn't match, try to get book title from UI
                logger.info(
                    f"In reading state but current book '{current_book}' doesn't match requested '{book_title}'"
                )
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.reader_handler.get_book_title()
                    if current_title_from_ui:
                        logger.info(f"Got book title from UI: '{current_title_from_ui}'")

                        # Compare with the requested book
                        normalized_ui_title = "".join(
                            c for c in current_title_from_ui if c.isalnum() or c.isspace()
                        ).lower()

                        # Check exact match with UI title
                        if normalized_request_title == normalized_ui_title:
                            logger.info(
                                f"Already reading book (UI title exact match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)

                        # Check partial match with UI title
                        if (
                            len(normalized_request_title) > 30
                            and len(normalized_ui_title) > 30
                            and (
                                normalized_request_title[:30] == normalized_ui_title[:30]
                                or normalized_request_title in normalized_ui_title
                                or normalized_ui_title in normalized_request_title
                            )
                        ):
                            logger.info(
                                f"Already reading book (UI title partial match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)
                except Exception as e:
                    logger.warning(f"Failed to get book title from UI: {e}")

                logger.info(
                    f"No match found for book: {book_title} ({normalized_request_title}) != {current_book}, transitioning to library"
                )
            else:
                # We're in reading state but don't have current_book set - try to get it from UI
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.reader_handler.get_book_title()
                    if current_title_from_ui:
                        logger.info(
                            f"In reading state with no tracked book. Got book title from UI: '{current_title_from_ui}'"
                        )

                        # Compare with the requested book
                        normalized_request_title = "".join(
                            c for c in book_title if c.isalnum() or c.isspace()
                        ).lower()
                        normalized_ui_title = "".join(
                            c for c in current_title_from_ui if c.isalnum() or c.isspace()
                        ).lower()

                        # Check exact match with UI title
                        if normalized_request_title == normalized_ui_title:
                            logger.info(
                                f"Already reading book (UI title exact match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)

                        # Check partial match with UI title
                        if (
                            len(normalized_request_title) > 30
                            and len(normalized_ui_title) > 30
                            and (
                                normalized_request_title[:30] == normalized_ui_title[:30]
                                or normalized_request_title in normalized_ui_title
                                or normalized_ui_title in normalized_request_title
                            )
                        ):
                            logger.info(
                                f"Already reading book (UI title partial match): {book_title}, returning current state"
                            )
                            # Update server's current book tracking
                            server.set_current_book(current_title_from_ui, sindarin_email)
                            return capture_book_state(already_open=True)
                except Exception as e:
                    logger.warning(f"Failed to get book title from UI: {e}")
        # Not in reading state but have tracked book - clear it
        elif current_book:
            logger.info(
                f"Not in reading state: {current_state}, but have book '{current_book}' tracked - clearing it"
            )
            server.clear_current_book(sindarin_email)

        logger.info(f"Reloaded current state: {current_state}")

        # If we get here, we need to go to library and open the book
        logger.info(
            f"Not already reading requested book: {book_title} != {current_book}, transitioning from {current_state} to library"
        )
        # If we're not already reading the requested book, transition to library and open it
        if automator.state_machine.transition_to_library(server=server):
            success = automator.reader_handler.open_book(book_title, show_placemark=show_placemark)
            logger.info(f"Book opened: {success}")

            if success:
                # Set the current book in the server state
                server.set_current_book(book_title, sindarin_email)
                return capture_book_state()

        return {"error": "Failed to open book"}, 500

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def post(self):
        """Open a specific book via POST request."""
        data = request.get_json()
        book_title = data.get("title")

        # Handle placemark parameter from POST data
        placemark_param = data.get("placemark", "0")
        if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
            request.args = request.args.copy()
            request.args["placemark"] = "1"

        # Call the implementation without the handle_automator_response decorator
        # since it might return a Response object that can't be JSON serialized
        result = self._open_book(book_title)

        # Directly return the result, as Flask can handle Response objects
        return result

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """Open a specific book via GET request."""
        book_title = request.args.get("title")

        # Call the implementation without the handle_automator_response decorator
        # since it might return a Response object that can't be JSON serialized
        result = self._open_book(book_title)

        # Directly return the result, as Flask can handle Response objects
        return result


class StyleResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Update reading style settings"""
        data = request.get_json()
        settings = data.get("settings", {})
        dark_mode = data.get("dark-mode")

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        logger.info(f"Updating style settings: {settings}, dark mode: {dark_mode}")

        # Update state machine's current state
        server.automator.state_machine.update_current_state()

        # Check if we're in reading state
        current_state = server.automator.state_machine.current_state
        if current_state != AppState.READING:
            return {
                "error": (
                    f"Must be reading a book to change style settings, current state: {current_state.name}"
                ),
            }, 400

        if dark_mode is not None:
            success = server.automator.reader_handler.set_dark_mode(dark_mode)
        else:
            # For now just return success since we haven't implemented other style settings
            success = True
            logger.warning("Other style settings not yet implemented")

        if success:
            # Save screenshot with unique ID
            screenshot_id = f"style_update_{int(time.time())}"
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
            server.automator.driver.save_screenshot(screenshot_path)

            # Get current page number and progress
            # Check if placemark is requested
            show_placemark = False
            placemark_param = request.args.get("placemark", "0")
            if placemark_param.lower() in ("1", "true", "yes"):
                show_placemark = True
                logger.info("Placemark mode enabled for style change")

            # Also check in POST data
            if not show_placemark and request.is_json:
                data = request.get_json(silent=True) or {}
                placemark_param = data.get("placemark", "0")
                if placemark_param and str(placemark_param).lower() in ("1", "true", "yes"):
                    show_placemark = True
                    logger.info("Placemark mode enabled from POST data for style change")

            progress = server.automator.reader_handler.get_reading_progress(show_placemark=show_placemark)

            response_data = {
                "success": True,
                "progress": progress,
            }

            # Process the screenshot (either base64 encode or add URL)
            screenshot_data = process_screenshot_response(screenshot_id, use_base64)
            response_data.update(screenshot_data)

            return response_data, 200

        return {"error": "Failed to update settings"}, 500


class TwoFactorResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Submit 2FA code"""
        data = request.get_json()
        code = data.get("code")

        logger.info(f"Submitting 2FA code: {code}")

        if not code:
            return {"error": "2FA code required"}, 400

        success = server.automator.auth_handler.handle_2fa(code)
        if success:
            return {"success": True}, 200
        return {"error": "Invalid 2FA code"}, 500


class AuthResource(Resource):
    @ensure_user_profile_loaded
    @handle_automator_response(server)
    def post(self):
        """Set up a profile for manual authentication via VNC"""
        data = request.get_json() or {}

        # Get sindarin_email from request - this is the profile name we'll use
        sindarin_email = None
        if "sindarin_email" in request.args:
            sindarin_email = request.args.get("sindarin_email")
        elif request.is_json and "sindarin_email" in data:
            sindarin_email = data.get("sindarin_email")
        elif "sindarin_email" in request.form:
            sindarin_email = request.form.get("sindarin_email")

        # Sindarin email is required for profile identification
        if not sindarin_email:
            logger.error("No sindarin_email provided for profile identification")
            return {"error": "sindarin_email is required for profile identification"}, 400
        else:
            logger.info(f"Using sindarin_email for profile: {sindarin_email}")

        # Check if recreate parameter is provided
        recreate = False
        if request.is_json:
            recreate = data.get("recreate", False)
        else:
            recreate = request.args.get("recreate", "0") in ("1", "true")

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Log authentication attempt details
        logger.info(f"Setting up profile: {sindarin_email} for manual VNC authentication")

        # If recreate is requested, just clean up the automator but don't force a new emulator
        if recreate:
            logger.info(f"Recreate requested for {sindarin_email}, cleaning up existing automator")
            # First check if we have an automator for this email specifically
            if sindarin_email in server.automators:
                logger.info(f"Cleaning up existing automator for {sindarin_email}")
                automator = server.automators[sindarin_email]
                if automator:
                    automator.cleanup()
                    server.automators[sindarin_email] = None
            # Also check the legacy automator field
            elif server.automator:
                logger.info("Cleaning up existing automator")
                server.automator.cleanup()
                server.automator = None

        # Initialize variables for Python launcher integration
        emulator_id = None
        display_num = None
        using_python_launcher = False

        # Check if we can use the Python launcher
        if hasattr(server, "automators") and sindarin_email in server.automators:
            automator = server.automators.get(sindarin_email)
            if (
                automator
                and hasattr(automator, "emulator_manager")
                and hasattr(automator.emulator_manager, "use_python_launcher")
            ):
                using_python_launcher = automator.emulator_manager.use_python_launcher

                if using_python_launcher:
                    logger.info(f"Using Python launcher for {sindarin_email}")
                    # Check if we have a running emulator for this email
                    if hasattr(automator.emulator_manager, "emulator_launcher"):
                        emulator_id, display_num = (
                            automator.emulator_manager.emulator_launcher.get_running_emulator(sindarin_email)
                        )
                        if emulator_id:
                            logger.info(
                                f"Found running emulator for {sindarin_email}: {emulator_id} on display :{display_num}"
                            )
                        else:
                            logger.info(f"No running emulator found for {sindarin_email}, will launch one")

        # Switch to the profile for this email or create a new one
        # We don't force a new emulator - let the profile manager decide if one is needed
        # We use sindarin_email here for profile identification
        success, message = server.switch_profile(sindarin_email, force_new_emulator=False)
        if not success:
            logger.error(f"Failed to switch to profile for {sindarin_email}: {message}")
            return {"error": f"Failed to switch to profile: {message}"}, 500

        # For M1/M2/M4 Macs where the emulator might not start,
        # we'll still continue with the profile tracking

        # Now that we've switched profiles, initialize the automator
        if not server.automators.get(sindarin_email):
            server.initialize_automator()
            if not server.automator.initialize_driver():
                return {"error": "Failed to initialize driver"}, 500

        # Re-check for Python launcher after initialization
        automator = server.automators.get(sindarin_email)
        if (
            automator
            and hasattr(automator, "emulator_manager")
            and hasattr(automator.emulator_manager, "use_python_launcher")
        ):
            using_python_launcher = automator.emulator_manager.use_python_launcher

            # If using Python launcher and no emulator is running yet, launch one
            if (
                using_python_launcher
                and not emulator_id
                and hasattr(automator.emulator_manager, "emulator_launcher")
            ):
                avd_name = automator.avd_name if hasattr(automator, "avd_name") else None
                if avd_name:
                    logger.info(f"Launching emulator for {sindarin_email} with AVD {avd_name}")
                    success, emulator_id, display_num = (
                        automator.emulator_manager.emulator_launcher.launch_emulator(avd_name, sindarin_email)
                    )
                    if success:
                        logger.info(f"Successfully launched emulator {emulator_id} on display :{display_num}")
                    else:
                        logger.error(f"Failed to launch emulator for {sindarin_email}")

        # Use the prepare_for_authentication method - always using VNC
        # Make sure the driver has access to the automator for state transitions
        # This fixes the "Could not access automator from driver session" error
        if automator.driver and not hasattr(automator.driver, "automator"):
            logger.info("Setting automator on driver object for state transitions")
            automator.driver.automator = automator

        # This is the critical method that ensures we navigate to AUTH or LIBRARY
        logger.info("Calling prepare_for_authentication to navigate to sign-in screen or library")
        auth_status = automator.state_machine.auth_handler.prepare_for_authentication()

        logger.info(f"Authentication preparation status: {auth_status}")

        # Check for fatal errors that would prevent continuing
        if auth_status.get("fatal_error", False):
            error_msg = auth_status.get("error", "Unknown fatal error in authentication preparation")
            logger.error(f"Fatal error in authentication preparation: {error_msg}")
            return {"success": False, "error": error_msg}, 500

        # Handle already authenticated cases (LIBRARY or HOME)
        if auth_status.get("already_authenticated", False):
            # If we're in HOME state, try to switch to LIBRARY
            if auth_status.get("state") == "HOME":
                logger.info("Already logged in but in HOME state, switching to LIBRARY")

                # Try to click the LIBRARY tab
                try:
                    library_tab = automator.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"
                    )
                    library_tab.click()
                    logger.info("Clicked on LIBRARY tab")
                    time.sleep(1)  # Wait for tab transition

                    # Update state after clicking
                    automator.state_machine.update_current_state()
                    updated_state = automator.state_machine.current_state

                    if updated_state == AppState.LIBRARY:
                        logger.info("Successfully switched to LIBRARY state")
                        return {
                            "success": True,
                            "message": "Switched to library view",
                            "authorized_kindle_account": True,
                        }, 200
                except Exception as e:
                    logger.error(f"Error clicking on LIBRARY tab: {e}")
                    # Continue with normal authentication process
            else:
                # We're already in LIBRARY state
                return {
                    "success": True,
                    "message": "Already authenticated",
                    "authorized_kindle_account": True,
                }, 200

        # Handle LIBRARY_SIGN_IN state - check if we need to click on the sign-in button
        if auth_status.get("state") == "LIBRARY_SIGN_IN":
            logger.info("Found empty library with sign-in button, clicking it to proceed with authentication")
            try:
                # Use the library handler to click the sign-in button
                result = automator.state_machine.library_handler.handle_library_sign_in()
                if result:
                    logger.info("Successfully clicked sign-in button, now on authentication screen")

                    # Update the state after clicking
                    automator.state_machine.update_current_state()
                    current_state = automator.state_machine.current_state
                    state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

                    logger.info(f"Current state after clicking sign-in button: {state_name}")

                    # Update the auth status with the new state
                    auth_status["state"] = state_name
                    auth_status["requires_manual_login"] = True
                else:
                    logger.error("Failed to click sign-in button")
            except Exception as e:
                logger.error(f"Error handling LIBRARY_SIGN_IN state: {e}")
                # Continue with normal authentication process

        # Always use manual login via VNC (no automation of Amazon credentials)
        # Before getting VNC URL, ensure that VNC server is running

        # Ensure VNC is running for this display if using Python launcher
        if using_python_launcher and display_num is not None:
            try:
                logger.info(f"Ensuring VNC server is running for display {display_num}")
                if hasattr(automator.emulator_manager, "emulator_launcher"):
                    # Call _ensure_vnc_running to start Xvfb and x11vnc if needed
                    automator.emulator_manager.emulator_launcher._ensure_vnc_running(display_num)
                    logger.info(f"VNC server check/start completed for display {display_num}")
            except Exception as e:
                logger.error(f"Error starting VNC server: {e}")

        # Get the formatted VNC URL with the profile email and emulator ID
        # emulator_id is already available from above code
        formatted_vnc_url = get_formatted_vnc_url(sindarin_email, emulator_id=emulator_id)

        # Prepare manual auth response with details from auth_status
        current_state = automator.state_machine.current_state
        state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

        # Start with base response information
        response_data = {
            "success": True,
            "manual_login_required": auth_status.get("requires_manual_login", True),
            "message": auth_status.get("message", "Ready for manual authentication via VNC"),
            "state": auth_status.get("state", state_name),
            "vnc_url": formatted_vnc_url,  # Include the VNC URL in the response
            "authorized_kindle_account": auth_status.get(
                "already_authenticated", False
            ),  # Indicates if user is signed in
        }

        # Pass through any additional info from auth_status
        if "error" in auth_status:
            response_data["error_info"] = auth_status["error"]

        # If we have custom messages, include them
        if "message" in auth_status:
            response_data["message"] = auth_status["message"]

        # Add Python launcher information to the response if available
        if using_python_launcher:
            response_data["using_python_launcher"] = True
            if emulator_id:
                response_data["emulator_id"] = emulator_id
            if display_num:
                response_data["display_num"] = display_num

        # Log the final response in detail
        logger.info(f"Returning auth response: {response_data}")

        return response_data, 200


class FixturesResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Create fixtures for major views"""
        try:
            fixtures_handler = TestFixturesHandler(server.automator.driver)
            if fixtures_handler.create_fixtures():
                return {"status": "success", "message": "Created fixtures for all major views"}, 200
            return {"error": "Failed to create fixtures"}, 500

        except Exception as e:
            logger.error(f"Error creating fixtures: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


# Helper function to get image path
def get_image_path(image_id):
    """Get full path for an image file."""
    # Build path to image using project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Ensure .png extension
    if not image_id.endswith(".png"):
        image_id = f"{image_id}.png"

    return os.path.join(project_root, "screenshots", image_id)


# Helper function to serve an image with option to delete after serving
def serve_image(image_id, delete_after=True):
    """Serve an image by ID with option to delete after serving.

    This function properly handles the Flask response object to work with Flask-RESTful.
    """
    try:
        image_path = get_image_path(image_id)
        logger.info(f"Attempting to serve image from: {image_path}")

        if not os.path.exists(image_path):
            logger.error(f"Image not found at path: {image_path}")
            return {"error": "Image not found"}, 404

        # Create a response that bypasses Flask-RESTful's serialization
        logger.info(f"Serving image from: {image_path}")
        response = make_response(send_file(image_path, mimetype="image/png"))

        # Delete the file after sending if requested
        # We need to set up a callback to delete the file after the response is sent
        if delete_after:

            @response.call_on_close
            def on_close():
                try:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                        logger.info(f"Deleted image: {image_path}")
                except Exception as e:
                    logger.error(f"Failed to delete image {image_path}: {e}")

        # Return the response object directly
        return response

    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return {"error": str(e)}, 500


# Helper function to check if base64 is requested
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


# Helper function to check if OCR is requested
def is_ocr_requested():
    """Check if OCR is requested in query parameters or JSON body.

    Returns:
        Boolean indicating whether OCR was requested
    """
    # Check URL query parameters first - match exactly how other query params are checked
    ocr_param = request.args.get("ocr", "0")
    perform_ocr = ocr_param in ("1", "true")

    logger.debug(f"is_ocr_requested check - query param 'ocr': {ocr_param}, result: {perform_ocr}")

    # If not in URL parameters, check JSON body
    if not perform_ocr and request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            ocr_param = json_data.get("ocr", False)
            if isinstance(ocr_param, bool):
                perform_ocr = ocr_param
            elif isinstance(ocr_param, str):
                perform_ocr = ocr_param == "1" or ocr_param.lower() == "true"
            elif isinstance(ocr_param, int):
                perform_ocr = ocr_param == 1
            logger.debug(f"is_ocr_requested check - JSON param 'ocr': {ocr_param}, result: {perform_ocr}")
        except Exception as e:
            logger.warning(f"Error parsing JSON for OCR parameter: {e}")

    return perform_ocr


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


# Helper function to handle image encoding for API responses
def process_screenshot_response(screenshot_id, use_base64=False, perform_ocr=False):
    """Process screenshot for API response - either adding URL, base64-encoded image, or OCR text.

    Args:
        screenshot_id: The ID of the screenshot
        use_base64: Whether to use base64 encoding
        perform_ocr: Whether to perform OCR on the image

    Returns:
        Dictionary with screenshot information (URL, base64, or OCR text)
    """
    result = {}
    screenshot_path = get_image_path(screenshot_id)
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


class ImageResource(Resource):
    def get(self, image_id):
        """Get an image by ID and delete it after serving."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)


class ProfilesResource(Resource):
    def get(self):
        """List all available profiles"""
        profiles = server.profile_manager.list_profiles()
        current = server.profile_manager.get_current_profile()

        # Get additional info about running emulators
        running_emulators = server.profile_manager.device_discovery.map_running_emulators()

        # Get VNC and emulator information for each profile
        vnc_instances = {}
        for profile in profiles:
            email = profile.get("email")
            if email and email in server.automators:
                # Get VNC info using emulator_launcher
                automator = server.automators.get(email)
                if (
                    automator
                    and hasattr(automator, "emulator_manager")
                    and hasattr(automator.emulator_manager, "emulator_launcher")
                ):
                    emulator_id, display_num = (
                        automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                    )
                    if display_num:
                        vnc_instances[email] = {
                            "instance_id": display_num,  # Use display number as instance ID
                            "display": display_num,
                            "vnc_port": 5900 + display_num,
                            "emulator_id": emulator_id,
                        }

        # Add information about which automators are active
        active_automators = {}
        for email, automator in server.automators.items():
            if automator and hasattr(automator, "driver") and automator.driver:
                is_running = True
                device_id = automator.device_id if hasattr(automator, "device_id") else None
                current_book = server.current_books.get(email) if email in server.current_books else None

                active_automators[email] = {
                    "device_id": device_id,
                    "is_running": is_running,
                    "current_book": current_book,
                }

                # Add VNC instance info if available
                if email in vnc_instances:
                    active_automators[email]["vnc_instance"] = vnc_instances[email]

        # Include a specific profile if requested
        specific_email = request.args.get("email")
        if specific_email:
            # Find the specific profile
            specific_profile = None
            for profile in profiles:
                if profile.get("email") == specific_email:
                    specific_profile = profile
                    break

            # Include VNC info for this specific profile
            vnc_info = vnc_instances.get(specific_email, {})
            automator_info = active_automators.get(specific_email, {})

            if specific_profile:
                return {
                    "profile": specific_profile,
                    "vnc_instance": vnc_info,
                    "automator": automator_info,
                    "is_current": current and current.get("email") == specific_email,
                }, 200
            else:
                return {"error": f"Profile {specific_email} not found"}, 404

        return {
            "profiles": profiles,
            "current": current,
            "running_emulators": running_emulators,
            "active_automators": active_automators,
            "vnc_instances": vnc_instances,
        }, 200

    def post(self):
        """Create, delete or manage a profile"""
        data = request.get_json()
        action = data.get("action")
        email = data.get("email")

        if action == "reset_styles":
            # Special case for resetting style preferences without needing an email
            if server.profile_manager.current_profile:
                if server.profile_manager.update_style_preference(False):
                    return {"success": True, "message": "Style preferences reset successfully"}, 200
                else:
                    return {"success": False, "message": "Failed to reset style preferences"}, 500
            else:
                return {"success": False, "message": "No current profile found"}, 400

        elif action == "list_active":
            # List all active emulators with their details
            running_emulators = server.profile_manager.device_discovery.map_running_emulators()
            active_automators = {}

            for email, automator in server.automators.items():
                if automator and hasattr(automator, "driver") and automator.driver:
                    device_id = automator.device_id if hasattr(automator, "device_id") else None
                    current_book = server.current_books.get(email) if email in server.current_books else None

                    active_automators[email] = {"device_id": device_id, "current_book": current_book}

            return {"running_emulators": running_emulators, "active_automators": active_automators}, 200

        # For all other actions, email is required
        if not email:
            return {"error": "Email is required for this action"}, 400

        if action == "create":
            success, message = server.profile_manager.create_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        elif action == "delete":
            success, message = server.profile_manager.delete_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        elif action == "switch":
            success, message = server.switch_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        elif action == "stop_emulator":
            # Find the automator for this email
            automator = server.automators.get(email)
            if (
                not automator
                or not hasattr(automator, "emulator_manager")
                or not hasattr(automator.emulator_manager, "emulator_launcher")
            ):
                return {"success": False, "message": f"No valid automator found for {email}"}, 404

            # Check if there's a running emulator for this email
            emulator_id, display_num = automator.emulator_manager.emulator_launcher.get_running_emulator(
                email
            )
            if not emulator_id:
                return {"success": False, "message": f"No running emulator found for {email}"}, 404

            # Stop the emulator using the launcher
            logger.info(f"Stopping emulator for {email} using emulator_launcher")
            success = automator.emulator_manager.emulator_launcher.stop_emulator(email)

            # Clean up the automator if it exists
            if email in server.automators and server.automators[email]:
                logger.info(f"Cleaning up automator for {email}")
                server.automators[email].cleanup()
                server.automators[email] = None

            # Clear current book
            server.clear_current_book(email)

            if success:
                return {"success": True, "message": f"Stopped emulator for {email}"}, 200
            else:
                return {"success": False, "message": f"Failed to stop emulator for {email}"}, 500

        else:
            return {"error": f"Invalid action: {action}"}, 400


class TextResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def _extract_text(self):
        """Shared implementation for extracting text from the current reading page."""
        try:
            # Make sure we're in the READING state
            server.automator.state_machine.update_current_state()
            current_state = server.automator.state_machine.current_state

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
                        slideover = server.automator.driver.find_element(strategy, locator)
                        if slideover.is_displayed():
                            about_book_visible = True
                            logger.info("Found 'About this book' slideover that must be dismissed before OCR")
                            break
                    except selenium_exceptions.NoSuchElementException:
                        continue

                if about_book_visible:
                    # Try multiple dismissal methods

                    # Method 1: Try tapping at the very top of the screen
                    window_size = server.automator.driver.get_window_size()
                    center_x = window_size["width"] // 2
                    top_y = int(window_size["height"] * 0.05)  # 5% from top
                    server.automator.driver.tap([(center_x, top_y)])
                    logger.info("Tapped at the very top of the screen to dismiss 'About this book' slideover")
                    time.sleep(1)

                    # Verify if it worked
                    still_visible = False
                    for strategy, locator in ABOUT_BOOK_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = server.automator.driver.find_element(strategy, locator)
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
                        server.automator.driver.swipe(center_x, start_y, center_x, end_y, 300)
                        logger.info("Swiped down to dismiss 'About this book' slideover")
                        time.sleep(1)

                        # Method 3: Try clicking the pill if it exists
                        try:
                            pill = server.automator.driver.find_element(*BOTTOM_SHEET_IDENTIFIERS[1])
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
                            slideover = server.automator.driver.find_element(strategy, locator)
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
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
            server.automator.driver.save_screenshot(screenshot_path)

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

            progress = server.automator.reader_handler.get_reading_progress(show_placemark=show_placemark)

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
    @handle_automator_response(server)
    def get(self):
        """Get OCR text of the current reading page without turning the page."""
        return self._extract_text()

    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """POST endpoint for OCR text extraction (identical to GET but allows for future parameters)."""
        return self._extract_text()


# Add resources to API
api.add_resource(InitializeResource, "/initialize")
api.add_resource(StateResource, "/state")
api.add_resource(CaptchaResource, "/captcha")
api.add_resource(BooksResource, "/books")
api.add_resource(ScreenshotResource, "/screenshot")
# General navigation endpoint that requires a JSON body with action
api.add_resource(NavigationResource, "/navigate")
# Specialized navigation endpoints for direct GET requests
api.add_resource(
    NavigationResource,
    "/navigate-next",
    endpoint="navigate_next",
    resource_class_kwargs={"default_action": "next_page"},
)
api.add_resource(
    NavigationResource,
    "/navigate-previous",
    endpoint="navigate_previous",
    resource_class_kwargs={"default_action": "previous_page"},
)

# Preview endpoints for navigation with OCR and return to original page
api.add_resource(
    NavigationResource,
    "/preview-next",
    endpoint="preview_next",
    resource_class_kwargs={"default_action": "preview_next_page"},
)
api.add_resource(
    NavigationResource,
    "/preview-previous",
    endpoint="preview_previous",
    resource_class_kwargs={"default_action": "preview_previous_page"},
)

api.add_resource(BookOpenResource, "/open-book")
api.add_resource(StyleResource, "/style")
api.add_resource(TwoFactorResource, "/2fa")
api.add_resource(AuthResource, "/auth")
api.add_resource(FixturesResource, "/fixtures")
api.add_resource(ImageResource, "/image/<string:image_id>")
api.add_resource(ProfilesResource, "/profiles")
api.add_resource(TextResource, "/text")


# Add new route to handle VNC connections
@app.route("/vnc")
def vnc_redirect():
    """Redirect to VNC connection with appropriate profile parameters.
    This ensures VNC only accesses the emulator tied to the specified profile email."""
    sindarin_email = get_sindarin_email(default_email=server.current_email)

    # If no email is provided and server doesn't have a current email, return error
    if not sindarin_email:
        return {"error": "No sindarin_email provided to identify which profile to access"}, 400

    logger.info(f"VNC redirect requested for email: {sindarin_email}")

    # Find the automator for the specified email
    automator = None
    if hasattr(server, "automators") and sindarin_email in server.automators:
        automator = server.automators.get(sindarin_email)
    else:
        logger.error(f"No automator found for profile {sindarin_email}")
        return {"error": f"No automator found for profile {sindarin_email}"}, 404

    # Check if emulator_manager exists and add it if missing
    if not hasattr(automator, "emulator_manager"):
        logger.warning(f"Automator for {sindarin_email} missing emulator_manager, adding it now")
        try:
            # Add emulator_manager from profile_manager
            automator.emulator_manager = server.profile_manager.emulator_manager
            logger.info(f"Successfully added emulator_manager to automator for {sindarin_email}")
        except Exception as e:
            logger.error(f"Failed to add emulator_manager to automator for {sindarin_email}: {e}")
            return {"error": f"Failed to initialize emulator_launcher capability: {e}"}, 500

    # Check if emulator_launcher exists
    if not hasattr(automator.emulator_manager, "emulator_launcher"):
        logger.error(f"Automator for {sindarin_email} does not have emulator_launcher capability")
        return {"error": f"Automator for {sindarin_email} does not have emulator_launcher capability"}, 500

    # Get the running emulator from the emulator launcher
    emulator_id, display_num = automator.emulator_manager.emulator_launcher.get_running_emulator(
        sindarin_email
    )

    # If no emulator is running, return an error
    if not emulator_id or not display_num:
        logger.error(f"No running emulator found for profile {sindarin_email}")
        return {"error": f"No running emulator found for profile {sindarin_email}"}, 404

    logger.info(f"Found running emulator for {sindarin_email}: {emulator_id} on display :{display_num}")

    # Construct the VNC URL
    vnc_url = VNC_BASE_URL

    # Construct the query string with sindarin_email and other required params
    query_params = [
        f"sindarin_email={sindarin_email}",
    ]

    # Add any other query parameters from the original request
    for key, value in request.args.items():
        if key not in [
            "sindarin_email",
            "view",
            "mobile",
        ]:  # Skip ones we've already handled
            query_params.append(f"{key}={value}")

    # Construct the final URL with all parameters
    if query_params:
        if "?" in vnc_url:
            vnc_url = f"{vnc_url}&{'&'.join(query_params)}"
        else:
            vnc_url = f"{vnc_url}?{'&'.join(query_params)}"

    logger.info(f"Redirecting {sindarin_email} to VNC instance: {vnc_url}")

    # Restart the VNC server with proper clipping on Linux
    if platform.system() != "Darwin":
        try:
            # Pass the display number to the restart script
            restart_cmd = ["/usr/local/bin/restart-vnc-for-profile.sh", sindarin_email, str(display_num)]

            logger.info(f"Restarting VNC server for profile {sindarin_email} on display :{display_num}...")

            # Run the command with a short timeout and capture output
            result = subprocess.run(restart_cmd, timeout=10, check=False, capture_output=True, text=True)
            logger.info(f"VNC server restart initiated for profile {sindarin_email}")

            # Log the output for debugging
            if result.stdout:
                logger.info(f"VNC restart stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"VNC restart stderr: {result.stderr}")

            # If the restart had an error code, log it
            if result.returncode != 0:
                logger.warning(f"VNC restart returned non-zero exit code: {result.returncode}")
        except Exception as e:
            logger.warning(f"Failed to restart VNC server for profile {sindarin_email}: {e}")

    # Add the emulator ID and port to the URL if available
    if emulator_id:
        # Extract the port number from emulator ID (e.g., "emulator-5554" -> 5554)
        try:
            emulator_port = int(emulator_id.split("-")[1])
            if "?" in vnc_url:
                vnc_url = f"{vnc_url}&emulator_id={emulator_id}&emulator_port={emulator_port}"
            else:
                vnc_url = f"{vnc_url}?emulator_id={emulator_id}&emulator_port={emulator_port}"
            logger.info(f"Added emulator ID '{emulator_id}' and port '{emulator_port}' to VNC URL")
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract port from emulator ID '{emulator_id}': {e}")

    # Redirect to the VNC URL
    return redirect(vnc_url)


def cleanup_resources():
    """Clean up resources before exiting"""
    logger.info("Cleaning up resources before shutdown...")

    # We intentionally keep all emulators running during server shutdown
    # This allows for faster reconnection when the server is restarted,
    # and supports the multi-emulator approach
    logger.info("Preserving all emulators during shutdown for faster reconnection")

    # Cleanup automator instances but don't stop emulators
    for email, automator in server.automators.items():
        if automator:
            try:
                # Just clean up the automator, not the emulator
                logger.info(f"Cleaning up automator for {email} (preserving emulator)")
                # Don't call automator.cleanup() as it would stop the emulator
                # Instead, just set it to None to release resources
                automator.driver = None
            except Exception as e:
                logger.error(f"Error cleaning up automator for {email}: {e}")

    # Clear all automators
    server.automators.clear()

    # Kill Appium server only
    try:
        logger.info("Stopping Appium server")
        server.kill_existing_process("appium")
    except Exception as e:
        logger.error(f"Error stopping Appium during shutdown: {e}")

    # We don't kill the ADB server either, to maintain connection with emulators
    logger.info("Cleanup complete, server shutting down (all emulators preserved)")


def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown"""
    signal_name = (
        "SIGINT" if sig == signal.SIGINT else "SIGTERM" if sig == signal.SIGTERM else f"Signal {sig}"
    )
    logger.info(f"Received {signal_name}, initiating graceful shutdown...")
    cleanup_resources()
    # Exit with success code
    os._exit(0)


def run_server():
    """Run the Flask server"""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("Registered signal handlers for graceful shutdown")

    app.run(host="0.0.0.0", port=4098)


def main():
    # Kill any Flask processes on the same port and Appium servers
    server.kill_existing_process("flask")
    server.kill_existing_process("appium")

    # Preserve emulators when restarting the server
    # This allows for faster reconnection and avoids unnecessary restarts
    logger.info("Preserving emulators during server startup for faster connection")

    # Ensure all existing automator instances have emulator_manager attached
    logger.info("Ensuring all automators have emulator_manager capability")
    for email, automator in server.automators.items():
        if automator and not hasattr(automator, "emulator_manager"):
            logger.info(f"Adding missing emulator_manager to automator for {email}")
            automator.emulator_manager = server.profile_manager.emulator_manager

    # Check ADB connectivity without killing the server or emulators
    try:
        # Just check device status to make sure ADB is responsive
        subprocess.run(
            [f"{server.android_home}/platform-tools/adb", "devices"],
            check=False,
            timeout=5,
            capture_output=True,
        )
        logger.info("ADB server is active, emulators preserved")
    except Exception as e:
        logger.warning(f"ADB check failed, will restart ADB server: {e}")
        try:
            # Only if ADB check fails, restart the ADB server
            subprocess.run(
                [f"{server.android_home}/platform-tools/adb", "kill-server"], check=False, timeout=5
            )
            time.sleep(1)
            subprocess.run(
                [f"{server.android_home}/platform-tools/adb", "start-server"], check=False, timeout=5
            )
            logger.info("ADB server restarted")
        except Exception as adb_e:
            logger.error(f"Error restarting ADB server: {adb_e}")

    # Start Appium server
    if not server.start_appium():
        logger.error("Failed to start Appium server")
        return

    # Save Flask server PID
    server.save_pid("flask", os.getpid())

    # Run the server directly, regardless of development mode
    run_server()


if __name__ == "__main__":
    # If running in background, write PID to file before starting server
    if os.getenv("FLASK_ENV") == "development":
        with open(os.path.join("logs", "flask.pid"), "w") as f:
            f.write(str(os.getpid()))
    main()
