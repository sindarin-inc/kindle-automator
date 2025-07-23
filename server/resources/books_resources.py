"""Book-related resources for listing and streaming books."""

import json
import logging
import os
import time
import traceback

from flask import Response, request
from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.cover_utils import (
    add_cover_urls_to_books,
    extract_book_covers_from_screen,
)
from server.utils.request_utils import get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class BooksResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _get_books(self):
        """Get list of available books with metadata"""
        from server.server import server

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
            from server.utils.appium_error_utils import is_appium_error

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
        from server.server import server

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

        # Check initial state and restart if UNKNOWN
        current_state = automator.state_machine.check_initial_state_with_restart()
        logger.info(f"Current state for books-stream: {current_state}")

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

            # Try to transition to library state
            logger.info("Not in library state, attempting to transition...")
            final_state = automator.state_machine.transition_to_library(server=server)

            # The transition_to_library now returns the final state
            logger.info(f"State after transition attempt: {final_state}")

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
                        from server.utils.appium_error_utils import is_appium_error

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
                from server.logging_config import clear_email_context, set_email_context
                from server.utils.request_utils import email_override

                set_email_context(sindarin_email)
                with email_override(sindarin_email):
                    try:
                        logger.info(
                            f"Starting book retrieval with processing callback in a new thread (sync={sync})."
                        )
                        automator.state_machine.library_handler.get_book_titles(
                            callback=book_processing_callback, sync=sync
                        )
                    except Exception as e:
                        from server.utils.appium_error_utils import is_appium_error

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
                    return (json.dumps(msg_dict) + "\n").encode("utf-8")

                # Update activity at the start of streaming
                logger.info(f"Starting book stream for {sindarin_email}, updating activity")
                server.update_activity(sindarin_email)

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
                        logger.error(
                            f"Unexpected error in generate_stream while getting from queue: {e}",
                            exc_info=True,
                        )
                        yield encode_message({"error": f"Streaming error: {str(e)}"})  # Send error to client
                        break  # Terminate stream on unexpected errors

                # After the loop, if no error was yielded from inside the loop
                if not error_message:
                    # Update activity at the end of successful streaming
                    logger.info(f"Book stream completed for {sindarin_email}, updating activity")
                    server.update_activity(sindarin_email)

                    logger.info(
                        f'Stream finished: {{"done": true, "total_books": {total_books_from_handler}}}'
                    )
                    yield encode_message({"done": True, "total_books": total_books_from_handler})

                yield encode_message({"complete": True})
                logger.info("SSE stream complete message sent")

            except Exception as e:
                error_trace = traceback.format_exc()
                logger.error(f"Error in generate_stream generator: {e}", exc_info=True)
                logger.error(f"Traceback: {error_trace}", exc_info=True)
                # Ensure this also yields an error if the generator itself has an issue
                yield encode_message({"error": str(e), "trace": error_trace})

        # Return the streaming response with proper configuration
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
