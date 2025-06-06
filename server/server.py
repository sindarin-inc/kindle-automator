"""Main Kindle Automator server module."""

import json
import logging
import os
import signal
import subprocess
import time
import traceback
import urllib.parse
from pathlib import Path

from appium.webdriver.common.appiumby import AppiumBy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from flask import Flask, Response, make_response, request, send_file
from flask_restful import Api, Resource
from selenium.common import exceptions as selenium_exceptions

from handlers.navigation_handler import NavigationResourceHandler
from handlers.test_fixtures_handler import TestFixturesHandler
from server.core.automation_server import AutomationServer
from server.logging_config import setup_logger
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_logger import setup_request_logger
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_sindarin_email
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

app = Flask(__name__)
# Configure Flask to allow optional trailing slashes
app.url_map.strict_slashes = False
api = Api(app)

# Set up request and response logging middleware
setup_request_logger(app)

# Disable Flask buffering to ensure SSE streaming works properly
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False
app.config["SERVER_SENT_EVENTS_PING_ACTIVE"] = True
app.config["SERVER_SENT_EVENTS_PING_INTERVAL"] = 15

# Configure Flask for SSE streaming
app.config.update(
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_SECURE=False,
    SESSION_USE_SIGNER=False,
)

# Create the server instance
server = AutomationServer()

# Store server instance in app config for access in middleware
app.config["server_instance"] = server


# Import resource modules
from server.resources.active_emulators_resource import ActiveEmulatorsResource
from server.resources.auth_check_resource import AuthCheckResource
from server.resources.auth_resource import AuthResource
from server.resources.book_open_resource import BookOpenResource
from server.resources.books_resource import BooksResource
from server.resources.books_stream_resource import BooksStreamResource
from server.resources.cold_storage_resources import (
    ColdStorageArchiveResource,
    ColdStorageRestoreResource,
    ColdStorageStatusResource,
)
from server.resources.cover_image_resource import CoverImageResource
from server.resources.emulator_batch_config_resource import EmulatorBatchConfigResource
from server.resources.fixtures_resource import FixturesResource
from server.resources.idle_check_resources import IdleCheckResource
from server.resources.image_resource import ImageResource
from server.resources.last_read_page_dialog_resource import LastReadPageDialogResource
from server.resources.log_timeline_resource import LogTimelineResource
from server.resources.logout_resource import LogoutResource
from server.resources.navigation_resource import NavigationResource
from server.resources.screenshot_resource import ScreenshotResource
from server.resources.shutdown_resources import ShutdownResource
from server.resources.staff_auth_resources import StaffAuthResource, StaffTokensResource
from server.resources.state_resource import StateResource
from server.resources.text_resource import TextResource
from server.resources.user_activity_resource import UserActivityResource

# Add resources to API
api.add_resource(StateResource, "/state", resource_class_kwargs={"server_instance": server})
api.add_resource(BooksResource, "/books", resource_class_kwargs={"server_instance": server})
api.add_resource(
    BooksStreamResource, "/books-stream", resource_class_kwargs={"server_instance": server}
)  # New streaming endpoint for books
api.add_resource(StaffAuthResource, "/staff-auth")
api.add_resource(StaffTokensResource, "/staff-tokens")
api.add_resource(ScreenshotResource, "/screenshot", resource_class_kwargs={"server_instance": server})
# General navigation endpoint with navigate parameter controlling direction
api.add_resource(NavigationResource, "/navigate", resource_class_kwargs={"server_instance": server})
# Specialized navigation endpoints as shortcuts
api.add_resource(
    NavigationResource,
    "/navigate-next",
    endpoint="navigate_next",
    resource_class_kwargs={"server_instance": server, "default_direction": 1},
)
api.add_resource(
    NavigationResource,
    "/navigate-previous",
    endpoint="navigate_previous",
    resource_class_kwargs={"server_instance": server, "default_direction": -1},
)

# Preview endpoints - redirecting to /navigate with preview parameters
api.add_resource(
    NavigationResource,
    "/preview-next",
    endpoint="preview_next",
    resource_class_kwargs={
        "server_instance": server,
        "default_direction": 0,
    },  # navigate=0, preview=1 via query params
)
api.add_resource(
    NavigationResource,
    "/preview-previous",
    endpoint="preview_previous",
    resource_class_kwargs={
        "server_instance": server,
        "default_direction": 0,
    },  # navigate=0, preview=-1 via query params
)

