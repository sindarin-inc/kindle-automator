import os
import signal
import subprocess
import logging
from flask import Flask, request, jsonify, send_file
from flask_restful import Api, Resource
from typing import Optional
import json

from automator import KindleAutomator

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/server.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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


class StateResource(Resource):
    def get(self):
        if not server.automator:
            return {"error": "Automator not initialized"}, 400

        try:
            current_state = server.automator.state_machine.current_state
            return {"state": current_state.name}, 200
        except Exception as e:
            logger.error(f"Error getting state: {e}")
            return {"error": str(e)}, 500


class CaptchaResource(Resource):
    def get(self):
        """Get captcha image"""
        try:
            return send_file("captcha.png", mimetype="image/png")
        except Exception as e:
            return {"error": str(e)}, 500

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
            return {"error": str(e)}, 500


class BooksResource(Resource):
    def get(self):
        """Get list of available books"""
        try:
            if not server.automator or not server.automator.library_handler:
                return {"error": "Automator not initialized"}, 400

            books = server.automator.library_handler.get_book_titles()
            return {"books": books}, 200
        except Exception as e:
            return {"error": str(e)}, 500


# Add resources to API
api.add_resource(InitializeResource, "/initialize")
api.add_resource(StateResource, "/state")
api.add_resource(CaptchaResource, "/captcha")
api.add_resource(BooksResource, "/books")


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
