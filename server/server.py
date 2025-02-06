import base64
import logging
import os
import signal
import subprocess
import time
import traceback
from typing import Optional

from flask import Flask, request, send_file
from flask_restful import Api, Resource

from automator import KindleAutomator
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
        try:
            if not server.automator:
                logger.info("No automator found, initializing...")
                server.initialize_automator()
                if not server.automator.initialize_driver():
                    return {"error": "Failed to initialize driver"}, 500

            if not server.automator.ensure_driver_running():
                return {"error": "Failed to ensure driver is running"}, 500

            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in automator health check: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    return wrapper


class StateResource(Resource):
    @ensure_automator_healthy
    def get(self):
        try:
            logger.info(f"Getting state: {server.automator.state_machine.current_state}")
            current_state = server.automator.state_machine.current_state
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
        try:
            # Return simple success response - the response handler will
            # intercept if we're in CAPTCHA state
            return {"status": "no_captcha"}, 200
        except Exception as e:
            logger.error(f"Error checking captcha: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Submit captcha solution"""
        try:
            data = request.get_json()
            solution = data.get("solution")

            if not solution:
                return {"error": "Captcha solution required"}, 400

            # Update captcha solution if different
            server.automator.update_captcha_solution(solution)
            success = server.automator.transition_to_library()

            if success:
                return {"status": "success"}, 200
            return {"error": "Failed to process captcha solution"}, 500

        except Exception as e:
            logger.error(f"Error submitting captcha: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class BooksResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def _get_books(self):
        """Get list of available books with metadata"""
        try:
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

        except Exception as e:
            logger.error(f"Error getting books: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    def get(self):
        """Handle GET request for books list"""
        return self._get_books()

    def post(self):
        """Handle POST request for books list"""
        return self._get_books()


class ScreenshotResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def get(self):
        """Get current page screenshot"""
        try:
            screenshot_path = os.path.join(server.automator.screenshots_dir, "current_screen.png")
            server.automator.driver.save_screenshot(screenshot_path)

            # Convert to base64 for response
            with open(screenshot_path, "rb") as img_file:
                img_data = base64.b64encode(img_file.read()).decode()

            return {"screenshot": img_data}, 200
        except Exception as e:
            logger.error(f"Error getting screenshot: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class NavigationResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Handle page navigation"""
        try:
            data = request.get_json()
            action = data.get("action")

            if action == "next_page":
                success = server.automator.reader_handler.turn_page_forward()
            elif action == "previous_page":
                success = server.automator.reader_handler.turn_page_backward()
            else:
                return {"error": "Invalid action"}, 400

            if success:
                # Save screenshot with unique ID
                screenshot_id = f"page_{int(time.time())}"
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

            return {"error": "Navigation failed"}, 500

        except Exception as e:
            logger.error(f"Navigation error: {e}")
            return {"error": str(e)}, 500


class BookOpenResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Open a specific book."""
        try:
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
                    screenshot_id = f"book_page_{int(time.time())}"
                    screenshot_path = os.path.join(server.automator.screenshots_dir, f"{screenshot_id}.png")
                    server.automator.driver.save_screenshot(screenshot_path)

                    # Return URL to image
                    image_url = f"/image/{screenshot_id}"
                    return {"success": True, "progress": progress, "screenshot_url": image_url}, 200

            return {"error": "Failed to open book"}, 500

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error opening book: {e}")
            return {"error": str(e)}, 500


class StyleResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Update reading style settings"""
        try:
            data = request.get_json()
            settings = data.get("settings", {})

            logger.info(f"Updating style settings: {settings}")

            # Example settings: font_size, brightness, background_color
            success = server.automator.reader_handler.update_style_settings(settings)

            if success:
                return {"success": True}, 200
            return {"error": "Failed to update settings"}, 500

        except Exception as e:
            logger.error(f"Error updating style: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class TwoFactorResource(Resource):
    @ensure_automator_healthy
    @handle_automator_response(server)
    def post(self):
        """Submit 2FA code"""
        try:
            data = request.get_json()
            code = data.get("code")

            logger.info(f"Submitting 2FA code: {code}")

            if not code:
                return {"error": "2FA code required"}, 400

            success = server.automator.auth_handler.handle_2fa(code)
            if success:
                return {"success": True}, 200
            return {"error": "Invalid 2FA code"}, 500

        except Exception as e:
            logger.error(f"2FA error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


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


class ImageResource(Resource):
    def _get_image_path(self, image_id):
        """Get full path for an image file."""
        # Build path to image using project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Ensure .png extension
        if not image_id.endswith(".png"):
            image_id = f"{image_id}.png"

        return os.path.join(project_root, "screenshots", image_id)

    def get(self, image_id):
        """Get an image by ID and delete it after serving."""
        try:
            image_path = self._get_image_path(image_id)

            if not os.path.exists(image_path):
                logger.error(f"Image not found at path: {image_path}")
                return {"error": "Image not found"}, 404

            # Return the image file
            response = send_file(image_path, mimetype="image/png")

            # Delete the file after sending
            try:
                os.remove(image_path)
                logger.info(f"Deleted image: {image_path}")
            except Exception as e:
                logger.error(f"Failed to delete image {image_path}: {e}")

            return response

        except Exception as e:
            logger.error(f"Error serving image: {e}")
            return {"error": str(e)}, 500

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        try:
            image_path = self._get_image_path(image_id)

            if not os.path.exists(image_path):
                logger.error(f"Image not found at path: {image_path}")
                return {"error": "Image not found"}, 404

            # Return the image file without deleting
            return send_file(image_path, mimetype="image/png")

        except Exception as e:
            logger.error(f"Error serving image: {e}")
            return {"error": str(e)}, 500


# Add resources to API
api.add_resource(InitializeResource, "/initialize")
api.add_resource(StateResource, "/state")
api.add_resource(CaptchaResource, "/captcha")
api.add_resource(BooksResource, "/books")
api.add_resource(ScreenshotResource, "/screenshot")
api.add_resource(NavigationResource, "/navigate")
api.add_resource(BookOpenResource, "/open-book")
api.add_resource(StyleResource, "/style")
api.add_resource(TwoFactorResource, "/2fa")
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
