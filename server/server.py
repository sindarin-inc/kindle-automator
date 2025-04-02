import base64
import logging
import os
import platform
import signal
import subprocess
import time
import traceback
from typing import Dict, List, Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from dotenv import load_dotenv
from flask import Flask, make_response, redirect, request, send_file
from flask_restful import Api, Resource
from mistralai import Mistral
from selenium.common import exceptions as selenium_exceptions

from automator import KindleAutomator
from handlers.auth_handler import LoginVerificationState
from handlers.test_fixtures_handler import TestFixturesHandler
from server.logging_config import setup_logger
from server.request_logger import setup_request_logger
from server.response_handler import handle_automator_response
from views.core.app_state import AppState

# Load environment variables from .env file
load_dotenv()

setup_logger()
logger = logging.getLogger(__name__)

# Development mode detection
IS_DEVELOPMENT = os.getenv("FLASK_ENV") == "development"

# We'll handle captcha solutions at runtime when passed via API, not from environment

app = Flask(__name__)
api = Api(app)

# Set up request and response logging middleware
setup_request_logger(app)


class AutomationServer:
    def __init__(self):
        self.automator: Optional[KindleAutomator] = None
        self.appium_process = None
        self.pid_dir = "logs"
        self.current_book = None  # Track the currently open book title
        os.makedirs(self.pid_dir, exist_ok=True)

        # Initialize the AVD profile manager
        self.android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        from views.core.avd_profile_manager import AVDProfileManager

        self.profile_manager = AVDProfileManager(base_dir=self.android_home)
        self.current_email = None

    def initialize_automator(self):
        """Initialize automator without credentials or captcha solution"""
        if not self.automator:
            # Initialize without credentials or captcha - they'll be set when needed
            self.automator = KindleAutomator()
            # Connect profile manager to automator for device ID tracking
            self.automator.profile_manager = self.profile_manager
            # Scan for any AVDs with email patterns in their names and register them
            discovered = self.profile_manager.scan_for_avds_with_emails()
            if discovered:
                logger.info(f"Auto-discovered {len(discovered)} email-to-AVD mappings: {discovered}")
        return self.automator

    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """Switch to a profile for the given email address.

        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any running emulator and start a new one
                               (used with recreate=1 flag)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info(f"Switching to profile for email: {email}, force_new_emulator={force_new_emulator}")

        # Check if we're already using this profile with a working emulator
        if self.current_email == email and not force_new_emulator:
            logger.info(f"Already using profile for {email}")
            
            # Check if there's a running emulator for this profile
            is_running, emulator_id, avd_name = self.profile_manager.find_running_emulator_for_email(email)
            
            if is_running and self.automator:
                logger.info(f"Automator already exists with running emulator for profile {email}, skipping profile switch")
                return True, f"Already using profile for {email} with running emulator"
            elif not is_running and self.automator:
                # We have an automator but no running emulator - decide what to do
                if force_new_emulator:
                    logger.info(f"No running emulator for profile {email}, cleaning up automator for restart")
                    self.automator.cleanup()
                    self.automator = None
                else:
                    logger.info(f"No running emulator for profile {email}, but have automator - will use on next reconnect")
                    return True, f"Profile {email} is already active, waiting for reconnection"
            else:
                logger.info(f"No automator exists for profile {email}, will reinitialize")

        # First cleanup existing automator if there is one
        if self.automator:
            logger.info("Cleaning up existing automator")
            self.automator.cleanup()
            self.automator = None

        # Switch to the profile for this email
        success, message = self.profile_manager.switch_profile(email, force_new_emulator=force_new_emulator)
        if not success:
            logger.error(f"Failed to switch profile: {message}")
            return False, message

        # Update current email
        self.current_email = email

        # Clear current book since we're switching profiles
        self.clear_current_book()

        logger.info(f"Successfully switched to profile for {email}")
        return True, message

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        pid_file = os.path.join(self.pid_dir, f"{name}.pid")
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
            # Set file permissions to be readable by all
            os.chmod(pid_file, 0o644)
        except Exception as e:
            logger.error(f"Error saving PID file: {e}")

    def kill_existing_process(self, name: str):
        """Kill existing process if running on port 4098"""
        try:
            if name == "flask":
                # Use lsof to find process on port 4098
                pid = subprocess.check_output(["lsof", "-t", "-i:4098"]).decode().strip()
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    logger.info(f"Killed existing flask process with PID {pid}")
            elif name == "appium":
                subprocess.run(["pkill", "-f", "appium"], check=False)
                logger.info("Killed existing appium processes")
        except subprocess.CalledProcessError:
            logger.info(f"No existing {name} process found")
        except Exception as e:
            logger.error(f"Error killing {name} process: {e}")

    def start_appium(self):
        """Start Appium server and save PID"""
        self.kill_existing_process("appium")
        try:
            self.appium_process = subprocess.Popen(
                ["appium"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            self.save_pid("appium", self.appium_process.pid)
            logger.info(f"Started Appium server with PID {self.appium_process.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Appium server: {e}")
            return False

    def set_current_book(self, book_title):
        """Set the currently open book title"""
        self.current_book = book_title
        logger.info(f"Set current book to: {book_title}")

    def clear_current_book(self):
        """Clear the currently open book tracking variable"""
        if self.current_book:
            logger.info(f"Cleared current book: {self.current_book}")
            self.current_book = None


server = AutomationServer()


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


def ensure_automator_healthy(f):
    """Decorator to ensure automator is initialized and healthy before each operation."""

    def wrapper(*args, **kwargs):
        max_retries = 3  # Allow more retries for UiAutomator2 crashes

        for attempt in range(max_retries):
            try:
                # Initialize automator if needed
                if not server.automator:
                    # If we have a current profile, ensure we're using it
                    current_profile = server.profile_manager.get_current_profile()
                    if current_profile:
                        # Use the existing profile
                        email = current_profile.get("email")
                        logger.info(f"Using existing profile for email: {email}")
                        success, message = server.switch_profile(email)
                        if not success:
                            logger.error(f"Failed to switch to existing profile: {message}")
                            return {"error": f"Failed to switch to existing profile: {message}"}, 500

                    logger.info("No automator found. Initializing automatically...")
                    server.initialize_automator()
                    if not server.automator.initialize_driver():
                        logger.error("Failed to initialize driver automatically")
                        return {
                            "error": "Failed to initialize driver automatically. Call /initialize first."
                        }, 500

                # Ensure driver is running
                if not server.automator.ensure_driver_running():
                    return {"error": "Failed to ensure driver is running"}, 500

                # Execute the function
                return f(*args, **kwargs)

            except Exception as e:
                # Check if it's the UiAutomator2 server crash error or other common crash patterns
                error_message = str(e)
                is_uiautomator_crash = any(
                    [
                        "cannot be proxied to UiAutomator2 server because the instrumentation process is not running"
                        in error_message,
                        "instrumentation process is not running" in error_message,
                        "Failed to establish a new connection" in error_message,
                        "Connection refused" in error_message,
                        "Connection reset by peer" in error_message,
                    ]
                )

                if is_uiautomator_crash and attempt < max_retries - 1:
                    logger.warning(
                        f"UiAutomator2 server crashed on attempt {attempt + 1}/{max_retries}. Restarting driver..."
                    )
                    logger.warning(f"Crash error: {error_message}")

                    # Kill any leftover UiAutomator2 processes directly via ADB
                    try:
                        if server.automator and server.automator.device_id:
                            device_id = server.automator.device_id
                            logger.info(f"Forcibly killing UiAutomator2 processes on device {device_id}")
                            subprocess.run(
                                [f"adb -s {device_id} shell pkill -f uiautomator"],
                                shell=True,
                                check=False,
                                timeout=5,
                            )
                            time.sleep(2)  # Give it time to fully terminate
                    except Exception as kill_e:
                        logger.warning(f"Error while killing UiAutomator2 processes: {kill_e}")

                    # Force a complete driver restart
                    if server.automator:
                        logger.info("Cleaning up automator resources")
                        server.automator.cleanup()

                    # Reset Appium server state as well
                    try:
                        logger.info("Resetting Appium server state")
                        subprocess.run(["pkill -f 'appium|node'"], shell=True, check=False, timeout=5)
                        time.sleep(2)  # Wait for processes to terminate

                        logger.info("Restarting Appium server")
                        if not server.start_appium():
                            logger.error("Failed to restart Appium server")
                    except Exception as appium_e:
                        logger.warning(f"Error while resetting Appium: {appium_e}")

                    # If we have a current profile, try to switch to it
                    current_profile = server.profile_manager.get_current_profile()
                    if current_profile:
                        email = current_profile.get("email")
                        logger.info(f"Attempting to switch back to profile for email: {email}")
                        success, message = server.switch_profile(email)
                        if not success:
                            logger.error(f"Failed to switch back to profile: {message}")
                            return {"error": f"Failed to switch back to profile: {message}"}, 500

                    logger.info("Initializing automator after crash recovery")
                    server.initialize_automator()
                    # Clear current book since we're restarting the driver
                    server.clear_current_book()

                    if server.automator.initialize_driver():
                        logger.info(
                            "Successfully restarted driver after UiAutomator2 crash, retrying operation..."
                        )
                        continue  # Retry the operation with the next loop iteration
                    else:
                        logger.error("Failed to restart driver after UiAutomator2 crash")

                # For non-UiAutomator2 crashes or if restart failed, log and return error
                logger.error(f"Error in operation (attempt {attempt + 1}/{max_retries}): {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

                # On the last attempt, return the error
                if attempt == max_retries - 1:
                    return {"error": str(e)}, 500

    return wrapper


class StateResource(Resource):
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
    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Get current captcha status and image if present"""
        # Return simple success response - the response handler will
        # intercept if we're in CAPTCHA state
        return {"status": "no_captcha"}, 200

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

        # Generate a unique filename with timestamp to avoid caching issues
        timestamp = int(time.time())
        filename = f"current_screen_{timestamp}.png"
        screenshot_path = os.path.join(server.automator.screenshots_dir, filename)

        # Take the screenshot
        try:
            # Check if we're in an auth-related state where we need to use secure screenshot
            current_state = server.automator.state_machine.current_state
            auth_states = [AppState.SIGN_IN, AppState.CAPTCHA, AppState.LIBRARY_SIGN_IN, AppState.UNKNOWN]

            # Check if the use_scrcpy parameter is explicitly set
            use_scrcpy = request.args.get("use_scrcpy", "0") in ("1", "true")

            if current_state == AppState.UNKNOWN and not use_scrcpy:
                # If state is unknown, update state first before deciding on screenshot method
                logger.info("State is UNKNOWN, updating state before choosing screenshot method")
                server.automator.state_machine.update_current_state()
                current_state = server.automator.state_machine.current_state
                logger.info(f"State after update: {current_state}")

            if current_state in auth_states or use_scrcpy:
                logger.info(
                    f"Using secure screenshot method for auth state: {current_state} or explicit scrcpy request"
                )
                # First attempt with secure screenshot method
                secure_path = server.automator.take_secure_screenshot(screenshot_path)
                if not secure_path:
                    # Try with standard method as fallback but catch FLAG_SECURE exceptions
                    logger.warning("Secure screenshot failed, falling back to standard method")
                    try:
                        server.automator.driver.save_screenshot(screenshot_path)
                    except Exception as inner_e:
                        # If this fails too, we'll log the error but continue with response processing
                        # so the error is properly reported to the client
                        logger.error(f"Standard screenshot also failed: {inner_e}")
                        failed = "Failed to take screenshot - FLAG_SECURE may be set"
            else:
                # Use standard screenshot for non-auth screens
                server.automator.driver.save_screenshot(screenshot_path)
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
            current_state = server.automator.state_machine.current_state
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
                    page_source = server.automator.driver.page_source

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
        else:
            return {"error": f"Invalid action: {action}"}, 400

        if success:
            # Get current page number and progress
            progress = server.automator.reader_handler.get_reading_progress()

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
    @ensure_automator_healthy
    @handle_automator_response(server)
    def _open_book(self, book_title):
        """Open a specific book - shared implementation for GET and POST."""
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

        logger.info(f"Opening book: {book_title}")

        if not book_title:
            return {"error": "Book title is required in the request"}, 400

        # Common function to capture progress and screenshot
        def capture_book_state(already_open=False):
            # Get reading progress
            progress = server.automator.reader_handler.get_reading_progress()
            logger.info(f"Progress: {progress}")

            # Save screenshot with unique ID
            screenshot_id = f"page_{int(time.time())}"
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
            time.sleep(0.5)
            server.automator.driver.save_screenshot(screenshot_path)

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
        server.automator.state_machine.update_current_state()
        current_state = server.automator.state_machine.current_state
        # Check if we're already in the reading state with the requested book
        if current_state != AppState.READING and server.current_book:
            logger.info(
                f"Not in reading state: {current_state}, but have book '{server.current_book}' tracked - clearing it"
            )
            server.clear_current_book()

        logger.info(f"Reloaded current state: {current_state}")
        if current_state == AppState.READING and server.current_book:
            # Normalize titles for comparison by removing special characters
            normalized_request_title = "".join(c for c in book_title if c.isalnum() or c.isspace()).lower()
            normalized_current_title = "".join(
                c for c in server.current_book if c.isalnum() or c.isspace()
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
                logger.info(f"Already reading book (partial match): {book_title}, returning current state")
                return capture_book_state(already_open=True)

            logger.info(
                f"No match found for book: {book_title} ({normalized_request_title}) != {server.current_book} ({normalized_current_title}), transitioning to library"
            )
        else:
            logger.info(
                f"Not already reading book: {book_title} != {server.current_book}, transitioning from {current_state} to library"
            )
        # If we're not already reading the requested book, transition to library and open it
        if server.automator.state_machine.transition_to_library(server=server):
            success = server.automator.reader_handler.open_book(book_title)
            logger.info(f"Book opened: {success}")

            if success:
                # Set the current book in the server state
                server.set_current_book(book_title)
                return capture_book_state()

        return {"error": "Failed to open book"}, 500

    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Open a specific book via POST request."""
        data = request.get_json()
        book_title = data.get("title")
        return self._open_book(book_title)

    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Open a specific book via GET request."""
        book_title = request.args.get("title")
        return self._open_book(book_title)


class StyleResource(Resource):
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
            progress = server.automator.reader_handler.get_reading_progress()

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
    @handle_automator_response(server)
    def post(self):
        """Authenticate with Amazon username and password"""
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        # Check if recreate parameter is provided
        recreate = False
        if request.is_json:
            recreate = data.get("recreate", False)
        else:
            recreate = request.args.get("recreate", "0") in ("1", "true")

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        logger.info(f"Authenticating with email: {email}")

        if not email or not password:
            return {"error": "Email and password are required in the request"}, 400

        # If recreate is requested, just clean up the automator but don't force a new emulator
        if recreate:
            logger.info(f"Recreate requested for {email}, cleaning up existing automator")
            # First clean up any existing automator
            if server.automator:
                logger.info("Cleaning up existing automator")
                server.automator.cleanup()
                server.automator = None

        # Switch to the profile for this email or create a new one
        # We don't force a new emulator - let the profile manager decide if one is needed
        success, message = server.switch_profile(email, force_new_emulator=False)
        if not success:
            logger.error(f"Failed to switch to profile for {email}: {message}")
            return {"error": f"Failed to switch to profile: {message}"}, 500

        # For M1/M2/M4 Macs where the emulator might not start,
        # we'll still continue with the profile tracking

        # Now that we've switched profiles, initialize the automator
        if not server.automator:
            server.initialize_automator()
            if not server.automator.initialize_driver():
                return {"error": "Failed to initialize driver"}, 500

        # Check if already authenticated by checking if we're in the library state
        server.automator.state_machine.update_current_state()
        current_state = server.automator.state_machine.current_state

        # We need to check if we're in the LIBRARY tab (not just home tab with library_root_view)
        if current_state == AppState.LIBRARY:
            logger.info("Already authenticated and in library state")
            return {"success": True, "message": "Already authenticated"}, 200

        # HOME tab is not considered authenticated yet, we need to switch to LIBRARY
        elif current_state == AppState.HOME:
            logger.info("Already logged in but in HOME state, need to switch to LIBRARY to verify books")

            # Try to click the LIBRARY tab
            try:
                library_tab = server.automator.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"
                )
                library_tab.click()
                logger.info("Clicked on LIBRARY tab")
                time.sleep(1)  # Wait for tab transition

                # Update state after clicking
                server.automator.state_machine.update_current_state()
                updated_state = server.automator.state_machine.current_state

                if updated_state == AppState.LIBRARY:
                    logger.info("Successfully switched to LIBRARY state")
                    return {"success": True, "message": "Switched to library view"}, 200
            except Exception as e:
                logger.error(f"Error clicking on LIBRARY tab: {e}")
                # Continue with normal authentication process

        # Update credentials using the dedicated method
        server.automator.update_credentials(email, password)

        # First try to reach sign-in state if we're not already there
        if current_state != AppState.SIGN_IN:
            logger.info(f"Not in sign-in state (current: {current_state.name}), attempting to transition")
            # Use existing state transition mechanisms to get to sign-in state
            if not server.automator.transition_to_library():
                # Take a screenshot for visual feedback
                timestamp = int(time.time())
                screenshot_id = f"auth_failed_transition_{timestamp}"
                screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
                server.automator.driver.save_screenshot(screenshot_path)

                # Update current state
                server.automator.state_machine.update_current_state()
                current_state = server.automator.state_machine.current_state

                response_data = {
                    "success": False,
                    "message": (
                        f"Could not transition to authentication state, current state: {current_state.name}"
                    ),
                }

                # Process the screenshot (either base64 encode or add URL)
                screenshot_data = process_screenshot_response(screenshot_id, use_base64)
                response_data.update(screenshot_data)

                return response_data, 500

        # Now proceed with authentication
        auth_result = server.automator.state_machine.auth_handler.sign_in()
        logger.debug(f"Authentication result: {auth_result}")
        # auth_result could be a boolean (success/failure) or tuple with (LoginVerificationState, message)

        # Check if auth_result is a tuple with error information
        error_message = None
        incorrect_password = False
        if isinstance(auth_result, tuple) and len(auth_result) == 2:
            state, message = auth_result
            if state in [LoginVerificationState.INCORRECT_PASSWORD, LoginVerificationState.ERROR]:
                incorrect_password = True
                error_message = message
                logger.error(f"Authentication failed with incorrect password: {message}")
                # Return immediately with error response without retrying
                return {"success": False, "message": message, "error_type": "incorrect_password"}, 401

        # Update current state after auth attempt
        server.automator.state_machine.update_current_state()
        current_state = server.automator.state_machine.current_state

        # Take a screenshot only for auth-related states, skip for successful auth
        screenshot_data = {}
        screenshot_id = None

        # If authentication was successful and we're in LIBRARY state, skip screenshot
        if not incorrect_password and current_state == AppState.LIBRARY:
            logger.info("Authentication successful - skipping screenshot since we're in LIBRARY state")
        else:
            # Only take screenshot for errors or non-LIBRARY states
            timestamp = int(time.time())
            screenshot_id = f"auth_screen_{timestamp}"
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")

            try:
                # Use secure screenshot for auth screens
                secure_path = server.automator.take_secure_screenshot(screenshot_path)
                if secure_path:
                    # Process the screenshot (either base64 encode or add URL)
                    screenshot_data = process_screenshot_response(screenshot_id, use_base64)
                    logger.info(f"Saved secure authentication screenshot to {screenshot_path}")
                else:
                    # Try standard method as fallback
                    logger.warning("Secure screenshot failed, trying standard method")
                    try:
                        server.automator.driver.save_screenshot(screenshot_path)
                        # Process the screenshot (either base64 encode or add URL)
                        screenshot_data = process_screenshot_response(screenshot_id, use_base64)
                        logger.info(
                            f"Saved authentication screenshot using standard method to {screenshot_path}"
                        )
                    except Exception as inner_e:
                        logger.warning(f"Standard screenshot also failed: {inner_e}")
            except Exception as e:
                logger.warning(f"Failed to take authentication screenshot: {e}")
                # This is expected on secure screens like password entry

        # Check for authentication errors
        error_message = None
        try:
            # Check for error message box - use the strategy defined in ERROR_VIEW_IDENTIFIERS
            from views.auth.view_strategies import ERROR_VIEW_IDENTIFIERS

            error_strategy, error_locator = ERROR_VIEW_IDENTIFIERS[
                2
            ]  # This is the auth-error-message-box strategy
            error_box = server.automator.driver.find_element(error_strategy, error_locator)

            if error_box:
                # Try to find specific error messages
                try:
                    # Use the strategy from AUTH_ERROR_STRATEGIES
                    from views.auth.interaction_strategies import AUTH_ERROR_STRATEGIES

                    error_strategy, error_locator = AUTH_ERROR_STRATEGIES[
                        4
                    ]  # This is the generic error message view
                    error_elements = server.automator.driver.find_elements(error_strategy, error_locator)
                    error_texts = []
                    for elem in error_elements:
                        if elem.text and elem.text.strip():
                            error_texts.append(elem.text.strip())

                    if error_texts:
                        error_message = " - ".join(error_texts)
                        logger.error(f"Authentication error: {error_message}")
                except Exception as e:
                    logger.error(f"Error extracting message from error box: {e}")
                    error_message = "Authentication error"
        except:
            # No error box found
            pass

        # Handle different states
        if current_state == AppState.LIBRARY:
            response_data = {"success": True, "message": "Authentication successful"}
            response_data.update(screenshot_data)
            return response_data, 200
        elif current_state == AppState.CAPTCHA:
            response_data = {
                "success": False,
                "requires": "captcha",
                "message": "CAPTCHA required",
            }
            response_data.update(screenshot_data)
            return response_data, 202
        elif (
            current_state == AppState.SIGN_IN
            and auth_result
            and len(auth_result) >= 1
            and auth_result[0] == LoginVerificationState.TWO_FACTOR
        ):
            response_data = {
                "success": False,
                "requires": "2fa",
                "message": "2FA code required",
            }
            response_data.update(screenshot_data)
            return response_data, 202
        else:
            # Return the specific error message if we found one
            if incorrect_password:
                # Special case for incorrect password - don't retry
                return {"success": False, "message": error_message, "error_type": "incorrect_password"}, 401
            elif error_message:
                response_data = {
                    "success": False,
                    "message": error_message,
                }
                response_data.update(screenshot_data)
                return response_data, 401
            else:
                response_data = {
                    "success": False,
                    "message": f"Authentication failed, current state: {current_state.name}",
                }
                response_data.update(screenshot_data)
                return response_data, 401


