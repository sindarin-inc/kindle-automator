import traceback
import os
import signal
import subprocess
import logging
from flask import Flask, request, jsonify, send_file
from flask_restful import Api, Resource
from typing import Optional
import json
from PIL import Image
from io import BytesIO
import base64

from automator import KindleAutomator

# Setup logging
os.makedirs("logs", exist_ok=True)

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create formatters and handlers
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# File handler
file_handler = logging.FileHandler("logs/server.log")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

app = Flask(__name__)
api = Api(app)


class AutomationServer:
    def __init__(self):
        self.automator: Optional[KindleAutomator] = None
        self.appium_process = None
        self.pid_dir = "logs"
        os.makedirs(self.pid_dir, exist_ok=True)

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        with open(os.path.join(self.pid_dir, f"{name}.pid"), "w") as f:
            f.write(str(pid))

    def kill_existing_process(self, name: str):
        """Kill existing process if PID file exists"""
        pid_file = os.path.join(self.pid_dir, f"{name}.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Killed existing {name} process with PID {pid}")
            except ProcessLookupError:
                logger.info(f"No existing {name} process found")
            except Exception as e:
                logger.error(f"Error killing {name} process: {e}")
            finally:
                os.remove(pid_file)

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
            email = data.get("email")
            password = data.get("password")

            if not email or not password:
                return {"error": "Email and password are required"}, 400

            server.automator = KindleAutomator(email, password, None)
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
        if not server.automator:
            return {"error": "Automator not initialized"}, 400
        if not server.automator.ensure_driver_running():
            return {"error": "Failed to ensure driver is running"}, 500
        return f(*args, **kwargs)

    return wrapper


class StateResource(Resource):
    @ensure_automator_healthy
    def get(self):
        try:
            current_state = server.automator.state_machine.current_state
            return {"state": current_state.name}, 200
        except Exception as e:
            logger.error(f"Error getting state: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class CaptchaResource(Resource):
    def get(self):
        """Get captcha image"""
        try:
            return send_file("captcha.png", mimetype="image/png")
        except Exception as e:
            logger.error(f"Captcha error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500

    @ensure_automator_healthy
    def post(self):
        """Submit captcha solution"""
        try:
            data = request.get_json()
            solution = data.get("solution")
            if not solution:
                return {"error": "Captcha solution required"}, 400

            server.automator.captcha_solution = solution
            success = server.automator.handle_initial_setup()
            return {"success": success}, 200 if success else 500
        except Exception as e:
            logger.error(f"Captcha error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class BooksResource(Resource):
    @ensure_automator_healthy
    def get(self):
        """Get list of available books"""
        try:
            # Get book titles from library handler
            book_titles = server.automator.library_handler.get_book_titles()

            if book_titles is None:
                return {"error": "Failed to get book titles"}, 500

            if not book_titles:
                logger.warning("No books found in library")

            # Return in same format as automator
            return {"book_titles": book_titles}, 200

        except Exception as e:
            logger.error(f"Error getting books: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class ScreenshotResource(Resource):
    @ensure_automator_healthy
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
    def post(self):
        """Handle page navigation"""
        try:
            data = request.get_json()
            action = data.get("action")

            if action == "next_page":
                success = server.automator.reader_handler.turn_page_forward()
            elif action == "prev_page":
                success = server.automator.reader_handler.turn_page_backward()
            else:
                return {"error": "Invalid action"}, 400

            if success:
                # Get current page number after navigation
                page_number = server.automator.reader_handler.get_current_page()
                return {"success": True, "page": page_number}, 200
            return {"error": "Navigation failed"}, 500

        except Exception as e:
            logger.error(f"Navigation error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class BookOpenResource(Resource):
    @ensure_automator_healthy
    def post(self):
        """Open a specific book"""
        try:
            data = request.get_json()
            book_title = data.get("title")

            if not book_title:
                return {"error": "Book title required"}, 400

            success, page = server.automator.run(reading_book_title=book_title)
            if success:
                return {"success": True, "page": page}, 200
            return {"error": "Failed to open book"}, 500

        except Exception as e:
            logger.error(f"Error opening book: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class StyleResource(Resource):
    @ensure_automator_healthy
    def post(self):
        """Update reading style settings"""
        try:
            data = request.get_json()
            settings = data.get("settings", {})

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
    def post(self):
        """Submit 2FA code"""
        try:
            data = request.get_json()
            code = data.get("code")

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

    # Start Flask server
    app.run(host="0.0.0.0", port=4098)


if __name__ == "__main__":
    main()
