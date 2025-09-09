"""Main Kindle Automator server module."""

import json
import logging
import os
import platform
import signal
import subprocess
import time
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path

import sentry_sdk
from appium.webdriver.common.appiumby import AppiumBy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    make_response,
    request,
    send_file,
    send_from_directory,
)
from flask_restful import Api, Resource
from selenium.common import exceptions as selenium_exceptions
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from database.connection import db_connection
from handlers.navigation_handler import NavigationResourceHandler
from handlers.test_fixtures_handler import TestFixturesHandler
from server.core.automation_server import AutomationServer
from server.logging_config import setup_logger
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_logger import setup_request_logger
from server.middleware.response_handler import (
    get_image_path,
    handle_automator_response,
    serve_image,
)
from server.resources.active_emulators_resource import ActiveEmulatorsResource
from server.resources.dashboard_resource import DashboardResource
from server.resources.emulator_batch_config_resource import EmulatorBatchConfigResource
from server.utils.cover_utils import (
    add_cover_urls_to_books,
    extract_book_covers_from_screen,
)
from server.utils.ocr_utils import (
    KindleOCR,
    is_base64_requested,
    is_ocr_requested,
    process_screenshot_response,
)
from server.utils.request_utils import (
    get_automator_for_request,
    get_formatted_vnc_url,
    get_sindarin_email,
    get_vnc_and_websocket_urls,
    is_websockets_requested,
)
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


# Custom JSON encoder that can handle datetime objects
class DateTimeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


app = Flask(__name__)
app.json_encoder = DateTimeJSONEncoder

# Configure app to work behind proxy with /kindle prefix
app.config["APPLICATION_ROOT"] = "/kindle"
app.config["PREFERRED_URL_SCHEME"] = "http"

# Configure Flask-RESTful to use the custom encoder
from flask_restful.representations import json as flask_json


def output_json(data, code, headers=None):
    """Makes a Flask response with a JSON encoded body using custom encoder."""
    resp = make_response(json.dumps(data, cls=DateTimeJSONEncoder), code)
    resp.headers.extend(headers or {})
    resp.headers["Content-Type"] = "application/json"
    return resp


def output_xml(data, code, headers=None):
    """Pass through XML data without modification."""
    # If data is already a Flask response object with XML content type, return it as-is
    if hasattr(data, "headers") and "text/xml" in data.headers.get("Content-Type", ""):
        return data
    # Otherwise create XML response
    resp = make_response(data, code)
    resp.headers.extend(headers or {})
    resp.headers["Content-Type"] = "text/xml; charset=utf-8"
    return resp


api = Api(app)
api.representations = {"application/json": output_json, "text/xml": output_xml}

# Initialize database connection
db_connection.initialize()

# Initialize Flask-Admin (available in all environments with staff auth)
if os.getenv("ENABLE_ADMIN", "true").lower() == "true":
    from sqlalchemy.orm import scoped_session

    from server.admin import init_admin

    # Create a scoped session for Flask-Admin
    db_session = scoped_session(db_connection.SessionLocal)
    admin = init_admin(app, db_session)

    # Add routes to serve Flask-Admin static files both with and without /kindle prefix
    import os

    import flask_admin

    admin_static_path = os.path.join(os.path.dirname(flask_admin.__file__), "static")

    # Serve Flask-Admin static files
    @app.route("/admin/static/<path:path>")
    def admin_static(path):
        """Serve Flask-Admin static files."""
        return send_from_directory(admin_static_path, path)


# Initialize Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:

    def before_send(event, hint):
        """Filter out expected Appium/WebDriver errors from Sentry."""
        # Filter out duplicate "Error on request" messages from Flask-RESTful
        if "logentry" in event and "message" in event["logentry"]:
            message = event["logentry"]["message"]
            if message.startswith("Error on request:"):
                return None

        if "exc_info" in hint:
            exc_type, exc_value, tb = hint["exc_info"]
            from server.utils.appium_error_utils import is_appium_error

            # Don't send Appium errors to Sentry as they're expected and handled
            if is_appium_error(exc_value):
                return None

        return event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            FlaskIntegration(transaction_style="endpoint"),
            LoggingIntegration(
                level=logging.INFO,  # Capture info and above as breadcrumbs
                event_level=logging.ERROR,  # Send errors as events
            ),
        ],
        environment=ENVIRONMENT.lower(),
        traces_sample_rate=0.1 if ENVIRONMENT.lower() == "prod" else 1.0,
        before_send=before_send,
        send_default_pii=False,  # Don't send PII by default
    )
    logger.info(f"Sentry initialized for {ENVIRONMENT} environment")