class FixturesResource(Resource):
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

        if not os.path.exists(image_path):
            logger.error(f"Image not found at path: {image_path}")
            return {"error": "Image not found"}, 404

        # Create a response that bypasses Flask-RESTful's serialization
        response = make_response(send_file(image_path, mimetype="image/png"))

        # Delete the file after sending if requested
        if delete_after:
            try:
                os.remove(image_path)
                logger.info(f"Deleted image: {image_path}")
            except Exception as e:
                logger.error(f"Failed to delete image {image_path}: {e}")

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

            # Process the image with OCR
            ocr_response = client.ocr.process(
                model="mistral-ocr-latest",
                document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"},
            )

            # Extract and return the OCR text
            logger.info(f"OCR response: {ocr_response}")
            if ocr_response and hasattr(ocr_response, "pages") and len(ocr_response.pages) > 0:
                page = ocr_response.pages[0]
                return page.markdown, None
            else:
                error_msg = "No OCR response or no pages found"
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
        return serve_image(image_id, delete_after=False)

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        return serve_image(image_id, delete_after=False)


class ProfilesResource(Resource):
    def get(self):
        """List all available profiles"""
        profiles = server.profile_manager.list_profiles()
        current = server.profile_manager.get_current_profile()

        return {"profiles": profiles, "current": current}, 200

    def post(self):
        """Create or delete a profile"""
        data = request.get_json()
        action = data.get("action")
        email = data.get("email")

        if not email:
            return {"error": "Email is required"}, 400

        if action == "create":
            success, message = server.profile_manager.create_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        elif action == "delete":
            success, message = server.profile_manager.delete_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        elif action == "switch":
            success, message = server.switch_profile(email)
            return {"success": success, "message": message}, 200 if success else 500

        else:
            return {"error": f"Invalid action: {action}"}, 400


