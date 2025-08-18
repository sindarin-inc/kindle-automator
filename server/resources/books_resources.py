"""Book-related resources for listing and streaming books."""

import json
import logging
import os
import time
import traceback

from flask import Response, request, stream_with_context
from flask_restful import Resource

from server.core.automation_server import AutomationServer
from server.core.redis_connection import get_redis_client
from server.logging_config import clear_email_context, set_email_context
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
from server.middleware.response_handler import handle_automator_response
from server.utils.ansi_colors import BOLD, BRIGHT_BLUE, RESET
from server.utils.appium_error_utils import is_appium_error
from server.utils.cancellation_utils import (
    CancellationChecker,
    get_active_request_info,
    should_cancel,
)
from server.utils.cover_utils import (
    add_cover_urls_to_books,
    extract_book_covers_from_screen,
)
from server.utils.request_utils import email_override, get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class BooksResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
    @handle_automator_response
    def _get_books(self):
        """Get list of available books with metadata"""
        server = AutomationServer.get_instance()

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.warning("No email provided to identify which profile to use")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            logger.error(f"No automator found for {sindarin_email}", exc_info=True)
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
                    "authenticated": False,
                    "current_state": current_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            # Try to transition to library state
            logger.info("Not in library state, attempting to transition...")
            final_state = automator.state_machine.transition_to_library(server=server)

            # The transition_to_library now returns the final state
            logger.info(f"State after transition attempt: {final_state}")

            # Check for auth requirement regardless of transition success
            if final_state == AppState.SIGN_IN:
                # Use the state machine's auth handler
                auth_response = automator.state_machine.handle_auth_state_detection(
                    final_state, sindarin_email
                )
                if auth_response:
                    logger.info("Authentication required after transition attempt - providing VNC URL")
                    return auth_response, 401

            if final_state == AppState.LIBRARY:
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
                        "authenticated": False,
                        "message": "Authentication is required via VNC",
                        "emulator_id": emulator_id,
                    }, 401

                return {"books": books}, 200
            else:
                # Transition didn't reach library, check what state we're in
                updated_state = final_state

                if updated_state == AppState.SIGN_IN:
                    # Use the state machine's auth handler
                    auth_response = automator.state_machine.handle_auth_state_detection(
                        updated_state, sindarin_email
                    )
                    if auth_response:
                        logger.info("Transition failed - authentication required - providing VNC URL")
                        return auth_response, 401
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
                "authenticated": False,
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
            if is_appium_error(e):
                raise
            logger.error(f"Error extracting book covers: {e}", exc_info=True)
            logger.error(f"Traceback: {traceback.format_exc()}", exc_info=True)

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
        from server.core.request_manager import RequestManager

        server = AutomationServer.get_instance()

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.warning("No email provided to identify which profile to use")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Create request manager for priority handling (not full deduplication for streams)
        manager = RequestManager(sindarin_email, "/books-stream", "GET")

        # Check if we should wait for higher priority request
        if manager._should_wait_for_higher_priority():
            logger.info(
                f"{BRIGHT_BLUE}Books-stream request blocked by higher priority operation for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
            )
            return {"error": "Request blocked by higher priority operation"}, 409

        # Check for and cancel lower priority requests
        manager._check_and_cancel_lower_priority_requests()

        # Register as active request (but don't prevent duplicates for reconnection support)
        manager._set_active_request()
        logger.info(f"[{time.time():.3f}] Books-stream registered as active for {sindarin_email}")

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            logger.error(f"No automator found for {sindarin_email}", exc_info=True)
            manager._clear_active_request()
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Store the request key for cancellation checking during state transitions
        stream_request_key = manager.request_key

        # Set up cancellation check function for the state machine
        def check_cancellation():
            """Check if this stream request has been cancelled."""
            return should_cancel(sindarin_email, stream_request_key)

        # Set the cancellation check on the state machine for interruptible operations
        automator.state_machine.set_cancellation_check(check_cancellation)

        # Check for cancellation before state check
        if should_cancel(sindarin_email, stream_request_key):
            logger.info(
                f"{BRIGHT_BLUE}[{time.time():.3f}] Stream cancelled before state check for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
            )
            manager._clear_active_request()
            automator.state_machine.set_cancellation_check(None)
            return {"error": "Request cancelled by higher priority operation", "cancelled": True}, 409

        # Check initial state and restart if UNKNOWN
        logger.info(f"[{time.time():.3f}] Starting state check for books-stream: {sindarin_email}")
        current_state = automator.state_machine.check_initial_state_with_restart()
        logger.info(f"[{time.time():.3f}] Current state for books-stream: {current_state}")

        # Handle different states - similar to _get_books but with appropriate streaming responses
        if current_state != AppState.LIBRARY:
            # Check if we're on the sign-in screen
            if current_state == AppState.SIGN_IN or current_state == AppState.LIBRARY_SIGN_IN:
                # Check if user was previously authenticated (has auth_date)
                profile_manager = automator.profile_manager
                auth_date = profile_manager.get_user_field(sindarin_email, "auth_date")

                if auth_date:
                    # User was previously authenticated but lost auth
                    logger.warning(
                        f"User {sindarin_email} was previously authenticated on {auth_date} but is now in {current_state} - marking auth as failed"
                    )
                    profile_manager.update_auth_state(sindarin_email, authenticated=False)

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
                    "authenticated": False,
                    "current_state": current_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            # Check for cancellation before attempting transition
            if should_cancel(sindarin_email, stream_request_key):
                logger.info(
                    f"{BRIGHT_BLUE}[{time.time():.3f}] Stream cancelled before transition for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
                )
                manager._clear_active_request()
                automator.state_machine.set_cancellation_check(None)
                return {"error": "Request cancelled by higher priority operation", "cancelled": True}, 409

            # Try to transition to library state
            logger.info(f"[{time.time():.3f}] Not in library state, attempting to transition...")
            final_state = automator.state_machine.transition_to_library(server=server)

            # The transition_to_library now returns the final state
            logger.info(f"[{time.time():.3f}] State after transition attempt: {final_state}")

            # Check for cancellation after transition
            if should_cancel(sindarin_email, stream_request_key):
                logger.info(
                    f"{BRIGHT_BLUE}[{time.time():.3f}] Stream cancelled after transition for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
                )
                manager._clear_active_request()
                automator.state_machine.set_cancellation_check(None)
                return {"error": "Request cancelled by higher priority operation", "cancelled": True}, 409

            # Check for auth requirement regardless of transition success
            if final_state == AppState.SIGN_IN:
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
                    "authenticated": False,
                    "current_state": final_state.name,
                    "message": "Authentication is required via VNC",
                    "emulator_id": emulator_id,
                }, 401

            if final_state != AppState.LIBRARY:
                # If transition failed to reach library, check for auth requirement
                # Use the state machine's auth handler
                auth_response = automator.state_machine.handle_auth_state_detection(
                    final_state, sindarin_email
                )
                if auth_response:
                    logger.info("Transition failed - authentication required - providing VNC URL")
                    return auth_response, 401

                # Not an auth state, return error
                return {
                    "error": f"Cannot get books in current state: {final_state.name}",
                    "current_state": final_state.name,
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

        # Standard implementation with book retrieval
        def generate_stream():
            import queue  # For thread-safe communication
            import threading

            logger.info(f"[{time.time():.3f}] Starting generate_stream for {sindarin_email}")

            # Event for signaling all books are retrieved by the library_handler
            all_books_retrieved_event = threading.Event()

            # Thread-safe queue for processed book batches
            processed_books_queue = queue.Queue()

            # Shared variables for status
            error_message = None
            total_books_from_handler = 0  # To store the total count from library_handler
            scroll_complete = False  # Whether we scrolled through all books
            successful_covers_accumulator = {}  # Accumulate all successful covers (now a dict)

            # Create cancellation checker for this request - check every iteration for streams
            cancellation_checker = CancellationChecker(sindarin_email, check_interval=1)

            # Get and store the request key for THIS stream from our manager
            # (not from get_active_request_info which might return a different request)
            stream_request_key = manager.request_key
            if stream_request_key:
                logger.info(f"[{time.time():.3f}] Books-stream request key: {stream_request_key}")

            # Track if we've been cancelled to prevent further processing
            stream_cancelled = False

            # Callback function that will receive raw books_batch from the library handler
            # This callback will process books synchronously (screenshot, covers) for the current stable view
            def book_processing_callback(raw_books_batch, **kwargs):
                nonlocal error_message, total_books_from_handler, stream_cancelled, scroll_complete

                # If already cancelled, don't process anything more
                if stream_cancelled:
                    return

                # Check for cancellation before processing each batch - check every time for streams
                if should_cancel(sindarin_email, stream_request_key):
                    logger.info(
                        f"Book retrieval cancelled for {sindarin_email} due to higher priority request"
                    )
                    error_message = "Request cancelled by higher priority operation"
                    stream_cancelled = True
                    all_books_retrieved_event.set()  # Signal to stop generate_stream loop
                    return

                if kwargs.get("error"):
                    logger.info(f"Callback received error: {kwargs.get('error')}")
                    error_message = kwargs.get("error")
                    # Check if this is also a done signal (error with completion info)
                    if kwargs.get("done"):
                        total_books_from_handler = kwargs.get("total_books", 0)
                        scroll_complete = kwargs.get("complete", False)
                    all_books_retrieved_event.set()  # Signal to stop generate_stream loop
                    return

                if kwargs.get("done"):
                    total_books_from_handler = kwargs.get("total_books", 0)
                    scroll_complete = kwargs.get("complete", False)
                    all_books_retrieved_event.set()  # Signal completion of book retrieval
                    return

                # Handle filter book count message
                if kwargs.get("filter_book_count") is not None:
                    filter_count_msg = {"filter_book_count": kwargs.get("filter_book_count")}
                    processed_books_queue.put(filter_count_msg)
                    logger.info(f"Queued filter book count message: {filter_count_msg}")
                    return

                if raw_books_batch:
                    try:
                        # Update activity to prevent idle timeout during long scrolls
                        server.update_activity(sindarin_email)

                        # At this point, the UI should be stable for raw_books_batch
                        timestamp = int(time.time())
                        screenshot_filename = f"library_view_stream_{timestamp}.png"
                        screenshot_path = os.path.join(automator.screenshots_dir, screenshot_filename)
                        automator.driver.save_screenshot(screenshot_path)

                        # Extract covers from the current screen for this batch
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
                        if is_appium_error(e):
                            raise
                        logger.error(f"Error processing book batch in callback: {e}", exc_info=True)
                        logger.error(f"Traceback: {traceback.format_exc()}", exc_info=True)
                        # This error is for a single batch; retrieval might continue for others.
                        # The main error_message is for fatal errors in the retrieval thread itself.
                else:
                    logger.info("Callback received an empty books_batch or no batch.")

            # Thread to run the library_handler's book retrieval
            def start_book_retrieval_thread_fn():
                # Set email context for this background thread
                set_email_context(sindarin_email)
                with email_override(sindarin_email):
                    try:
                        logger.info(
                            f"[{time.time():.3f}] Starting book retrieval with processing callback in a new thread (sync={sync})."
                        )
                        automator.state_machine.library_handler.get_book_titles(
                            callback=book_processing_callback, sync=sync
                        )
                    except Exception as e:
                        if is_appium_error(e):
                            raise
                        logger.error(
                            f"Error in book retrieval thread (start_book_retrieval_thread_fn, exc_info=True): {e}"
                        )
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

            # Generator part for SSE (runs in Flask worker thread)
            try:

                def encode_message(msg_dict):
                    # Always use JSONL format (newline-delimited JSON)
                    return (json.dumps(msg_dict) + "\n").encode("utf-8")

                # Update activity at the start of streaming
                logger.info(
                    f"[{time.time():.3f}] Starting book stream for {sindarin_email}, updating activity"
                )
                server.update_activity(sindarin_email)

                yield encode_message(
                    {"status": "started", "message": "Book retrieval and processing initiated"}
                )

                batch_num_sent = 0
                # Add a small initial delay to allow filter count to be captured
                # The filter modal takes several seconds to open, capture counts, and close
                initial_wait_time = 0
                max_initial_wait = 10.0  # Maximum 10 seconds to wait for filter count
                check_interval = 0.1  # Check for cancellation every 100ms

                logger.info(
                    f"[{time.time():.3f}] Starting initial wait for filter count (max {max_initial_wait}s)"
                )
                while initial_wait_time < max_initial_wait:
                    # Check for cancellation during initial wait
                    if should_cancel(sindarin_email, stream_request_key) or stream_cancelled:
                        logger.info(
                            f"[{time.time():.3f}] Stream cancelled for {sindarin_email} during initial wait"
                        )
                        error_message = "Request cancelled by higher priority operation"
                        stream_cancelled = True
                        yield encode_message({"error": error_message, "cancelled": True, "done": True})
                        return  # Exit the entire generator

                    try:
                        # Check if filter count is available with shorter timeout for faster cancellation detection
                        processed_batch = processed_books_queue.get(timeout=check_interval)
                        if (
                            processed_batch
                            and isinstance(processed_batch, dict)
                            and "filter_book_count" in processed_batch
                        ):
                            # Found filter count, send it immediately
                            yield encode_message(processed_batch)
                            logger.info(f"Sent filter book count in SSE stream: {processed_batch}")
                            break
                        else:
                            # Not filter count, put it back and break
                            logger.debug(
                                f"Received non-filter batch during initial wait: {type(processed_batch)}"
                            )
                            processed_books_queue.put(processed_batch)
                            break
                    except queue.Empty:
                        initial_wait_time += check_interval
                        if initial_wait_time >= max_initial_wait:
                            logger.info("No filter count received in initial wait period")
                            break
                        elif int(initial_wait_time * 10) % 20 == 0:  # Log every 2 seconds
                            logger.debug(
                                f"Still waiting for filter count... {initial_wait_time:.1f}s elapsed"
                            )

                while True:
                    # Check for cancellation at the start of each iteration
                    if should_cancel(sindarin_email, stream_request_key) or stream_cancelled:
                        logger.info(
                            f"{BRIGHT_BLUE}Stream cancelled for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}{BRIGHT_BLUE} in main loop{RESET}"
                        )
                        error_message = "Request cancelled by higher priority operation"
                        yield encode_message({"error": error_message, "cancelled": True, "done": True})
                        return  # Exit the entire generator

                    if error_message:
                        logger.info(f"Error signaled: {error_message}. Yielding error.")
                        yield encode_message({"error": error_message, "done": True})
                        return  # Exit the entire generator

                    try:
                        # Get processed batch from queue with a timeout
                        processed_batch = processed_books_queue.get(
                            timeout=0.1
                        )  # Small timeout for fast cancellation detection
                        if processed_batch:
                            # Check if this is a filter book count message
                            if isinstance(processed_batch, dict) and "filter_book_count" in processed_batch:
                                yield encode_message(processed_batch)
                                logger.info(f"Sent filter book count in main loop: {processed_batch}")
                            else:
                                # Regular book batch
                                batch_num_sent += 1
                                yield encode_message({"books": processed_batch, "batch_num": batch_num_sent})
                        # No task_done needed for queue.Queue if not using join()
                    except queue.Empty:
                        # Queue is empty, check for cancellation again
                        if should_cancel(sindarin_email, stream_request_key) or stream_cancelled:
                            logger.info(
                                f"{BRIGHT_BLUE}Stream cancelled for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}{BRIGHT_BLUE} while waiting for data{RESET}"
                            )
                            error_message = "Request cancelled by higher priority operation"
                            yield encode_message({"error": error_message, "cancelled": True, "done": True})
                            return  # Exit the entire generator
                        # Check if book retrieval is done
                        if all_books_retrieved_event.is_set():
                            break
                        # else: continue polling, the event wasn't set yet.
                    except Exception as e:
                        if is_appium_error(e):
                            raise
                        logger.error(
                            f"Unexpected error in generate_stream while getting from queue: {e}",
                            exc_info=True,
                        )
                        yield encode_message({"error": f"Streaming error: {str(e)}"})  # Send error to client
                        break  # Terminate stream on unexpected errors

                # After the loop, always send done message with complete status
                if not error_message:
                    # Update activity at the end of successful streaming
                    logger.info(f"Book stream completed for {sindarin_email}, updating activity")
                    server.update_activity(sindarin_email)

                # Always send done message with complete status
                logger.info(
                    f'Stream finished: {{"done": true, "total_books": {total_books_from_handler}, "complete": {scroll_complete}}}'
                )
                yield encode_message(
                    {"done": True, "total_books": total_books_from_handler, "complete": scroll_complete}
                )

            except Exception as e:
                error_trace = traceback.format_exc()
                logger.error(f"Error in generate_stream generator: {e}", exc_info=True)
                logger.error(f"Traceback: {error_trace}", exc_info=True)
                # Ensure this also yields an error if the generator itself has an issue
                yield encode_message({"error": str(e), "trace": error_trace})

        # Check if we should join an existing stream (for reconnecting clients)
        redis_client = get_redis_client()
        stream_key = f"kindle:stream:{sindarin_email}:books"
        stream_active_key = f"kindle:stream:{sindarin_email}:active"

        # Check if there's an active stream we can join
        if redis_client and redis_client.get(stream_active_key):
            logger.info(f"Joining existing stream for {sindarin_email}")

            # Generator for replaying accumulated stream data
            def generate_replay_stream():
                try:
                    sent_index = 0
                    consecutive_empty = 0
                    max_consecutive_empty = 20  # Stop after 20 consecutive empty polls (10 seconds)

                    while consecutive_empty < max_consecutive_empty:
                        # Get all messages from the list
                        messages = redis_client.lrange(stream_key, sent_index, -1)

                        if messages:
                            consecutive_empty = 0
                            # Send any new messages
                            for msg in messages:
                                yield msg + b"\n" if isinstance(msg, bytes) else msg.encode("utf-8") + b"\n"
                                sent_index += 1

                                # Check if this was a done message
                                try:
                                    data = json.loads(msg)
                                    if data.get("done") or data.get("error"):
                                        logger.info(f"Found done/error message in replay, ending stream")
                                        manager._clear_active_request()
                                        return
                                except:
                                    pass
                        else:
                            # No new messages, check if stream is still active
                            if not redis_client.get(stream_active_key):
                                logger.info(f"Stream {stream_key} is no longer active")
                                # Send a done message if we didn't get one
                                done_msg = json.dumps({"done": True, "message": "Stream ended"})
                                yield done_msg.encode("utf-8") + b"\n"
                                manager._clear_active_request()
                                return

                            consecutive_empty += 1
                            time.sleep(0.5)  # Wait before polling again

                    # Timeout reached
                    logger.warning(
                        f"{BRIGHT_BLUE}Timeout waiting for stream data for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
                    )
                    timeout_msg = json.dumps({"error": "Stream timeout", "done": True})
                    yield timeout_msg.encode("utf-8") + b"\n"

                except Exception as e:
                    logger.error(f"Error in replay stream: {e}", exc_info=True)
                    error_msg = json.dumps({"error": str(e), "done": True})
                    yield error_msg.encode("utf-8") + b"\n"
                finally:
                    manager._clear_active_request()

            # Return the replay stream response
            response = Response(
                stream_with_context(generate_replay_stream()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Content-Type": "text/event-stream; charset=utf-8",
                    "Access-Control-Allow-Origin": "*",
                },
            )
            response.implicit_sequence_conversion = False
            return response

        # No existing stream, start a new one

        # Check for cancellation one more time before starting the stream
        if manager and manager.is_cancelled():
            logger.info(
                f"{BRIGHT_BLUE}Request cancelled before starting stream for {BOLD}{BRIGHT_BLUE}{sindarin_email}{RESET}"
            )
            return {"error": "Request cancelled by higher priority operation", "cancelled": True}, 409

        if redis_client:
            # Mark stream as active
            redis_client.set(stream_active_key, "1", ex=300)  # 5 minute TTL
            # Clear any old stream data
            redis_client.delete(stream_key)
            logger.info(f"Starting new stream for {sindarin_email}")

        # Wrap the generator to clean up and store to Redis
        def generate_stream_with_cleanup():
            stream_completed = False
            try:
                for chunk in generate_stream():
                    # Store chunk to Redis for replay
                    if redis_client:
                        try:
                            # Extract just the JSON data (remove newline)
                            decoded = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                            json_str = decoded.strip()
                            if json_str:
                                redis_client.rpush(stream_key, json_str)
                                redis_client.expire(stream_key, 300)  # 5 minute TTL
                        except Exception as e:
                            logger.error(f"Error storing stream chunk to Redis: {e}")

                    # Check if this chunk indicates completion
                    try:
                        decoded = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                        data = json.loads(decoded.strip())
                        if data.get("done") or data.get("error"):
                            stream_completed = True
                    except:
                        pass  # Not JSON or couldn't decode, just pass through

                    yield chunk
            finally:
                # Clear the active stream flag
                if redis_client:
                    redis_client.delete(stream_active_key)
                    if not stream_completed:
                        # Add an error message to the stream if it was interrupted
                        error_msg = json.dumps({"error": "Stream interrupted", "done": True})
                        redis_client.rpush(stream_key, error_msg)
                    redis_client.expire(stream_key, 60)  # Keep completed stream for 1 minute

                # Only clear the active request when streaming actually ends
                if stream_completed:
                    logger.info(
                        f"Stream completed, clearing active request for books-stream: {sindarin_email}"
                    )
                else:
                    logger.warning(
                        f"Stream interrupted, clearing active request for books-stream: {sindarin_email}"
                    )
                manager._clear_active_request()
                # Clear the cancellation check from state machine
                automator.state_machine.set_cancellation_check(None)

        # Return the streaming response with text/event-stream for browser compatibility
        # but still using JSONL format (no data: prefix)
        logger.info(f"[{time.time():.3f}] Creating streaming response for {sindarin_email}")
        response = Response(
            stream_with_context(generate_stream_with_cleanup()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
                "Access-Control-Allow-Origin": "*",
            },
        )
        logger.info(f"[{time.time():.3f}] Returning streaming response for {sindarin_email}")
        response.implicit_sequence_conversion = False
        return response
