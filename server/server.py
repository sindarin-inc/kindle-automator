import base64
import logging
import os
import signal
import subprocess
import time
import traceback
from typing import Optional

from appium.webdriver.common.appiumby import AppiumBy
from flask import Flask, make_response, redirect, request, send_file
from flask_restful import Api, Resource
from selenium.common import exceptions as selenium_exceptions

from automator import KindleAutomator
from handlers.auth_handler import LoginVerificationState
from handlers.test_fixtures_handler import TestFixturesHandler
from server.logging_config import setup_logger
from server.response_handler import handle_automator_response
from views.core.app_state import AppState

setup_logger()
logger = logging.getLogger(__name__)

# Development mode detection
IS_DEVELOPMENT = os.getenv("FLASK_ENV") == "development"

# Load configuration
try:
    import config

    AMAZON_EMAIL = config.AMAZON_EMAIL
    AMAZON_PASSWORD = config.AMAZON_PASSWORD
    CAPTCHA_SOLUTION = getattr(config, "CAPTCHA_SOLUTION", None)
except ImportError:
    logger.warning("No config.py found. Using default credentials from config.template.py")
    import config_template

    AMAZON_EMAIL = config_template.AMAZON_EMAIL
    AMAZON_PASSWORD = config_template.AMAZON_PASSWORD
    CAPTCHA_SOLUTION = None

app = Flask(__name__)
api = Api(app)


class AutomationServer:
    def __init__(self):
        self.automator: Optional[KindleAutomator] = None
        self.appium_process = None
        self.pid_dir = "logs"
        os.makedirs(self.pid_dir, exist_ok=True)

    def initialize_automator(self):
        """Initialize automator with configured credentials"""
        if not self.automator:
            self.automator = KindleAutomator(AMAZON_EMAIL, AMAZON_PASSWORD, CAPTCHA_SOLUTION)
        return self.automator

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


server = AutomationServer()


class InitializeResource(Resource):
    def post(self):
        try:
            data = request.get_json()
            email = data.get("email", AMAZON_EMAIL)  # Fall back to config email
            password = data.get("password", AMAZON_PASSWORD)  # Fall back to config password

            if not email or not password:
                return {"error": "Email and password are required"}, 400

            server.automator = KindleAutomator(email, password, CAPTCHA_SOLUTION)
            success = server.automator.initialize_driver()

            if not success:
                return {"error": "Failed to initialize driver"}, 500

            return {"status": "initialized"}, 200

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
                    logger.info("No automator found, initializing...")
                    server.initialize_automator()
                    if not server.automator.initialize_driver():
                        return {"error": "Failed to initialize driver"}, 500

                # Ensure driver is running
                if not server.automator.ensure_driver_running():
                    return {"error": "Failed to ensure driver is running"}, 500

                # Execute the function
                return f(*args, **kwargs)

            except Exception as e:
                # Check if it's the UiAutomator2 server crash error
                is_uiautomator_crash = isinstance(
                    e, selenium_exceptions.WebDriverException
                ) and "cannot be proxied to UiAutomator2 server because the instrumentation process is not running" in str(
                    e
                )

                if is_uiautomator_crash and attempt < max_retries - 1:
                    logger.warning(
                        f"UiAutomator2 server crashed on attempt {attempt + 1}/{max_retries}. Restarting driver..."
                    )

                    # Force a complete driver restart
                    if server.automator:
                        server.automator.cleanup()
                        server.initialize_automator()
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

        # Update captcha solution if different
        server.automator.update_captcha_solution(solution)
        # Also update it directly in the state machine's auth handler as a backup
        server.automator.state_machine.auth_handler.captcha_solution = solution

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
            # Try to transition to library state
            logger.info("Not in library state, attempting to transition...")
            if server.automator.state_machine.transition_to_library():
                logger.info("Successfully transitioned to library state")
                # Get books with metadata from library handler
                books = server.automator.library_handler.get_book_titles()
                if books is None:
                    return {"error": "Failed to get books"}, 500
                return {"books": books}, 200
            else:
                return {
                    "error": f"Cannot get books in current state: {current_state.name}",
                    "current_state": current_state.name,
                }, 400

        # Get books with metadata from library handler
        books = server.automator.library_handler.get_book_titles()
        if books is None:
            return {"error": "Failed to get books"}, 500

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
        If xml=1 is provided, also returns the XML page source."""
        failed = None
        # Check if save parameter is provided
        save = request.args.get("save", "0") == "1"
        # Check if xml parameter is provided
        include_xml = request.args.get("xml", "0") in ("1", "true")

        # Generate a unique filename with timestamp to avoid caching issues
        timestamp = int(time.time())
        filename = f"current_screen_{timestamp}.png"
        screenshot_path = os.path.join(server.automator.screenshots_dir, filename)

        # Take the screenshot
        try:
            server.automator.driver.save_screenshot(screenshot_path)
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            failed = "Failed to take screenshot"

        # If save=1, return the URL to access the screenshot via the /image endpoint with POST method
        # Otherwise, return the image directly via GET method (which will delete it after serving)
        image_id = os.path.splitext(filename)[0]

        if not save and not include_xml:
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

            # Return URL to access the screenshot (POST method preserves the image)
            image_url = f"/image/{image_id}"
            response_data["screenshot_url"] = image_url

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

            # Return URL to image
            image_url = f"/image/{screenshot_id}"
            return {
                "success": True,
                "progress": progress,
                "screenshot_url": image_url,
            }, 200

        return {"error": "Navigation failed"}, 500

    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Handle navigation via GET requests, using default_action from endpoint config"""
        # For GET requests, use the default action configured for this endpoint
        if not self.default_action:
            return {"error": "This endpoint doesn't support GET requests"}, 400

        # Pass the default action to the post method to handle navigation
        return self.post(self.default_action)


class BookOpenResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Open a specific book."""
        data = request.get_json()
        book_title = data.get("title")

        logger.info(f"Opening book: {book_title}")

        if not book_title:
            return {"error": "Book title required"}, 400

        if server.automator.state_machine.transition_to_library():
            success = server.automator.reader_handler.open_book(book_title)
            logger.info(f"Book opened: {success}")

            if success:
                progress = server.automator.reader_handler.get_reading_progress()
                logger.info(f"Progress: {progress}")

                # Save screenshot with unique ID
                screenshot_id = f"page_{int(time.time())}"
                screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
                time.sleep(0.5)
                server.automator.driver.save_screenshot(screenshot_path)

                # Return URL to image
                image_url = f"/image/{screenshot_id}"
                return {"success": True, "progress": progress, "screenshot_url": image_url}, 200

        return {"error": "Failed to open book"}, 500


class StyleResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Update reading style settings"""
        data = request.get_json()
        settings = data.get("settings", {})
        dark_mode = data.get("dark-mode")

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

            # Return URL to image
            image_url = f"/image/{screenshot_id}"
            return {
                "success": True,
                "progress": progress,
                "screenshot_url": image_url,
            }, 200

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
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Authenticate with Amazon username and password"""
        data = request.get_json()
        email = data.get("email", AMAZON_EMAIL)  # Fall back to config email
        password = data.get("password", AMAZON_PASSWORD)  # Fall back to config password

        logger.info(f"Authenticating with email: {email}")

        if not email or not password:
            return {"error": "Email and password are required"}, 400

        # Check if already authenticated by checking if we're in the library state
        server.automator.state_machine.update_current_state()
        current_state = server.automator.state_machine.current_state

        if current_state == AppState.LIBRARY:
            logger.info("Already authenticated and in library state")
            return {"success": True, "message": "Already authenticated"}, 200

        # Update credentials if different from current ones
        if email != server.automator.email or password != server.automator.password:
            server.automator.email = email
            server.automator.password = password
            # Also update credentials in the state machine's auth handler
            server.automator.state_machine.auth_handler.email = email
            server.automator.state_machine.auth_handler.password = password

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
                image_url = f"/image/{screenshot_id}"

                # Update current state
                server.automator.state_machine.update_current_state()
                current_state = server.automator.state_machine.current_state

                return {
                    "success": False,
                    "message": (
                        f"Could not transition to authentication state, current state: {current_state.name}"
                    ),
                    "screenshot_url": image_url,
                }, 500

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

        # Take a screenshot for visual feedback (skip if we already know it's incorrect password)
        image_url = None
        if not incorrect_password:
            timestamp = int(time.time())
            screenshot_id = f"auth_screen_{timestamp}"
            screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")

            try:
                server.automator.driver.save_screenshot(screenshot_path)
                image_url = f"/image/{screenshot_id}"
                logger.info(f"Saved authentication screenshot to {screenshot_path}")
            except Exception as e:
                logger.warning(f"Failed to take authentication screenshot: {e}")
                # This is expected on secure screens like password entry

        # Check for authentication errors
        error_message = None
        try:
            # Check for error message box
            error_box = server.automator.driver.find_element(
                AppiumBy.XPATH, "//android.view.View[@resource-id='auth-error-message-box']"
            )
            if error_box:
                # Try to find specific error messages
                try:
                    error_elements = server.automator.driver.find_elements(
                        AppiumBy.XPATH,
                        "//android.view.View[@resource-id='auth-error-message-box']//android.view.View",
                    )
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
            return {"success": True, "message": "Authentication successful", "screenshot_url": image_url}, 200
        elif current_state == AppState.CAPTCHA:
            return {
                "success": False,
                "requires": "captcha",
                "message": "CAPTCHA required",
                "screenshot_url": image_url,
            }, 202
        elif (
            current_state == AppState.SIGN_IN
            and auth_result
            and len(auth_result) >= 1
            and auth_result[0] == LoginVerificationState.TWO_FACTOR
        ):
            return {
                "success": False,
                "requires": "2fa",
                "message": "2FA code required",
                "screenshot_url": image_url,
            }, 202
        else:
            # Return the specific error message if we found one
            if incorrect_password:
                # Special case for incorrect password - don't retry
                return {"success": False, "message": error_message, "error_type": "incorrect_password"}, 401
            elif error_message:
                response = {
                    "success": False,
                    "message": error_message,
                }
                if image_url:
                    response["screenshot_url"] = image_url
                return response, 401
            else:
                response = {
                    "success": False,
                    "message": f"Authentication failed, current state: {current_state.name}",
                }
                if image_url:
                    response["screenshot_url"] = image_url
                return response, 401


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


class ImageResource(Resource):
    def get(self, image_id):
        """Get an image by ID and delete it after serving."""
        return serve_image(image_id, delete_after=False)

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        return serve_image(image_id, delete_after=False)


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


def run_server():
    """Run the Flask server"""
    app.run(host="0.0.0.0", port=4098)


def main():
    # Kill any existing processes
    server.kill_existing_process("flask")
    server.kill_existing_process("appium")

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