class TextResource(Resource):
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
                from views.reading.interaction_strategies import ABOUT_BOOK_SLIDEOVER_IDENTIFIERS, BOTTOM_SHEET_IDENTIFIERS
                
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
                                logger.warning("'About this book' slideover is still visible after multiple dismissal attempts")
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
            progress = server.automator.reader_handler.get_reading_progress()
            
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
                    return {
                        "success": True,
                        "progress": progress,
                        "text": ocr_text
                    }, 200
                else:
                    return {
                        "success": False,
                        "progress": progress,
                        "error": error or "OCR processing failed"
                    }, 500
                
            except Exception as e:
                logger.error(f"Error processing OCR: {e}")
                return {
                    "success": False,
                    "progress": progress,
                    "error": f"Failed to extract text: {str(e)}"
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
api.add_resource(BookOpenResource, "/open-book")
api.add_resource(StyleResource, "/style")
api.add_resource(TwoFactorResource, "/2fa")
api.add_resource(AuthResource, "/auth")
api.add_resource(FixturesResource, "/fixtures")
api.add_resource(ImageResource, "/image/<string:image_id>")
api.add_resource(ProfilesResource, "/profiles")
api.add_resource(TextResource, "/text")


def cleanup_resources():
    """Clean up resources before exiting"""
    logger.info("Cleaning up resources before shutdown...")

    # Detect if we're on Mac in development mode
    is_mac_dev = platform.system() == "Darwin" and os.environ.get("FLASK_ENV") == "development"

    # Kill any running emulators (skip on Mac development environment)
    if not is_mac_dev:
        try:
            logger.info("Stopping any running emulators")
            subprocess.run(["pkill", "-f", "emulator"], check=False, timeout=3)
            subprocess.run(["pkill", "-f", "qemu"], check=False, timeout=3)
        except Exception as e:
            logger.error(f"Error stopping emulators during shutdown: {e}")
    else:
        logger.info("Mac development environment detected - skipping emulator cleanup to preserve local emulators")

    # Kill Appium server
    try:
        logger.info("Stopping Appium server")
        server.kill_existing_process("appium")
    except Exception as e:
        logger.error(f"Error stopping Appium during shutdown: {e}")

    # Reset ADB server
    try:
        logger.info("Resetting ADB server")
        subprocess.run([f"{server.android_home}/platform-tools/adb", "kill-server"], check=False, timeout=3)
    except Exception as e:
        logger.error(f"Error resetting ADB during shutdown: {e}")

    logger.info("Cleanup complete, server shutting down")


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
    # Kill any existing processes
    server.kill_existing_process("flask")
    server.kill_existing_process("appium")

    # Detect if we're on Mac in development mode
    is_mac_dev = platform.system() == "Darwin" and os.environ.get("FLASK_ENV") == "development"

    # Only force clean emulators on non-Mac development environments
    if not is_mac_dev:
        try:
            logger.info("Forcibly cleaning up any existing emulators at startup")
            subprocess.run(["pkill", "-9", "-f", "emulator"], check=False, timeout=5)
            subprocess.run(["pkill", "-9", "-f", "qemu"], check=False, timeout=5)
            # Reset adb server to ensure clean state
            subprocess.run(
                [f"{server.android_home}/platform-tools/adb", "kill-server"], check=False, timeout=5
            )
            time.sleep(1)
            subprocess.run(
                [f"{server.android_home}/platform-tools/adb", "start-server"], check=False, timeout=5
            )
            logger.info("Emulator cleanup at startup completed")
        except Exception as e:
            logger.error(f"Error during startup emulator cleanup: {e}")
    else:
        logger.info(
            "Mac development environment detected - skipping emulator cleanup to preserve local emulators"
        )
        # Just reset adb server to ensure clean state, without killing emulators
        try:
            subprocess.run([f"{server.android_home}/platform-tools/adb", "devices"], check=False, timeout=5)
            logger.info("ADB server reset completed, existing emulators preserved")
        except Exception as e:
            logger.error(f"Error resetting ADB server: {e}")

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