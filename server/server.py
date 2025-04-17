import concurrent.futures
import logging
import os
import platform
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import flask
import requests
from appium.webdriver.common.appiumby import AppiumBy
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, redirect, request, send_file
from flask_restful import Api, Resource
from mistralai import Mistral
from selenium.common import exceptions as selenium_exceptions

from automator import KindleAutomator
from handlers.auth_handler import LoginVerificationState
from handlers.test_fixtures_handler import TestFixturesHandler
from server.automation_server import AutomationServer
from server.config import BASE_DIR  # Import constants from config
from server.image_utils import (
    KindleOCR,
    get_image_path,
    is_base64_requested,
    is_ocr_requested,
    process_screenshot_response,
    serve_image,
)
from server.logging_config import setup_logger
from server.middleware import (
    ensure_automator_healthy,
    ensure_user_profile_loaded,
    get_sindarin_email,
)
from server.request_logger import setup_request_logger
from server.response_handler import handle_automator_response
from views.core.app_state import AppState

# Set up logging
setup_logger()
logger = logging.getLogger(__name__)

# Environment setup
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

# Set up Flask application
app = Flask(__name__)
api = Api(app)

# Create the server instance
server = AutomationServer()

# Store server instance in app config for access in middleware
app.config["server_instance"] = server

# Set up request and response logging middleware
setup_request_logger(app)


# === RESOURCE CLASSES (ENDPOINTS) ===