else:
    logger.warning("SENTRY_DSN not found in environment variables - Sentry not initialized")

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
from server.resources.auth_check_resource import AuthCheckResource
from server.resources.auth_resource import AuthResource
from server.resources.book_open_resource import BookOpenResource
from server.resources.books_resources import BooksResource, BooksStreamResource
from server.resources.cold_storage_resources import (
    ColdStorageArchiveResource,
    ColdStorageRestoreResource,
    ColdStorageStatusResource,
)
from server.resources.fixtures_resource import FixturesResource
from server.resources.idle_check_resources import IdleCheckResource
from server.resources.image_resources import CoverImageResource, ImageResource
from server.resources.last_read_page_dialog_resource import LastReadPageDialogResource
from server.resources.log_timeline_resource import LogTimelineResource
from server.resources.logout_resource import LogoutResource
from server.resources.navigation_resource import NavigationResource
from server.resources.screenshot_resource import ScreenshotResource
from server.resources.sentry_debug_resource import SentryDebugResource
from server.resources.shutdown_resources import ShutdownResource
from server.resources.snapshot_check_resource import SnapshotCheckResource
from server.resources.staff_auth_resources import StaffAuthResource, StaffTokensResource
from server.resources.state_resource import StateResource
from server.resources.table_of_contents_resource import TableOfContentsResource
from server.resources.text_resource import TextResource
from server.resources.user_activity_resource import UserActivityResource

# Add resources to API
api.add_resource(StateResource, "/state")
api.add_resource(BooksResource, "/books")
api.add_resource(BooksStreamResource, "/books-stream")  # New streaming endpoint for books
api.add_resource(StaffAuthResource, "/staff-auth")
api.add_resource(StaffTokensResource, "/staff-tokens")
api.add_resource(ScreenshotResource, "/screenshot")
# General navigation endpoint with navigate parameter controlling direction
api.add_resource(NavigationResource, "/navigate")
# Specialized navigation endpoints as shortcuts
api.add_resource(
    NavigationResource,
    "/navigate-next",
    endpoint="navigate_next",
    resource_class_kwargs={"default_direction": 1},
)
api.add_resource(
    NavigationResource,
    "/navigate-previous",
    endpoint="navigate_previous",
    resource_class_kwargs={"default_direction": -1},
)

# Preview endpoints - redirecting to /navigate with preview parameters
api.add_resource(
    NavigationResource,
    "/preview-next",
    endpoint="preview_next",
    resource_class_kwargs={"default_direction": 0},  # navigate=0, preview=1 via query params
)
api.add_resource(
    NavigationResource,
    "/preview-previous",
    endpoint="preview_previous",
    resource_class_kwargs={"default_direction": 0},  # navigate=0, preview=-1 via query params
)