api.add_resource(BookOpenResource, "/open-book", resource_class_kwargs={"server_instance": server})
api.add_resource(
    LogoutResource,
    "/logout",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(AuthResource, "/auth", resource_class_kwargs={"server_instance": server})
api.add_resource(AuthCheckResource, "/auth-check")
api.add_resource(FixturesResource, "/fixtures", resource_class_kwargs={"server_instance": server})
api.add_resource(ImageResource, "/image/<string:image_id>")
api.add_resource(CoverImageResource, "/covers/<string:email_slug>/<string:filename>")
api.add_resource(TextResource, "/text", resource_class_kwargs={"server_instance": server})
api.add_resource(
    LastReadPageDialogResource, "/last-read-page-dialog", resource_class_kwargs={"server_instance": server}
)
api.add_resource(
    ShutdownResource,
    "/shutdown",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    IdleCheckResource,
    "/idle-check",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    ActiveEmulatorsResource,
    "/emulators/active",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    EmulatorBatchConfigResource,
    "/batch-configure-emulators",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    ColdStorageArchiveResource,
    "/cold-storage/archive",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    ColdStorageStatusResource,
    "/cold-storage/status",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    ColdStorageRestoreResource,
    "/cold-storage/restore",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(
    LogTimelineResource,
    "/logs/timeline",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(UserActivityResource, "/log")


def check_and_restart_adb_server():
    """
    Check ADB connectivity and restart the server if it's not responsive.
    This preserves existing emulators while ensuring ADB is functional.
    """
    try:
        # Just check device status to make sure ADB is responsive
        subprocess.run(
            [f"{server.android_home}/platform-tools/adb", "devices"],
            check=False,
            timeout=5,
            capture_output=True,
        )
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


def run_idle_check():
    """Run idle check using the IdleCheckResource directly."""
    try:
        idle_check = IdleCheckResource(server_instance=server)
        result, status_code = idle_check.get()

        if status_code == 200:
            shut_down = result.get("shut_down", 0)
            active = result.get("active", 0)
        else:
            logger.error(f"Idle check failed with status {status_code}: {result}")
    except Exception as e:
        logger.error(f"Error during scheduled idle check: {e}")


def run_cold_storage_check():
    """Run cold storage archival check for profiles inactive for 30+ days."""
    try:
        logger.info("Running scheduled cold storage check...")
        from server.utils.cold_storage_manager import ColdStorageManager

        cold_storage_manager = ColdStorageManager.get_instance()
        success_count, failure_count, storage_info = cold_storage_manager.archive_eligible_profiles(
            days_inactive=30
        )

        logger.info(f"Cold storage check completed: {success_count} archived, {failure_count} failed")
        if storage_info and storage_info.get("total_space_saved", 0) > 0:
            logger.info(f"Total space saved: {storage_info['total_space_saved_human']}")
    except Exception as e:
        logger.error(f"Error during scheduled cold storage check: {e}")


def cleanup_resources():
    """Clean up resources before exiting"""
    logger.info("=== Beginning graceful shutdown sequence ===")
    logger.info("Cleaning up resources before shutdown...")

    # Shutdown the scheduler if it exists
    if hasattr(app, "scheduler") and app.scheduler:
        try:
            logger.info("Shutting down APScheduler...")
            app.scheduler.shutdown(wait=False)
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")

    # Clean up any active WebSocket proxies
    try:
        from server.utils.websocket_proxy_manager import WebSocketProxyManager

        ws_manager = WebSocketProxyManager.get_instance()
        ws_manager.cleanup()
        logger.info("Successfully cleaned up WebSocket proxies")
    except Exception as e:
        logger.error(f"Error cleaning up WebSocket proxies: {e}")

    # Mark all running emulators for restart and shutdown gracefully with preserved state
    from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
    from server.utils.vnc_instance_manager import VNCInstanceManager

    vnc_manager = VNCInstanceManager.get_instance()

    shutdown_manager = EmulatorShutdownManager(server)

    # Track which emulators are running and mark them for restart
    running_emails = []
    logger.info(f"Checking {len(server.automators)} automators for running emulators...")

    for email, automator in server.automators.items():
        if automator.emulator_manager.is_emulator_running(email):
            try:
                logger.info(f"✓ Marking {email} as running at restart for deployment recovery")
                vnc_manager.mark_running_for_deployment(email)
                running_emails.append(email)
            except Exception as e:
                logger.error(f"✗ Error marking {email} for restart: {e}")

    logger.info(f"Found {len(running_emails)} running emulators to preserve across restart")

    # Perform graceful shutdowns with preserved state
    for email in running_emails:
        try:
            logger.info(
                f"Gracefully shutting down {email} with preserve_reading_state=True, mark_for_restart=True"
            )
            shutdown_manager.shutdown_emulator(email, preserve_reading_state=True, mark_for_restart=True)
        except KeyError as e:
            logger.error(f"✗ Error shutting down {email}: {e}")

    # Stop Appium servers for all running emulators
    from server.utils.appium_driver import AppiumDriver

    appium_driver = AppiumDriver.get_instance()

    for email in running_emails:
        try:
            logger.info(f"Stopping Appium server for {email}")
            appium_driver.stop_appium_for_profile(email)
        except Exception as e:
            logger.error(f"Error stopping Appium for {email} during shutdown: {e}")

    # Kill any remaining Appium processes (legacy cleanup)
    try:
        logger.info("Cleaning up any remaining Appium processes")
        server.kill_existing_process("appium")
    except Exception as e:
        logger.error(f"Error killing remaining Appium processes: {e}")

    # Clean up ADB port forwards to prevent port conflicts on restart
    logger.info("Cleaning up ADB port forwards")
    try:
        # Get all connected devices
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")[1:]  # Skip header
        for line in lines:
            if "\tdevice" in line:
                device_id = line.split("\t")[0]
                logger.info(f"Removing port forwards for device {device_id}")
                subprocess.run([f"adb -s {device_id} forward --remove-all"], shell=True, check=False)
    except Exception as e:
        logger.warning(f"Error cleaning up ADB port forwards: {e}")

    logger.info(f"=== Graceful shutdown complete ===")
    logger.info(f"Marked {len(running_emails)} emulators for restart on next boot")


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

    # Run with threaded=True and explicit buffering settings to ensure streaming works
    app.run(host="0.0.0.0", port=4098, threaded=True, use_reloader=False)


def main():
    # Kill any Flask processes on the same port (but leave Appium servers alone)
    server.kill_existing_process("flask")

    # Reset any lingering appium states from a previous run
    from server.utils.vnc_instance_manager import VNCInstanceManager

    vnc_manager = VNCInstanceManager.get_instance()
    logger.info("Resetting appium states from previous run...")
    vnc_manager.reset_appium_states_on_startup()

    # Check ADB connectivity
    check_and_restart_adb_server()

    # Save Flask server PID
    server.save_pid("flask", os.getpid())

    # Schedule emulator restart after server is ready using background thread
    from server.utils.server_startup_utils import auto_restart_emulators_after_startup

    auto_restart_emulators_after_startup(server, delay=3.0)

    # Initialize APScheduler for idle checks and cold storage
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=run_idle_check,
        trigger=CronTrigger(minute="0,15,30,45"),
        id="idle_check",
        name="Idle Emulator Check",
        replace_existing=True,
    )
    # Add cold storage check - runs daily at 3 AM
    scheduler.add_job(
        func=run_cold_storage_check,
        trigger=CronTrigger(hour=3, minute=0),
        id="cold_storage_check",
        name="Cold Storage Archival Check",
        replace_existing=True,
    )
    scheduler.start()
    app.scheduler = scheduler
    logger.info("Started APScheduler for idle checks (at :00, :15, :30, :45 each hour)")
    logger.info("Started APScheduler for cold storage checks (daily at 3:00 AM)")

    # Run the server directly, regardless of development mode
    run_server()


if __name__ == "__main__":
    # If running in background, write PID to file before starting server
    if os.getenv("FLASK_ENV") == "development":
        with open(os.path.join("logs", "flask.pid"), "w") as f:
            f.write(str(os.getpid()))
    main()
