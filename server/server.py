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
from server.middleware.response_handler import (
    get_image_path,
    handle_automator_response,
    serve_image,
)
from server.resources.active_emulators_resource import ActiveEmulatorsResource
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

app = Flask(__name__)
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


class StateResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        try:
            automator, _, error_response = get_automator_for_request(server)
            if error_response:
                return error_response

            # Update the current state before returning it to ensure it's not stale
            current_state = automator.state_machine.update_current_state()
            return {"state": current_state.name}, 200
        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error getting state: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class BooksResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _get_books(self):
        """Get list of available books with metadata"""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.error("No email provided to identify which profile to use")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            logger.error(f"No automator found for {sindarin_email}")
            return {"error": f"No automator found for {sindarin_email}"}, 404

        current_state = automator.state_machine.current_state
        logger.info(f"Current state when getting books: {current_state}")

        # Handle different states
        if current_state != AppState.LIBRARY:
            # Check if we're on the sign-in screen
            if current_state == AppState.SIGN_IN or current_state == AppState.LIBRARY_SIGN_IN:
                # Get current email to include in VNC URL
                sindarin_email = get_sindarin_email()

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
            transition_success = automator.state_machine.transition_to_library(server=server)

            # Get the updated state after transition attempt
            new_state = automator.state_machine.current_state
            logger.info(f"State after transition attempt: {new_state}")

            # Check for auth requirement regardless of transition success
            if new_state == AppState.SIGN_IN:
                # Get current email to include in VNC URL
                sindarin_email = get_sindarin_email()

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
                # Get books with metadata from state machine's library handler
                books = automator.state_machine.library_handler.get_book_titles()

                # If books is None, it means authentication is required
                if books is None:
                    # Get current email to include in VNC URL
                    sindarin_email = get_sindarin_email()

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
                updated_state = automator.state_machine.current_state

                if updated_state == AppState.SIGN_IN:
                    # Get current email to include in VNC URL
                    sindarin_email = get_sindarin_email()

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

        # Get books with metadata from state machine's library handler
        books = automator.state_machine.library_handler.get_book_titles()

        # If books is None, it means authentication is required
        if books is None:
            # Get current email to include in VNC URL
            sindarin_email = get_sindarin_email()

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

            logger.info("Authentication required - providing VNC URL for manual authentication")
            return {
                "error": "Authentication required",
                "requires_auth": True,
                "message": "Authentication is required via VNC",
                "emulator_id": emulator_id,
            }, 401

        # Take a screenshot to use for extracting book covers
        timestamp = int(time.time())
        screenshot_filename = f"library_view_{timestamp}.png"
        screenshot_path = os.path.join(automator.screenshots_dir, screenshot_filename)
        automator.driver.save_screenshot(screenshot_path)

        # Extract book covers using the simplified utility function
        try:
            # Extract covers from the current screen and get list of successful extractions
            cover_info_dict = extract_book_covers_from_screen(
                automator.driver, books, sindarin_email, screenshot_path
            )

            num_successful_covers = sum(1 for info in cover_info_dict.values() if info.get("success"))
            logger.info(f"Successfully processed {num_successful_covers} book covers")

            # Add cover URLs only for books with successfully extracted covers
            books = add_cover_urls_to_books(books, cover_info_dict, sindarin_email)
        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error extracting book covers: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

        return {"books": books}, 200

    def get(self):
        """Handle GET request for books list"""
        return self._get_books()

    def post(self):
        """Handle POST request for books list"""
        return self._get_books()


class BooksStreamResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """Stream book results as they're found using Flask streaming"""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.error("No email provided to identify which profile to use")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            logger.error(f"No automator found for {sindarin_email}")
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Update current state since middleware no longer does it
        current_state = automator.state_machine.update_current_state()
        logger.info(f"Current state for books-stream: {current_state}")

        # Handle different states - similar to _get_books but with appropriate streaming responses
        if current_state != AppState.LIBRARY:
            # Check if we're on the sign-in screen
            if current_state == AppState.SIGN_IN or current_state == AppState.LIBRARY_SIGN_IN:
                # Get current email to include in VNC URL
                emulator_id = None
                if (
                    automator
                    and hasattr(automator, "emulator_manager")
                    and hasattr(automator.emulator_manager, "emulator_launcher")
                ):
                    emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(sindarin_email)
                    logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

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
            transition_success = automator.state_machine.transition_to_library(server=server)

            # Get the updated state after transition attempt
            new_state = automator.state_machine.current_state
            logger.info(f"State after transition attempt: {new_state}")

            # Check for auth requirement regardless of transition success
            if new_state == AppState.SIGN_IN:
                # Get the emulator ID for this email if possible
                emulator_id = None
                if (
                    automator
                    and hasattr(automator, "emulator_manager")
                    and hasattr(automator.emulator_manager, "emulator_launcher")
                ):
                    emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(sindarin_email)
                    logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                logger.info("Authentication required after transition attempt - providing VNC URL")
                return {
                    "error": "Authentication required",
                    "requires_auth": True,
                    "current_state": new_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            if not transition_success:
                # If transition failed, check for auth requirement
                updated_state = automator.state_machine.current_state

                if updated_state == AppState.SIGN_IN:
                    # Get the emulator ID for this email if possible
                    emulator_id = None
                    if (
                        automator
                        and hasattr(automator, "emulator_manager")
                        and hasattr(automator.emulator_manager, "emulator_launcher")
                    ):
                        emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                            sindarin_email
                        )
                        logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

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
                        "error": f"Cannot stream books in current state: {updated_state.name}",
                        "current_state": updated_state.name,
                    }, 400

        def generate_simple_stream():
            """Simple test generator that doesn't depend on book retrieval"""
            # Send initial message
            logger.info("Starting simple test stream")
            yield (json.dumps({"status": "test_started"}) + "\n").encode("utf-8")

            # Send 10 test messages with forced flush
            for i in range(10):
                logger.info(f"Generating test message {i}")
                message = (
                    json.dumps({"test_message": f"Message {i}", "timestamp": time.time()}) + "\n"
                ).encode("utf-8")
                yield message
                time.sleep(1)  # Force a delay

            # Send completion message
            logger.info("Finishing test stream")
            yield (json.dumps({"test_complete": True}) + "\n").encode("utf-8")

        # If using test mode, just return a simple streaming test
        if request.args.get("test") == "1":
            # Return simple test stream
            logger.info("Using test stream mode")
            return Response(
                generate_simple_stream(),
                mimetype="text/plain",
                direct_passthrough=True,
                headers={
                    "X-Accel-Buffering": "no",
                    "Cache-Control": "no-cache, no-transform",
                    "Transfer-Encoding": "chunked",
                },
            )

        # Extract sync parameter
        sync = request.args.get("sync", "false").lower() in ("true", "1")
        logger.info(f"Sync parameter: {sync}")

        # Standard implementation with book retrieval
        def generate_stream():
            import json
            import queue  # For thread-safe communication
            import sys
            import threading

            # Event for signaling all books are retrieved by the library_handler
            all_books_retrieved_event = threading.Event()

            # Thread-safe queue for processed book batches
            processed_books_queue = queue.Queue()

            # Shared variables for status
            error_message = None
            total_books_from_handler = 0  # To store the total count from library_handler
            successful_covers_accumulator = {}  # Accumulate all successful covers (now a dict)

            # Callback function that will receive raw books_batch from the library handler
            # This callback will process books synchronously (screenshot, covers) for the current stable view
            def book_processing_callback(raw_books_batch, **kwargs):
                nonlocal error_message, total_books_from_handler, successful_covers_accumulator

                if kwargs.get("error"):
                    logger.info(f"Callback received error: {kwargs.get('error')}")
                    error_message = kwargs.get("error")
                    all_books_retrieved_event.set()  # Signal to stop generate_stream loop
                    return

                if kwargs.get("done"):
                    total_books_from_handler = kwargs.get("total_books", 0)
                    all_books_retrieved_event.set()  # Signal completion of book retrieval
                    return

                if raw_books_batch:
                    try:
                        # At this point, the UI should be stable for raw_books_batch
                        timestamp = int(time.time())
                        screenshot_filename = f"library_view_stream_{timestamp}.png"
                        screenshot_path = os.path.join(automator.screenshots_dir, screenshot_filename)
                        logger.info(f"Taking screenshot for batch: {screenshot_path}")
                        automator.driver.save_screenshot(screenshot_path)

                        # Extract covers from the current screen for this batch
                        logger.info("Extracting covers for the current batch.")
                        cover_info_for_batch = extract_book_covers_from_screen(
                            automator.driver, raw_books_batch, sindarin_email, screenshot_path
                        )
                        successful_covers_accumulator.update(cover_info_for_batch)  # Merge dicts

                        # Add cover URLs using all accumulated successful covers
                        processed_batch_with_covers = add_cover_urls_to_books(
                            raw_books_batch, successful_covers_accumulator, sindarin_email
                        )
                        processed_books_queue.put(processed_batch_with_covers)

                    except Exception as e:
                        from server.utils.appium_error_utils import is_appium_error

                        if is_appium_error(e):
                            raise
                        logger.error(f"Error processing book batch in callback: {e}")
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        # This error is for a single batch; retrieval might continue for others.
                        # The main error_message is for fatal errors in the retrieval thread itself.
                else:
                    logger.info("Callback received an empty books_batch or no batch.")

            # Thread to run the library_handler's book retrieval
            def start_book_retrieval_thread_fn():
                # Set email context for this background thread
                from server.logging_config import clear_email_context, set_email_context

                set_email_context(sindarin_email)
                try:
                    logger.info(
                        f"Starting book retrieval with processing callback in a new thread (sync={sync})."
                    )
                    automator.state_machine.library_handler.get_book_titles(
                        callback=book_processing_callback, sync=sync
                    )
                    logger.info("Book retrieval process (get_book_titles) completed in its thread.")
                except Exception as e:
                    from server.utils.appium_error_utils import is_appium_error

                    if is_appium_error(e):
                        raise
                    logger.error(f"Error in book retrieval thread (start_book_retrieval_thread_fn): {e}")
                    nonlocal error_message  # To set the shared error_message
                    error_message = str(e)
                    # Ensure the main loop knows about this fatal error and can terminate
                    if not all_books_retrieved_event.is_set():
                        all_books_retrieved_event.set()
                finally:
                    # Clear email context when thread completes
                    clear_email_context()

            retrieval_thread = threading.Thread(target=start_book_retrieval_thread_fn, daemon=True)
            retrieval_thread.start()
            logger.info("Book retrieval and processing thread started.")

            # Generator part for SSE (runs in Flask worker thread)
            try:

                def encode_message(msg_dict):
                    return (json.dumps(msg_dict) + "\n").encode("utf-8")

                yield encode_message(
                    {"status": "started", "message": "Book retrieval and processing initiated"}
                )

                batch_num_sent = 0
                while True:
                    if error_message:
                        logger.info(f"Error signaled: {error_message}. Yielding error.")
                        yield encode_message({"error": error_message})
                        break

                    try:
                        # Get processed batch from queue with a timeout
                        processed_batch = processed_books_queue.get(
                            timeout=0.2
                        )  # Small timeout to remain responsive
                        if processed_batch:
                            batch_num_sent += 1
                            yield encode_message({"books": processed_batch, "batch_num": batch_num_sent})
                        # No task_done needed for queue.Queue if not using join()
                    except queue.Empty:
                        # Queue is empty, check if book retrieval is done
                        if all_books_retrieved_event.is_set():
                            break
                        # else: continue polling, the event wasn't set yet.
                    except Exception as e:
                        from server.utils.appium_error_utils import is_appium_error

                        if is_appium_error(e):
                            raise
                        logger.error(f"Unexpected error in generate_stream while getting from queue: {e}")
                        yield encode_message({"error": f"Streaming error: {str(e)}"})  # Send error to client
                        break  # Terminate stream on unexpected errors

                # After the loop, if no error was yielded from inside the loop
                if not error_message:
                    logger.info(
                        f"Stream finished. Total books expected from handler: {total_books_from_handler}."
                    )
                    yield encode_message({"done": True, "total_books": total_books_from_handler})

                yield encode_message({"complete": True})
                logger.info("SSE stream complete message sent.")

            except Exception as e:
                error_trace = traceback.format_exc()
                logger.error(f"Error in generate_stream generator: {e}")
                logger.error(f"Traceback: {error_trace}")
                # Ensure this also yields an error if the generator itself has an issue
                yield encode_message({"error": str(e), "trace": error_trace})

        # Return the streaming response with proper configuration
        logger.info("Setting up streaming response")
        return Response(
            generate_stream(),
            mimetype="text/plain",
            direct_passthrough=True,
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache, no-transform",
                "Content-Type": "text/plain",
                "Transfer-Encoding": "chunked",
            },
        )


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
        sindarin_email = get_sindarin_email()

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
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
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
        @handle_automator_response
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
                screenshot_path = get_image_path(image_id)
                screenshot_data = process_screenshot_response(
                    image_id, screenshot_path, use_base64, perform_ocr
                )
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
    def __init__(self, default_direction=1):
        """Initialize the NavigationResource.

        Args:
            default_direction: Default navigation direction (1 for forward, -1 for backward)
        """
        self.default_direction = default_direction
        super().__init__()

    def _navigate_impl(self, direction=None):
        """Internal implementation for navigation - shared by GET and POST."""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Create navigation handler
        nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)

        # Process and parse navigation parameters
        params = NavigationResourceHandler.parse_navigation_params(request)

        # If a specific direction was provided in the route initialization, override navigate_count
        if direction is not None:
            # Set the navigate_count based on the requested direction
            params["navigate_count"] = direction
        # If no navigate_count was provided in the request, use the default direction
        elif "navigate" not in request.args and "navigate" not in request.form:
            params["navigate_count"] = self.default_direction

        # Log the navigation parameters
        logger.info(f"Navigation params: {params}")

        # Delegate to the handler
        return nav_handler.navigate(
            navigate_count=params["navigate_count"],
            preview_count=params["preview_count"],
            show_placemark=params["show_placemark"],
            use_base64=params["use_base64"],
            perform_ocr=params["perform_ocr"],
            book_title=params.get("title"),
        )

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self, direction=None):
        """Handle page navigation via POST."""
        return self._navigate_impl(direction)

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Handle navigation via GET requests, using query parameters"""
        # For preview endpoints, add preview parameter if not present
        endpoint = request.endpoint if hasattr(request, "endpoint") else ""
        if endpoint in ["preview_next", "preview_previous"] and "preview" not in request.args:
            # Set preview=1 for preview_next and preview=-1 for preview_previous
            preview_value = 1 if endpoint == "preview_next" else -1
            # Clone request.args to a mutable dictionary and add preview parameter
            request.args = dict(request.args)
            request.args["preview"] = str(preview_value)

        # Process and parse navigation parameters
        params = NavigationResourceHandler.parse_navigation_params(request)

        # If no navigate parameter was provided, use the default direction
        if "navigate" not in request.args:
            direction = self.default_direction
        else:
            direction = None  # Will use the parsed navigate_count from params

        # Call the internal implementation
        return self._navigate_impl(direction)


class BookOpenResource(Resource):
    def _open_book(self, book_title):
        """Open a specific book - shared implementation for GET and POST."""
        # URL decode the book title to handle plus signs and other encoded characters
        if book_title:
            decoded_book_title = urllib.parse.unquote_plus(book_title)
            if decoded_book_title != book_title:
                logger.info(f"Decoded book title: '{book_title}' -> '{decoded_book_title}'")
                book_title = decoded_book_title

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Check if OCR is requested
        perform_ocr = is_ocr_requested()
        if perform_ocr:
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True

        # Check if placemark is requested - default is FALSE which means DO NOT show placemark
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for this request")

        logger.info(f"Opening book: {book_title}")

        if not book_title:
            return {"error": "Book title is required in the request"}, 400

        # Common function to capture progress and screenshot
        def capture_book_state(already_open=False):
            # Check for the 'last read page' dialog without auto-accepting
            from handlers.navigation_handler import NavigationResourceHandler

            nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)
            dialog_result = nav_handler._handle_last_read_page_dialog(auto_accept=False)

            # If dialog was found, return it to the client for decision
            if isinstance(dialog_result, dict) and dialog_result.get("dialog_found"):
                logger.info(
                    "Found 'last read page' dialog in open-book endpoint - returning to client for decision"
                )

                # We don't need screenshots or page source

                # Build response with dialog info
                response_data = {
                    "success": True,
                    "last_read_dialog": True,
                    "dialog_text": dialog_result.get("dialog_text"),
                    "message": "Last read page dialog detected",
                }

                # Add flag if book was already open
                if already_open:
                    response_data["already_open"] = True

                # No screenshot data to add

                return response_data, 200

            # No dialog found, continue with normal flow
            # Get reading progress
            progress = automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )
            logger.info(f"Progress: {progress}")

            # Create response data with progress info
            response_data = {"success": True, "progress": progress}

            # Add flag if book was already open
            if already_open:
                response_data["already_open"] = True

            # We need OCR text if requested, but without screenshots
            if perform_ocr:
                # Take a screenshot just for OCR then discard it
                screenshot_id = f"ocr_temp_{int(time.time())}"
                screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
                automator.driver.save_screenshot(screenshot_path)

                # Get OCR text
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                ocr_text, _ = KindleOCR.process_ocr(image_data)
                if ocr_text:
                    response_data["ocr_text"] = ocr_text

                # Delete the temporary screenshot
                try:
                    os.remove(screenshot_path)
                except Exception as e:
                    logger.error(f"Error removing temporary OCR screenshot: {e}")

            return response_data, 200

        # Ensure state_machine is initialized
        if not automator.state_machine:
            logger.error("State machine not initialized for automator")
            return {
                "error": "State machine not initialized. Please ensure the automator is properly initialized."
            }, 500

        # Reload the current state to be sure
        automator.state_machine.update_current_state()
        current_state = automator.state_machine.current_state

        # IMPORTANT: For new app installation or first run, current_book may be None
        # even though we're already in reading state - we need to check that too

        # Get current book for this email
        current_book = server.current_books.get(sindarin_email)

        # If we're already in READING state, we should NOT close the book - get the title!
        if current_state == AppState.READING:
            # First check for Download Limit dialog which needs to be handled even for already-open books
            try:
                # Check if we're dealing with the Download Limit dialog
                if automator.state_machine.reader_handler._check_for_download_limit_dialog():
                    logger.info("Found Download Limit dialog for current book - handling it")
                    # Handle the dialog
                    if automator.state_machine.reader_handler.handle_download_limit_dialog():
                        logger.info("Successfully handled Download Limit dialog")
                        # Continue with normal flow after handling dialog
                    else:
                        logger.error("Failed to handle Download Limit dialog")
                        return {"error": "Failed to handle Download Limit dialog"}, 500
            except Exception as e:
                logger.error(f"Error checking for Download Limit dialog: {e}")

            # Then, check if we have current_book set
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
                    current_title_from_ui = automator.state_machine.reader_handler.get_book_title()
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
                # We're in reading state but don't have current_book set
                # First check if we have an actively reading title stored in profile settings
                actively_reading_title = automator.profile_manager.get_style_setting(
                    "actively_reading_title", email=sindarin_email
                )

                if actively_reading_title:
                    # Compare with the requested book
                    normalized_request_title = "".join(
                        c for c in book_title if c.isalnum() or c.isspace()
                    ).lower()
                    normalized_active_title = "".join(
                        c for c in actively_reading_title if c.isalnum() or c.isspace()
                    ).lower()

                    logger.info(
                        f"Title comparison with stored active title: requested='{normalized_request_title}', active='{normalized_active_title}'"
                    )

                    # Try exact match first
                    if normalized_request_title == normalized_active_title:
                        logger.info(
                            f"Already reading book (stored active title exact match): {book_title}, returning current state"
                        )
                        # Update server's current book tracking
                        server.set_current_book(actively_reading_title, sindarin_email)
                        return capture_book_state(already_open=True)

                    # For longer titles, try to match the first 30+ characters or check if one title contains the other
                    if (
                        len(normalized_request_title) > 30
                        and len(normalized_active_title) > 30
                        and (
                            normalized_request_title[:30] == normalized_active_title[:30]
                            or normalized_request_title in normalized_active_title
                            or normalized_active_title in normalized_request_title
                        )
                    ):
                        logger.info(
                            f"Already reading book (stored active title partial match): {book_title}, returning current state"
                        )
                        # Update server's current book tracking
                        server.set_current_book(actively_reading_title, sindarin_email)
                        return capture_book_state(already_open=True)

                # If no match with stored title, try to get it from UI
                try:
                    # Try to get the current book title from the reader UI
                    current_title_from_ui = automator.state_machine.reader_handler.get_book_title()
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

        # If we get here, we need to go to library or handle search results directly
        logger.info(
            f"Not already reading requested book: {book_title} != {current_book}, current state: {current_state}"
        )

        # If we're in search results view, we can open books directly without transitioning to library
        if current_state == AppState.SEARCH_RESULTS:
            logger.info("Currently in SEARCH_RESULTS view, opening book directly")

            # Set book_to_open attribute on automator for the state handler to use
            automator.book_to_open = book_title
            logger.info(f"Set automator.book_to_open to '{book_title}' for handle_search_results")

            # First try to handle the search results state which will look for the book
            if automator.state_machine.handle_state():
                logger.info("Successfully handled SEARCH_RESULTS state")
                # Check if we've moved to READING state
                automator.state_machine.update_current_state()
                if automator.state_machine.current_state == AppState.READING:
                    # Set the current book in the server state
                    server.set_current_book(book_title, sindarin_email)
                    return capture_book_state()

            # If handle_state didn't succeed or we're not in READING state, try direct approach
            logger.info("Falling back to direct library_handler.open_book for search results")
            result = automator.state_machine.library_handler.open_book(book_title)
            logger.info(f"Book open result from search results: {result}")

            # Handle dictionary response from library handler
            if result.get("status") == "title_not_available":
                # Return the error response directly
                return result, 400
            elif result.get("success"):
                # Set the current book in the server state
                server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500

        # For other states, transition to library and open the book
        logger.info(f"Transitioning from {current_state} to library")
        if automator.state_machine.transition_to_library(server=server):
            # Use library_handler to open the book instead of reader_handler
            result = automator.state_machine.library_handler.open_book(book_title)
            logger.info(f"Book open result: {result}")

            # Handle dictionary response from library handler
            if result.get("status") == "title_not_available":
                # Return the error response directly
                return result, 400
            elif result.get("success"):
                # Set the current book in the server state
                server.set_current_book(book_title, sindarin_email)
                return capture_book_state()
            else:
                # Return the error from the result
                return result, 500
        else:
            # Failed to transition to library
            logger.error(f"Failed to transition from {current_state} to library")
            return {"success": False, "error": f"Failed to transition from {current_state} to library"}, 500

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


class AuthResource(Resource):
    def _handle_recreate(self, sindarin_email, recreate_user=True, recreate_seed=False):
        """Handle deletion of AVDs when recreate is requested"""
        actions = []
        if recreate_user:
            actions.append("user AVD")
        if recreate_seed:
            actions.append("seed clone")

        logger.info(f"Recreate requested for {sindarin_email}, will recreate: {', '.join(actions)}")

        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()

        # Clean up the automator before recreating AVDs
        if sindarin_email in server.automators:
            logger.info(f"Cleaning up existing automator for {sindarin_email}")
            automator = server.automators[sindarin_email]
            if automator:
                automator.cleanup()
            del server.automators[sindarin_email]

        # Use the new recreate_profile_avd method with parameters
        success, message = profile_manager.recreate_profile_avd(sindarin_email, recreate_user, recreate_seed)
        if not success:
            logger.error(f"Failed to recreate profile AVD: {message}")
            return False, message

        return True, f"Successfully recreated: {', '.join(actions)}"

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _auth(self):
        """Set up a profile for manual authentication via VNC or WebSockets"""
        # Create a unified params dict that combines query params and JSON body
        params = {}
        for key, value in request.args.items():
            params[key] = value

        # Then try to add JSON parameters if available (they override query params)
        if request.is_json:
            try:
                json_data = request.get_json() or {}
                # Update params with JSON data (overriding any query params with the same name)
                for key, value in json_data.items():
                    params[key] = value
            except:
                # In case of JSON parsing error, just continue with query params
                logger.warning("Failed to parse JSON data in request")

        # Get sindarin_email from unified params
        sindarin_email = params.get("sindarin_email")

        # Fall back to form data if needed
        if not sindarin_email and "sindarin_email" in request.form:
            sindarin_email = request.form.get("sindarin_email")

        # Sindarin email is required for profile identification
        if not sindarin_email:
            logger.error("No sindarin_email provided for profile identification")
            return {"error": "sindarin_email is required for profile identification"}, 400

        # Process boolean parameters in a unified way
        # For query params, "1", "true", "yes" (case-insensitive) are considered true
        # For JSON data, use the boolean or convert string values
        def get_bool_param(param_name, default=False):
            if param_name not in params:
                return default

            value = params[param_name]
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ("1", "true", "yes")
            elif isinstance(value, int):
                return value == 1
            return default

        # Get boolean parameters
        recreate = get_bool_param("recreate", False)
        restart_vnc = get_bool_param("restart_vnc", False)
        use_websockets = get_bool_param("websockets", False)

        if restart_vnc:
            logger.info(f"Restart VNC requested for {sindarin_email}")

        if use_websockets:
            logger.info(f"WebSockets requested for {sindarin_email} (will use rfbproxy)")

        # Log authentication attempt details
        logger.info(f"Setting up profile: {sindarin_email} for manual VNC authentication")

        # Debug logging for cross-user interference
        logger.info(f"CROSS_USER_DEBUG: Auth endpoint called for email={sindarin_email}")
        logger.info(f"CROSS_USER_DEBUG: Current automators in server: {list(server.automators.keys())}")

        # Get the automator (should have been created by the decorator)
        automator = server.automators.get(sindarin_email)
        logger.info(
            f"CROSS_USER_DEBUG: Retrieved automator={id(automator) if automator else 'None'} for email={sindarin_email}"
        )

        # Use the prepare_for_authentication method - always using VNC
        # Make sure the driver has access to the automator for state transitions
        # This fixes the "Could not access automator from driver session" error
        if automator and automator.driver and not hasattr(automator.driver, "automator"):
            logger.info("Setting automator on driver object for state transitions")
            automator.driver.automator = automator
            logger.info(
                f"CROSS_USER_DEBUG: Set driver.automator reference - driver={id(automator.driver)}, automator={id(automator)}"
            )

        # Ensure the automator exists and driver is healthy and all components are initialized
        if not automator:
            logger.error("Failed to get automator for request")
            return {"error": "Failed to initialize automator"}, 500

        if automator.driver:
            logger.info(
                f"CROSS_USER_DEBUG: Before ensure_driver_running - driver={id(automator.driver)}, automator={id(automator)}, device_id={getattr(automator, 'device_id', 'unknown')}"
            )

        if not automator.ensure_driver_running():
            logger.error("Failed to ensure driver is running, cannot proceed with authentication")
            return {"error": "Failed to initialize automator driver"}, 500

        # This is the critical method that ensures we navigate to AUTH or LIBRARY
        logger.info("Calling prepare_for_authentication to navigate to sign-in screen or library")
        logger.info(
            f"CROSS_USER_DEBUG: About to call prepare_for_authentication - automator={id(automator)}, state_machine={id(automator.state_machine)}, auth_handler={id(automator.state_machine.auth_handler)}"
        )
        auth_status = automator.state_machine.auth_handler.prepare_for_authentication()
        logger.info(f"CROSS_USER_DEBUG: prepare_for_authentication returned for email={sindarin_email}")

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

        # Handle restart_vnc parameter if set - force kill existing VNC process
        if restart_vnc:
            import platform
            import subprocess

            from server.utils.vnc_instance_manager import VNCInstanceManager

            # Get the display number for this profile
            logger.info(f"Explicitly restarting VNC server for {sindarin_email}")

            # Skip on macOS
            if platform.system() != "Darwin":
                try:
                    # Get VNC instance manager to find the display
                    vnc_manager = VNCInstanceManager.get_instance()
                    display_num_to_restart = None
                    vnc_port_to_restart = None

                    for instance in vnc_manager.instances:
                        if instance.get("assigned_profile") == sindarin_email:
                            display_num_to_restart = instance.get("display")
                            vnc_port_to_restart = instance.get("vnc_port")
                            break

                    if display_num_to_restart:
                        logger.info(
                            f"Found display :{display_num_to_restart} for {sindarin_email}, killing existing VNC process"
                        )
                        # Kill any existing VNC process for this display
                        subprocess.run(["pkill", "-f", f"x11vnc.*:{display_num_to_restart}"], check=False)
                        # Also force kill by port
                        if vnc_port_to_restart:
                            subprocess.run(
                                ["pkill", "-f", f"x11vnc.*rfbport {vnc_port_to_restart}"], check=False
                            )

                        logger.info(f"Forced VNC restart for display :{display_num_to_restart}")
                    else:
                        logger.warning(f"Could not find display number for {sindarin_email}")
                except Exception as e:
                    logger.error(f"Error restarting VNC server: {e}")

        # Get the formatted VNC URL with the profile email
        # This will also start the VNC server if it's not running
        # If websockets are requested, also get the websocket URL
        if use_websockets:
            # Get both VNC and WebSocket URLs
            vnc_url, ws_url = get_vnc_and_websocket_urls(sindarin_email)
            formatted_vnc_url = vnc_url  # Keep using vnc_url for backward compatibility
        else:
            # Just get the regular VNC URL
            formatted_vnc_url = get_formatted_vnc_url(sindarin_email)
            ws_url = None

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

        # Add WebSocket URL to the response if available
        if use_websockets and ws_url:
            response_data["websocket_url"] = ws_url

        # Log the final response in detail
        logger.info(f"Returning auth response: {response_data}")

        return response_data, 200

    def get(self):
        """Get the auth status"""
        # First check if recreate is requested BEFORE profile loading
        params = {}
        for key, value in request.args.items():
            params[key] = value

        sindarin_email = params.get("sindarin_email")
        recreate_user = params.get("recreate") == 1 or params.get("recreate") == "1"
        recreate_seed = params.get("recreate_seed") == 1 or params.get("recreate_seed") == "1"

        if sindarin_email and (recreate_user or recreate_seed):
            success, message = self._handle_recreate(sindarin_email, recreate_user, recreate_seed)
            if not success:
                return {"error": message}, 500

        # Now proceed with normal auth flow
        return self._auth()

    def post(self):
        """Set up a profile for manual authentication via VNC"""
        # First check if recreate is requested BEFORE profile loading
        params = {}
        if request.is_json:
            params = request.get_json() or {}

        sindarin_email = params.get("sindarin_email") or params.get("email")
        recreate_user = params.get("recreate") == 1 or params.get("recreate") == "1"
        recreate_seed = params.get("recreate_seed") == 1 or params.get("recreate_seed") == "1"

        if sindarin_email and (recreate_user or recreate_seed):
            success, message = self._handle_recreate(sindarin_email, recreate_user, recreate_seed)
            if not success:
                return {"error": message}, 500

        # Now proceed with normal auth flow
        return self._auth()


class FixturesResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Create fixtures for major views"""
        try:
            automator, _, error_response = get_automator_for_request(server)
            if error_response:
                return error_response

            fixtures_handler = TestFixturesHandler(automator.driver)
            if fixtures_handler.create_fixtures():
                return {"status": "success", "message": "Created fixtures for all major views"}, 200
            return {"error": "Failed to create fixtures"}, 500

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error creating fixtures: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500