api.add_resource(BookOpenResource, "/open-book")
api.add_resource(TableOfContentsResource, "/table-of-contents")
api.add_resource(
    LogoutResource,
    "/logout",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(AuthResource, "/auth")
api.add_resource(AuthCheckResource, "/auth-check")
api.add_resource(
    SnapshotCheckResource,
    "/snapshot-check",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(FixturesResource, "/fixtures")
api.add_resource(ImageResource, "/image/<string:image_id>")
api.add_resource(CoverImageResource, "/covers/<string:email_slug>/<string:filename>")
api.add_resource(TextResource, "/text")
api.add_resource(LastReadPageDialogResource, "/last-read-page-dialog")
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
api.add_resource(DashboardResource, "/dashboard")
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
api.add_resource(SentryDebugResource, "/sentry-debug")


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
            logger.warning(f"Error restarting ADB server: {adb_e}", exc_info=True)


def run_idle_check():
    """Run idle check using the IdleCheckResource directly."""
    try:
        # Log health status before idle check
        logger.info("=== Periodic Health Check ===")
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            logger.info(
                f"System: CPU {cpu}%, Memory {mem.percent}% ({mem.used // 1024**3}GB/{mem.total // 1024**3}GB), Disk {disk.percent}%"
            )

            # Count running emulators
            from server.utils.android_path_utils import get_android_home, get_avd_dir
            from server.utils.emulator_launcher import EmulatorLauncher

            android_home = get_android_home()
            avd_dir = get_avd_dir()
            launcher = EmulatorLauncher(android_home, avd_dir, "x86_64")
            running_count = len(launcher.get_running_emulators())
            logger.info(f"Running emulators: {running_count}")
        except Exception as e:
            logger.debug(f"Could not log health status: {e}")

        # Clean up stale VNC instance records for crashed/killed emulators
        try:
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            vnc_manager.audit_and_cleanup_stale_instances()
        except Exception as e:
            logger.debug(f"Error during VNC instance cleanup: {e}")

        idle_check = IdleCheckResource(server_instance=server)
        result, status_code = idle_check.get()

        if status_code == 200:
            shut_down = result.get("shut_down", 0)
            active = result.get("active", 0)
            logger.info(f"Idle check complete: {shut_down} shut down, {active} active")
        else:
            logger.warning(f"Idle check failed with status {status_code}: {result}")
    except Exception as e:
        logger.warning(f"Error during scheduled idle check: {e}", exc_info=True)


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
        logger.warning(f"Error during scheduled cold storage check: {e}", exc_info=True)


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
            logger.warning(f"Error shutting down scheduler: {e}", exc_info=True)

    # Clean up any active WebSocket proxies
    try:
        from server.utils.websocket_proxy_manager import WebSocketProxyManager

        ws_manager = WebSocketProxyManager.get_instance()
        ws_manager.cleanup()
        logger.info("Successfully cleaned up WebSocket proxies")
    except Exception as e:
        logger.warning(f"Error cleaning up WebSocket proxies: {e}", exc_info=True)

    # Mark all running emulators for restart and shutdown gracefully with preserved state
    from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
    from server.utils.vnc_instance_manager import VNCInstanceManager

    vnc_manager = VNCInstanceManager.get_instance()

    shutdown_manager = EmulatorShutdownManager(server)

    # Track which emulators are running and mark them for restart
    running_emails = []
    logger.info(f"Checking {len(server.automators)} automators for running emulators...")

    # Create a list copy to avoid dictionary modification during iteration
    for email, automator in list(server.automators.items()):
        if automator and automator.emulator_manager.is_emulator_running(email):
            try:
                logger.info(f"✓ Marking {email} as running at restart for deployment recovery")
                vnc_manager.mark_running_for_deployment(email)
                running_emails.append(email)
            except Exception as e:
                logger.warning(f"✗ Error marking {email} for restart: {e}", exc_info=True)

    logger.info(f"Found {len(running_emails)} running emulators to preserve across restart")

    # Perform graceful shutdowns with preserved state
    for email in running_emails:
        try:
            logger.info(
                f"Gracefully shutting down {email} with preserve_reading_state=True, mark_for_restart=True"
            )
            shutdown_manager.shutdown_emulator(email, preserve_reading_state=True, mark_for_restart=True)
        except KeyError as e:
            logger.warning(f"✗ Error shutting down {email}: {e}", exc_info=True)

    # Stop Appium servers for all running emulators
    from server.utils.appium_driver import AppiumDriver

    appium_driver = AppiumDriver.get_instance()

    for email in running_emails:
        try:
            appium_driver.stop_appium_for_profile(email)
        except Exception as e:
            logger.warning(f"Error stopping Appium for {email} during shutdown: {e}", exc_info=True)

    # Kill any remaining Appium processes (legacy cleanup)
    try:
        server.kill_existing_process("appium")
    except Exception as e:
        logger.warning(f"Error killing remaining Appium processes: {e}", exc_info=True)

    # Port forwards are persistent and tied to instance IDs
    # We keep them in place for faster startup on next server start

    logger.info(f"Marked {len(running_emails)} emulators for restart on next boot")
    logger.info(f"=== Graceful shutdown complete ===")


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

    auto_restart_emulators_after_startup(server)

    # Initialize APScheduler for idle checks and cold storage
    scheduler = BackgroundScheduler(daemon=True)

    # Different idle check schedules for Mac vs Linux
    if platform.system() == "Darwin":
        # Mac: run twice a day at 6 AM and 6 PM
        idle_cron_trigger = CronTrigger(hour="6,18", minute=0)
        idle_schedule_desc = "twice daily at 6:00 AM and 6:00 PM"
    else:
        # Linux: run every 5 minutes
        idle_cron_trigger = CronTrigger(minute="*/5")
        idle_schedule_desc = "every 5 minutes"

    scheduler.add_job(
        func=run_idle_check,
        trigger=idle_cron_trigger,
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
    logger.info(f"Started APScheduler for idle checks ({idle_schedule_desc})")
    logger.info("Started APScheduler for cold storage checks (daily at 3:00 AM)")

    # Clear Redis deduplication keys after all initialization is complete
    from server.core.redis_connection import clear_deduplication_keys_on_startup

    clear_deduplication_keys_on_startup()

    # Run the server directly, regardless of development mode
    run_server()


if __name__ == "__main__":
    # If running in background, write PID to file before starting server
    if os.getenv("FLASK_ENV") == "development":
        with open(os.path.join("logs", "flask.pid"), "w") as f:
            f.write(str(os.getpid()))
    main()