class InitializeResource(Resource):
    def post(self):
        """Explicitly initialize the automation driver.

        Note: This endpoint is optional as the system automatically initializes
        when needed on other endpoints. It can be used for pre-initialization.
        """
        try:
            # Initialize automator without credentials - they'll be set during authentication
            server.initialize_automator()
            success = server.automator.initialize_driver()

            if not success:
                return {"error": "Failed to initialize driver"}, 500

            # Clear the current book since we're reinitializing the app
            server.clear_current_book()

            return {
                "status": "initialized",
                "message": (
                    "Device initialized. Use /auth endpoint to authenticate with your Amazon credentials."
                ),
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
            # Check if we're on the sign-in screen without credentials
            if current_state == AppState.SIGN_IN or current_state == AppState.LIBRARY_SIGN_IN:
                # Check if we have credentials set
                if not server.automator.email or not server.automator.password:
                    logger.info("Authentication required but no credentials are set")
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "current_state": current_state.name,
                        "message": "You need to provide Amazon credentials via the /auth endpoint",
                    }, 401

            # Try to transition to library state
            logger.info("Not in library state, attempting to transition...")
            transition_success = server.automator.state_machine.transition_to_library(server=server)

            # Get the updated state after transition attempt
            new_state = server.automator.state_machine.current_state
            logger.info(f"State after transition attempt: {new_state}")

            # Check for auth requirement regardless of transition success
            if new_state == AppState.SIGN_IN:
                # Check if we have credentials set
                if not server.automator.email or not server.automator.password:
                    logger.info("Authentication required after transition attempt but no credentials are set")
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "current_state": new_state.name,
                        "message": "You need to provide Amazon credentials via the /auth endpoint",
                    }, 401

            if transition_success:
                logger.info("Successfully transitioned to library state")
                # Get books with metadata from library handler
                books = server.automator.library_handler.get_book_titles()

                # If books is None, it means authentication is required
                if books is None:
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "message": "You need to sign in to access your Kindle library",
                    }, 401

                return {"books": books}, 200
            else:
                # If transition failed, check for auth requirement
                updated_state = server.automator.state_machine.current_state

                if updated_state == AppState.SIGN_IN:
                    logger.info("Transition failed - authentication required")
                    return {
                        "error": "Authentication required",
                        "requires_auth": True,
                        "current_state": updated_state.name,
                        "message": "You need to provide Amazon credentials via the /auth endpoint",
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
            return {
                "error": "Authentication required",
                "requires_auth": True,
                "message": "You need to sign in to access your Kindle library",
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
            failed = str(e)

        # Process the response for various modes (base64, URL, OCR)
        response_data, status_code = process_screenshot_response(
            screenshot_path=screenshot_path if not failed else None,
            include_xml=include_xml,
            perform_ocr=perform_ocr,
            use_base64=use_base64,
            automator=automator,
        )

        if failed:
            response_data["error"] = failed
            status_code = 500

        return response_data, status_code


class NavigationResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Navigate to a specific section"""
        data = request.get_json()
        destination = data.get("destination", "").lower()
        valid_destinations = ["library", "home", "more"]

        if not destination:
            return {"error": "No destination specified"}, 400

        if destination not in valid_destinations:
            return {"error": f"Invalid destination. Choose from: {', '.join(valid_destinations)}"}, 400

        # Handle different destinations
        if destination == "library":
            success = server.automator.state_machine.transition_to_library()
        elif destination == "home":
            success = server.automator.state_machine.transition_to_home()
        elif destination == "more":
            # TODO: Implement "More" section navigation
            return {"error": "Navigation to 'More' section not yet implemented"}, 501

        if success:
            server.automator.state_machine.update_current_state()
            current_state = server.automator.state_machine.current_state
            return {"status": "success", "current_state": current_state.name}, 200
        else:
            # If navigation failed, return the current state
            server.automator.state_machine.update_current_state()
            current_state = server.automator.state_machine.current_state
            return {
                "error": f"Failed to navigate to {destination}",
                "current_state": current_state.name,
            }, 400

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Get or use device back button for navigation"""
        # Check if this is a back button request
        if "back" in request.args and request.args.get("back") in ("1", "true"):
            logger.info("Using device back button")
            try:
                server.automator.press_back_button()
                # Update state after back button
                server.automator.state_machine.update_current_state()
                current_state = server.automator.state_machine.current_state
                # For books, also capture the progress
                progress = None
                if current_state == AppState.READING:
                    try:
                        progress = server.automator.reader_handler.get_reading_progress()
                    except Exception as p_err:
                        logger.warning(f"Failed to get reading progress: {p_err}")

                return {
                    "status": "success",
                    "action": "back",
                    "current_state": current_state.name,
                    "progress": progress,
                }, 200

            except Exception as e:
                logger.error(f"Error using back button: {e}")
                return {"error": f"Failed to use back button: {str(e)}"}, 500

        # If no specific action, just return the current state
        server.automator.state_machine.update_current_state()
        current_state = server.automator.state_machine.current_state
        return {"current_state": current_state.name}, 200


class BookOpenResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def _open_book(self):
        """Open a book by title"""
        data = request.get_json() if request.is_json else None
        query_params = request.args

        # Get book title from either JSON body or query parameters
        book_title = None
        if data and "title" in data:
            book_title = data.get("title")
        elif "title" in query_params:
            book_title = query_params.get("title")

        if not book_title:
            return {"error": "Book title is required"}, 400

        # Get position parameter if provided
        position = 0
        if data and "position" in data:
            try:
                position = float(data.get("position", 0))
            except (ValueError, TypeError):
                position = 0
        elif "position" in query_params:
            try:
                position = float(query_params.get("position", 0))
            except (ValueError, TypeError):
                position = 0

        # Get the current state
        current_state = server.automator.state_machine.current_state

        # Track if we need to go to library first
        need_to_go_to_library = False

        # If already in reading state with same book, no need to reopen
        if (
            current_state == AppState.READING
            and server.current_book
            and server.current_book.lower() == book_title.lower()
        ):
            # If position is specified and not at beginning, navigate to that position
            if position > 0:
                logger.info(f"Already reading '{book_title}'. Navigating to position {position}")
                success = server.automator.reader_handler.navigate_to_position(position)
                if not success:
                    return {"error": f"Failed to navigate to position {position}"}, 500
            else:
                logger.info(f"Already reading '{book_title}'. No position change needed.")

            reading_progress = server.automator.reader_handler.get_reading_progress()

            # Capture book state with screenshot
            screenshot_id = None
            try:
                screenshot_path = os.path.join(
                    server.automator.screenshots_dir, f"book_screen_{int(time.time())}.png"
                )
                server.automator.driver.save_screenshot(screenshot_path)
                screenshot_id = os.path.basename(screenshot_path).split(".")[0]
            except Exception as ss_err:
                logger.warning(f"Failed to capture book screenshot: {ss_err}")

            response = {
                "status": "success",
                "message": f"Already reading {book_title}",
                "current_state": current_state.name,
                "book_title": book_title,
                "progress": reading_progress,
            }

            if screenshot_id:
                response["screenshot_id"] = screenshot_id
                response["image_url"] = f"/image/{screenshot_id}"

            return response, 200

        # If not in LIBRARY state, transition to library first
        if current_state != AppState.LIBRARY:
            logger.info(f"Currently in {current_state}, transitioning to LIBRARY first")
            need_to_go_to_library = True
            success = server.automator.state_machine.transition_to_library()
            if not success:
                return {"error": "Failed to transition to LIBRARY state"}, 500

        # Search for and open the book
        logger.info(f"Searching for book: '{book_title}'")

        # Open the book - this returns a boolean indicating success
        success = server.automator.library_handler.open_book(book_title)

        if not success:
            return {
                "error": f"Book not found: {book_title}",
            }, 404

        # Set the current book title
        server.set_current_book(book_title)

        # If position is specified and not at beginning, navigate to that position
        if position > 0:
            logger.info(f"Navigating to position {position} in '{book_title}'")
            nav_success = server.automator.reader_handler.navigate_to_position(position)
            if not nav_success:
                return {"error": f"Opened book but failed to navigate to position {position}"}, 500

        # Get reading progress
        reading_progress = server.automator.reader_handler.get_reading_progress()

        # Capture book state with screenshot
        screenshot_id = None
        try:
            screenshot_path = os.path.join(
                server.automator.screenshots_dir, f"book_screen_{int(time.time())}.png"
            )
            server.automator.driver.save_screenshot(screenshot_path)
            screenshot_id = os.path.basename(screenshot_path).split(".")[0]
        except Exception as ss_err:
            logger.warning(f"Failed to capture book screenshot: {ss_err}")

        response = {
            "status": "success",
            "message": f"Successfully opened {book_title}"
            + (f" at position {position}" if position > 0 else ""),
            "book_title": book_title,
            "progress": reading_progress,
        }

        if screenshot_id:
            response["screenshot_id"] = screenshot_id
            response["image_url"] = f"/image/{screenshot_id}"

        # If we had to go to library first, add that to the response
        if need_to_go_to_library:
            response["navigation_steps"] = ["library", "open_book"]

        return response, 200

    def post(self):
        """Handle POST request to open a book"""
        return self._open_book()

    def get(self):
        """Handle GET request to open a book"""
        return self._open_book()


class StyleResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Update reading style (font, font size, margin, etc.)"""
        data = request.get_json()

        if not data:
            return {"error": "No style settings provided"}, 400

        # Check if the automator is in reading state
        if server.automator.state_machine.current_state != AppState.READING:
            return {"error": "Cannot update style when not in reading mode"}, 400

        # Track successful changes
        applied_changes = {}
        failed_changes = {}

        # Process font size
        if "font_size" in data:
            try:
                font_size = int(data["font_size"])
                size_success = server.automator.reader_handler.set_font_size(font_size)
                if size_success:
                    applied_changes["font_size"] = font_size
                else:
                    failed_changes["font_size"] = "Failed to set font size"
            except (ValueError, TypeError) as e:
                failed_changes["font_size"] = f"Invalid font size value: {str(e)}"

        # Process font face
        if "font" in data:
            font = data["font"]
            font_success = server.automator.reader_handler.set_font(font)
            if font_success:
                applied_changes["font"] = font
            else:
                failed_changes["font"] = f"Failed to set font to {font}"

        # Process theme/color
        if "theme" in data:
            theme = data["theme"]
            theme_success = server.automator.reader_handler.set_theme(theme)
            if theme_success:
                applied_changes["theme"] = theme
            else:
                failed_changes["theme"] = f"Failed to set theme to {theme}"

        # Process margins
        if "margin" in data:
            try:
                margin = int(data["margin"])
                margin_success = server.automator.reader_handler.set_margin(margin)
                if margin_success:
                    applied_changes["margin"] = margin
                else:
                    failed_changes["margin"] = "Failed to set margin"
            except (ValueError, TypeError) as e:
                failed_changes["margin"] = f"Invalid margin value: {str(e)}"

        # Process line spacing
        if "spacing" in data:
            try:
                spacing = int(data["spacing"])
                spacing_success = server.automator.reader_handler.set_line_spacing(spacing)
                if spacing_success:
                    applied_changes["spacing"] = spacing
                else:
                    failed_changes["spacing"] = "Failed to set line spacing"
            except (ValueError, TypeError) as e:
                failed_changes["spacing"] = f"Invalid spacing value: {str(e)}"

        # Create response
        response = {
            "status": "success" if len(applied_changes) > 0 else "failure",
            "applied_changes": applied_changes,
        }

        if failed_changes:
            response["failed_changes"] = failed_changes
            if len(applied_changes) == 0:
                return response, 500

        return response, 200


class TwoFactorResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Submit 2FA code"""
        data = request.get_json()
        code = data.get("code")

        if not code:
            return {"error": "2FA verification code required"}, 400

        # Check if we're in the right state
        current_state = server.automator.state_machine.current_state
        if current_state != LoginVerificationState.OTP_VERIFICATION:
            return {
                "error": f"Cannot submit 2FA code in current state: {current_state.name}",
                "current_state": current_state.name,
            }, 400

        # Submit the code
        success = server.automator.auth_handler.submit_otp_code(code)

        if success:
            # Verify we're now signed in
            server.automator.state_machine.update_current_state()
            new_state = server.automator.state_machine.current_state

            if new_state == AppState.LIBRARY:
                return {"status": "success", "current_state": new_state.name}, 200
            elif new_state == LoginVerificationState.OTP_VERIFICATION:
                return {"error": "Incorrect verification code", "error_type": "incorrect_code"}, 400
            else:
                return {
                    "status": "partial",
                    "message": f"Code accepted but not in library state. Current state: {new_state.name}",
                    "current_state": new_state.name,
                }, 200
        else:
            return {"error": "Failed to submit verification code"}, 500


class AuthResource(Resource):
    @ensure_user_profile_loaded
    @handle_automator_response(server)
    def post(self):
        """Authenticate with Amazon credentials"""
        data = request.get_json()

        username = data.get("username") or data.get("email")
        password = data.get("password")
        captcha_solution = data.get("captcha_solution")
        recreate = data.get("recreate", 0) == 1

        if not username or not password:
            return {"error": "Username and password are required"}, 400

        # Set this as the current email
        server.current_email = username
        sindarin_email = username

        # Check if we need to create a new emulator or reuse existing
        if recreate:
            logger.info(f"Recreate flag set, forcing new emulator for {username}")
            success, message = server.switch_profile(username, force_new_emulator=True)
            if not success:
                logger.error(f"Failed to switch profile with force_new_emulator: {message}")
                return {"error": f"Failed to initialize profile: {message}"}, 500

        # Initialize automator with credentials
        automator = server.automators.get(sindarin_email)

        if not automator:
            logger.info(f"Initializing automator for {sindarin_email}")
            automator = server.initialize_automator(sindarin_email)

        if not automator:
            return {"error": "Failed to initialize automator"}, 500

        # Set credentials
        automator.email = username
        automator.password = password

        # Set captcha solution if provided
        if captcha_solution:
            automator.captcha_solution = captcha_solution

        # Initialize driver if needed
        if not automator.driver:
            logger.info("Initializing driver for authentication")
            if not automator.initialize_driver():
                return {"error": "Failed to initialize driver"}, 500

        # Attempt to sign in
        logger.info(f"Attempting to sign in with {username}")

        # clear current book since we're authenticating
        server.clear_current_book(sindarin_email)

        auth_result = automator.auth_handler.sign_in()

        # Check the result
        if auth_result == "success":
            # Successful authentication
            return {"status": "success", "message": "Successfully authenticated"}, 200
        elif auth_result == "captcha":
            # Captcha required - handled by @handle_automator_response decorator
            return {"status": "captcha_required"}, 403
        elif auth_result == "incorrect_password":
            # Incorrect password
            return {
                "error": "Authentication failed: Incorrect password",
                "error_type": "incorrect_password",
            }, 401
        elif auth_result == "2fa_required":
            # 2FA required
            return {
                "status": "2fa_required",
                "message": "Two-factor authentication required",
                "verification_method": "otp",  # Currently only support OTP
            }, 200
        else:
            # Unknown error
            return {"error": f"Authentication failed: {auth_result}"}, 500


class FixturesResource(Resource):
    """API for managing test fixtures"""

    @ensure_user_profile_loaded
    def post(self):
        """Load or record test fixtures"""
        try:
            data = request.get_json()
            action = data.get("action", "").lower()
            state = data.get("state", "")

            # Create fixtures handler
            handler = TestFixturesHandler()

            # Handle different actions
            if action == "load":
                if not state:
                    return {"error": "State name is required for loading fixtures"}, 400

                success = handler.load_state(state)
                if success:
                    return {"status": "success", "message": f"Loaded fixtures for state: {state}"}, 200
                else:
                    return {"error": f"Failed to load fixtures for state: {state}"}, 500

            elif action == "record":
                if not state:
                    return {"error": "State name is required for recording fixtures"}, 400

                # Get XML page source from current state
                if server.automator and server.automator.driver:
                    try:
                        page_source = server.automator.driver.page_source
                        success = handler.save_state(state, page_source)
                        if success:
                            return {
                                "status": "success",
                                "message": f"Recorded fixtures for state: {state}",
                            }, 200
                        else:
                            return {"error": f"Failed to record fixtures for state: {state}"}, 500
                    except Exception as e:
                        return {"error": f"Error capturing page source: {e}"}, 500
                else:
                    return {"error": "No active driver available for capturing state"}, 500
            else:
                return {"error": f"Unknown action: {action}. Use 'load' or 'record'."}, 400

        except Exception as e:
            logger.error(f"Error in fixtures endpoint: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class ImageResource(Resource):
    """API endpoint for serving images by ID"""

    def get(self, image_id):
        """Get an image by ID"""
        delete_after = request.args.get("delete", "0") in ("1", "true")
        return serve_image(image_id, server, delete_after_serve=delete_after)


class XMLResource(Resource):
    """API endpoint for serving XML files by ID"""

    def get(self, xml_id):
        """Get an XML file by ID"""
        try:
            # Look for XML file with this ID in screenshots directory
            automator = server.automator
            if not automator:
                return {"error": "No active automator"}, 500

            xml_path = os.path.join(automator.screenshots_dir, f"{xml_id}.xml")

            if not os.path.exists(xml_path):
                return {"error": f"XML file not found: {xml_id}"}, 404

            # Return the XML file
            return send_file(xml_path, mimetype="text/xml")
        except Exception as e:
            logger.error(f"Error serving XML file: {e}")
            return {"error": f"Failed to serve XML file: {str(e)}"}, 500


# Register API resources
api.add_resource(InitializeResource, "/initialize")
api.add_resource(StateResource, "/state")
api.add_resource(CaptchaResource, "/captcha")
api.add_resource(BooksResource, "/books")
api.add_resource(ScreenshotResource, "/screenshot")
api.add_resource(NavigationResource, "/navigate")
api.add_resource(BookOpenResource, "/open_book", "/open-book")
api.add_resource(StyleResource, "/style")
api.add_resource(TwoFactorResource, "/2fa")
api.add_resource(AuthResource, "/auth")
api.add_resource(FixturesResource, "/fixtures")
api.add_resource(ImageResource, "/image/<string:image_id>")
api.add_resource(XMLResource, "/xml/<string:xml_id>")


# Start server when run directly (not imported)
if __name__ == "__main__":
    # Set up Appium server
    if not server.start_appium():
        logger.error("Failed to start Appium server, exiting")
        exit(1)

    # Save Flask PID
    import os

    server.save_pid("flask", os.getpid())

    # Start the server
    from server.config import HOST, PORT

    app.run(host=HOST, port=PORT, debug=IS_DEVELOPMENT)