class ImageResource(Resource):
    def get(self, image_id):
        """Get an image by ID and delete it after serving."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)


class CoverImageResource(Resource):
    def get(self, email_slug, filename):
        """Get a book cover image by email slug and filename."""
        try:
            # Construct the absolute path to the cover image
            project_root = Path(__file__).resolve().parent.parent.absolute()
            covers_dir = project_root / "covers"
            user_covers_dir = covers_dir / email_slug
            cover_path = user_covers_dir / filename

            # Check if cover file exists
            if not cover_path.exists():
                logger.error(f"Cover image not found: {cover_path}")
                return {"error": "Cover image not found"}, 404

            # Create response with proper mime type
            response = make_response(send_file(str(cover_path), mimetype="image/png"))

            # No need to delete cover images - they're persisted for future use
            return response

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error serving cover image: {e}")
            traceback.print_exc()
            return {"error": str(e)}, 500


class TextResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _extract_text(self):
        """Shared implementation for extracting text from the current reading page."""
        try:
            automator, _, error_response = get_automator_for_request(server)
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


class LastReadPageDialogResource(Resource):
    """Resource for handling the 'Last read page' dialog decisions.

    This endpoint allows the client to decide whether to click "Yes" or "No"
    on the "Last read page" dialog that appears when opening a book or navigating.
    """

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Handle Last read page dialog choice from the client via GET request."""
        # Call the implementation method that handles both GET and POST requests
        return self._handle_last_read_page_dialog_choice()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Handle Last read page dialog choice from the client via POST request."""
        # Call the implementation method that handles both GET and POST requests
        return self._handle_last_read_page_dialog_choice()

    def _handle_last_read_page_dialog_choice(self):
        """Implementation for handling Last read page dialog choice from both GET and POST requests."""
        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Check if base64 parameter is provided
        use_base64 = is_base64_requested()

        # Check if OCR is requested
        perform_ocr = is_ocr_requested()
        if perform_ocr:
            logger.info("OCR requested, will process image with OCR")
            if not use_base64:
                # Force base64 encoding for OCR
                use_base64 = True
                logger.info("Forcing base64 encoding for OCR processing")

        # Check if placemark is requested - default is FALSE
        show_placemark = False
        placemark_param = request.args.get("placemark", "0")
        if placemark_param and placemark_param.lower() in ("1", "true", "yes"):
            show_placemark = True
            logger.info("Placemark mode enabled for this request")
        else:
            logger.info("Placemark mode disabled - will avoid tapping to prevent placemark display")

        # Get the goto_last_read_page parameter from either query params or JSON body
        # First check query params
        goto_last_read_page = None
        goto_last_read_page_param = request.args.get("goto_last_read_page")
        if goto_last_read_page_param is not None:
            goto_last_read_page = goto_last_read_page_param.lower() in ("1", "true", "yes")
            logger.info(f"Found goto_last_read_page in query params: {goto_last_read_page}")

        # Then check JSON body if not found in query params
        if goto_last_read_page is None:
            data = request.get_json(silent=True) or {}
            if "goto_last_read_page" in data:
                goto_last_read_page_json = data.get("goto_last_read_page")
                if isinstance(goto_last_read_page_json, bool):
                    goto_last_read_page = goto_last_read_page_json
                elif isinstance(goto_last_read_page_json, str):
                    goto_last_read_page = goto_last_read_page_json.lower() in ("1", "true", "yes")
                elif isinstance(goto_last_read_page_json, int):
                    goto_last_read_page = goto_last_read_page_json == 1
                logger.info(f"Found goto_last_read_page in JSON body: {goto_last_read_page}")

        # If parameter wasn't provided, return an error
        if goto_last_read_page is None:
            return {
                "error": "Parameter 'goto_last_read_page' is required (boolean)",
                "message": (
                    "Must specify whether to go to the last read page (true) or start from beginning (false)"
                ),
            }, 400

        # Value is already converted to boolean when extracted from either source

        logger.info(f"Last read page dialog choice: goto_last_read_page={goto_last_read_page}")

        # Use NavigationResourceHandler to handle the dialog
        from handlers.navigation_handler import NavigationResourceHandler

        nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)

        # First check if the dialog is still visible before trying to click
        dialog_result = nav_handler._handle_last_read_page_dialog(auto_accept=False)
        if not dialog_result or not isinstance(dialog_result, dict) or not dialog_result.get("dialog_found"):
            logger.warning("Last read page dialog no longer visible - may have timed out or been dismissed")
            return {"error": "Last read page dialog not found"}, 404

        # Get dialog info for response
        dialog_text = dialog_result.get("dialog_text", "")

        # Now click the appropriate button based on the client's choice
        from selenium.common.exceptions import NoSuchElementException

        from views.reading.interaction_strategies import LAST_READ_PAGE_DIALOG_BUTTONS
        from views.reading.view_strategies import LAST_READ_PAGE_DIALOG_IDENTIFIERS

        try:
            # Try to click YES or NO based on the goto_last_read_page value
            button_clicked = False

            # YES button - go to last read page
            if goto_last_read_page:
                logger.info("Client chose to go to last read page - clicking YES")
                for btn_strategy, btn_locator in LAST_READ_PAGE_DIALOG_BUTTONS:
                    try:
                        yes_button = automator.driver.find_element(btn_strategy, btn_locator)
                        if yes_button.is_displayed():
                            yes_button.click()
                            logger.info("Clicked YES button")
                            button_clicked = True
                            time.sleep(0.5)  # Give dialog time to dismiss
                            break
                    except NoSuchElementException:
                        continue
            # NO button - start from the beginning
            else:
                logger.info("Client chose to start from beginning - clicking NO")
                # The NO button is usually the second button (button2)
                try:
                    no_button = automator.driver.find_element("id", "android:id/button2")
                    if no_button.is_displayed():
                        no_button.click()
                        logger.info("Clicked NO button")
                        button_clicked = True
                        time.sleep(0.5)  # Give dialog time to dismiss
                except NoSuchElementException:
                    # Try another approach - look for "NO" text
                    try:
                        no_button = automator.driver.find_element(
                            "xpath", "//android.widget.Button[@text='NO']"
                        )
                        if no_button.is_displayed():
                            no_button.click()
                            logger.info("Clicked NO button by text")
                            button_clicked = True
                            time.sleep(0.5)  # Give dialog time to dismiss
                    except NoSuchElementException:
                        logger.warning("NO button not found by text")

            if not button_clicked:
                logger.error(f"Failed to click {'YES' if goto_last_read_page else 'NO'} button")
                return {"error": f"Failed to click {'YES' if goto_last_read_page else 'NO'} button"}, 500

            # Get reading progress
            progress = automator.state_machine.reader_handler.get_reading_progress(
                show_placemark=show_placemark
            )

            # Build response
            response_data = {
                "success": True,
                "message": (
                    f"Successfully clicked {'YES' if goto_last_read_page else 'NO'} on Last read page dialog"
                ),
                "dialog_text": dialog_text,
                "progress": progress,
            }

            # We need OCR text if requested, but without screenshots
            if perform_ocr:
                # Take a screenshot just for OCR then discard it
                screenshot_id = f"ocr_temp_{int(time.time())}"
                screenshot_path = os.path.join(automator.screenshots_dir, f"{screenshot_id}.png")
                automator.driver.save_screenshot(screenshot_path)

                # Get OCR text
                with open(screenshot_path, "rb") as img_file:
                    image_data = img_file.read()

                ocr_text, _ = KindleOCR.process_ocr(image_data)
                if ocr_text:
                    response_data["ocr_text"] = ocr_text

                # Delete the temporary screenshot
                try:
                    os.remove(screenshot_path)
                except Exception as e:
                    logger.error(f"Error removing temporary OCR screenshot: {e}")

            return response_data, 200

        except Exception as e:
            logger.error(f"Error handling Last read page dialog choice: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"Failed to handle dialog choice: {str(e)}"}, 500


# Import resource modules
from server.resources.auth_check_resource import AuthCheckResource
from server.resources.cold_storage_resources import (
    ColdStorageArchiveResource,
    ColdStorageRestoreResource,
    ColdStorageStatusResource,
)
from server.resources.idle_check_resources import IdleCheckResource
from server.resources.log_timeline_resource import LogTimelineResource
from server.resources.logout_resource import LogoutResource
from server.resources.shutdown_resources import ShutdownResource
from server.resources.staff_auth_resources import StaffAuthResource, StaffTokensResource
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
api.add_resource(
    LogoutResource,
    "/logout",
    resource_class_kwargs={"server_instance": server},
)
api.add_resource(AuthResource, "/auth")
api.add_resource(AuthCheckResource, "/auth-check")
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
