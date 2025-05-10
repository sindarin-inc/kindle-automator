import logging
import os
import time
import traceback
from functools import wraps
from typing import Optional

from flask import Response, make_response, send_file
from selenium.common import exceptions as selenium_exceptions

from server.utils.request_utils import get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


# Utility function to get email and handle fallbacks consistently
def get_email_with_fallbacks(server_instance, use_helper=True) -> Optional[str]:
    """
    Get sindarin_email with consistent fallbacks across functions.

    Args:
        server_instance: The AutomationServer instance
        use_helper: Whether to use the get_sindarin_email helper function

    Returns:
        The email to use, or None if not found
    """
    # Get sindarin_email from request using the helper in utils (without a default)
    sindarin_email = get_sindarin_email()

    # Fall back to current profile if still no email
    if not sindarin_email:
        current_profile = server_instance.profile_manager.get_current_profile()
        if current_profile and "email" in current_profile:
            sindarin_email = current_profile["email"]
            logger.debug(f"Using email from current profile: {sindarin_email}")

    return sindarin_email


def get_image_path(image_id):
    """Get full path for an image file."""
    # Build path to image using project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        logger.info(f"Attempting to serve image from: {image_path}")

        if not os.path.exists(image_path):
            logger.error(f"Image not found at path: {image_path}")
            return {"error": "Image not found"}, 404

        # Create a response that bypasses Flask-RESTful's serialization
        logger.info(f"Serving image from: {image_path}")
        response = make_response(send_file(image_path, mimetype="image/png"))

        # Delete the file after sending if requested
        # We need to set up a callback to delete the file after the response is sent
        if delete_after:

            @response.call_on_close
            def on_close():
                try:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                        logger.info(f"Deleted image: {image_path}")
                except Exception as e:
                    logger.error(f"Failed to delete image {image_path}: {e}")

        # Return the response object directly
        return response

    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return {"error": str(e)}, 500


def retry_with_app_relaunch(func, server_instance, *args, **kwargs):
    """Helper function to retry operations with app relaunch.

    Args:
        func: The function to retry
        server_instance: The AutomationServer instance
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The result from the function or a formatted error response
    """
    max_retries = 2
    start_time = time.time()
    last_error = None

    def format_response(result):
        """Format response with time taken"""
        time_taken = round(time.time() - start_time, 3)

        # Handle Flask Response objects (e.g., from serve_image)
        import flask
        from flask import Response

        if isinstance(result, (flask.Response, Response)):
            return result

        if isinstance(result, tuple) and len(result) == 2:
            response, status_code = result
            if isinstance(response, dict):
                response["time_taken"] = time_taken
            return response, status_code
        elif isinstance(result, dict):
            result["time_taken"] = time_taken
            return result, 200
        return result

    def restart_driver():
        """Restart the Appium driver for the current email"""
        # Get sindarin_email using our utility function with fallbacks
        sindarin_email = get_email_with_fallbacks(server_instance)

        if not sindarin_email:
            logger.error("No email found to restart driver")
            return False

        # No longer setting current_email as it has been removed

        # Check if we have an automator for this email
        if sindarin_email not in server_instance.automators or not server_instance.automators[sindarin_email]:
            logger.info(f"Initializing automator for {sindarin_email}")
            automator = server_instance.initialize_automator(sindarin_email)
            return automator.initialize_driver() if automator else False

        # Clean up existing automator
        automator = server_instance.automators[sindarin_email]
        if automator:
            automator.cleanup()
            server_instance.automators[sindarin_email] = None

        # Initialize new automator
        automator = server_instance.initialize_automator(sindarin_email)
        return automator.initialize_driver() if automator else False

    def restart_emulator():
        """Restart the emulator if it's not running properly"""
        logger.info("Restarting emulator due to device list error")

        # Get sindarin_email using our utility function with fallbacks
        sindarin_email = get_email_with_fallbacks(server_instance)

        if not sindarin_email:
            logger.error("No email found to restart emulator")
            return False

        # No longer setting current_email as it has been removed

        logger.info(f"Attempting to restart emulator for profile: {sindarin_email}")
        # Force a new emulator to be created
        success, _ = server_instance.switch_profile(sindarin_email, force_new_emulator=True)

        # Initialize automator
        if success:
            logger.info(f"Initializing automator after emulator restart for {sindarin_email}")
            automator = server_instance.initialize_automator(sindarin_email)
            if automator:
                automator.initialize_driver()

        return success

    def is_uiautomator_crash(error):
        """Check if the error is a UiAutomator2 server crash"""
        return isinstance(
            error, selenium_exceptions.WebDriverException
        ) and "cannot be proxied to UiAutomator2 server because the instrumentation process is not running" in str(
            error
        )

    def is_emulator_missing(error):
        """Check if the error indicates the emulator is not running"""
        error_str = str(error)
        return (
            "Failed to get devices list after multiple attempts" in error_str
            or "'NoneType' object has no attribute 'update_current_state'" in error_str
            or "Failed to initialize driver" in error_str
        )

    # Main retry loop
    for attempt in range(max_retries):
        try:
            # Restart driver for retry attempts
            if attempt > 0:
                logger.info(f"Retry attempt {attempt + 1}/{max_retries}")
                if not restart_driver():
                    logger.error("Failed to initialize driver during retry")
                    continue

            # Execute function
            result = func(*args, **kwargs)

            # Check for error status codes
            if isinstance(result, tuple) and len(result) == 2:
                response, status_code = result
                # Don't retry authentication errors with incorrect password
                if isinstance(response, dict) and response.get("error_type") == "incorrect_password":
                    logger.info(
                        "Authentication failed with incorrect password - won't retry and returning directly"
                    )
                    return format_response(result)
                # Don't retry authentication required errors
                elif (
                    status_code == 401
                    and isinstance(response, dict)
                    and response.get("requires_auth") == True
                ):
                    logger.info("Authentication required - returning directly without retry")
                    return format_response(result)
                # Don't retry auth operations with recreate flag to avoid double recreation
                elif (
                    isinstance(response, dict)
                    and func.__name__ == "post"
                    and hasattr(args[0], "__class__")
                    and args[0].__class__.__name__ == "AuthResource"
                ):
                    # Check if this is an auth endpoint with recreate flag
                    try:
                        request_json = args[0].request.get_json(silent=True) or {}
                        if request_json.get("recreate", 0) == 1:
                            logger.info(
                                "Auth with recreate=1 operation - skipping retry to avoid double recreation"
                            )
                            return format_response(result)
                    except Exception as e:
                        logger.warning(f"Error checking for recreate flag: {e}")

                    # Also skip retry for other auth issues to avoid duplicate auth attempts
                    logger.info("Auth operation - avoiding retry for authentication stability")
                    return format_response(result)
                # Special case: Don't retry captcha responses (403 with captcha_required)
                elif (
                    status_code == 403
                    and isinstance(response, dict)
                    and response.get("status") == "captcha_required"
                ):
                    logger.info("Captcha required response - passing through without retry")
                    return format_response(result)
                elif status_code >= 400:
                    # For other errors, include status_code in the response to maintain it through retries
                    response_with_code = response
                    if isinstance(response, dict):
                        response_with_code = response.copy()
                        response_with_code["status_code"] = status_code
                    raise Exception(response_with_code)

            # Success case - format and return the result
            return format_response(result)

        except Exception as e:
            last_error = e

            # Special handling for UiAutomator2 server crash
            if is_uiautomator_crash(e):
                logger.warning(
                    f"UiAutomator2 server crashed on attempt {attempt + 1}/{max_retries}. Restarting driver..."
                )

                # Try to restart the driver and immediately retry once more
                if restart_driver():
                    logger.info("Successfully restarted driver after UiAutomator2 crash")
                    try:
                        logger.info("Retrying operation after UiAutomator2 crash recovery")
                        result = func(*args, **kwargs)
                        return format_response(result)
                    except Exception as retry_error:
                        logger.error(f"Retry after UiAutomator2 recovery failed: {retry_error}")
                        last_error = retry_error
                else:
                    logger.error("Failed to reinitialize driver after UiAutomator2 crash")
            # Special handling for emulator not running or device list error
            elif is_emulator_missing(e):
                logger.warning(
                    f"Emulator not running on attempt {attempt + 1}/{max_retries}. Restarting emulator..."
                )

                # Try to restart the emulator and immediately retry once more
                if restart_emulator():
                    logger.info("Successfully restarted emulator, now restarting driver")
                    if restart_driver():
                        logger.info("Successfully restarted driver after emulator restart")
                        try:
                            logger.info("Retrying operation after emulator and driver restart")
                            result = func(*args, **kwargs)
                            return format_response(result)
                        except Exception as retry_error:
                            logger.error(f"Retry after emulator restart failed: {retry_error}")
                            last_error = retry_error
                    else:
                        logger.error("Failed to reinitialize driver after emulator restart")
                else:
                    logger.error("Failed to restart emulator")
            else:
                # Regular error handling for other types of crashes
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

            # Check if we should continue with another attempt
            if attempt < max_retries - 1:
                time.sleep(1)  # Wait before retry
                continue

    # If we reach here, all retries failed
    time_taken = round(time.time() - start_time, 3)
    logger.error(f"All retry attempts failed. Last error: {last_error}")

    # Check if the error is a dictionary response (likely from our API)
    if (
        isinstance(last_error, Exception)
        and str(last_error).startswith("{")
        and str(last_error).endswith("}")
    ):
        try:
            # Import json here to avoid circular imports
            import json

            error_dict = json.loads(str(last_error).replace("'", '"'))
            # Merge error_dict with time_taken
            error_dict["time_taken"] = time_taken
            return error_dict, 500 if "status_code" not in error_dict else error_dict.pop("status_code")
        except Exception as parse_error:
            # If parsing fails, log and fall back to string representation
            logger.error(f"Failed to parse error as JSON: {parse_error}")

    return {"error": str(last_error), "time_taken": time_taken}, 500


def handle_automator_response(server_instance):
    """Decorator to standardize response handling for automator endpoints.

    Handles special cases like CAPTCHA requirements and ensures consistent
    response format across all endpoints. Includes retry logic with app relaunch.
    Also captures diagnostic snapshots before and after operations.
    Works with the multi-emulator approach.

    Args:
        server_instance: The AutomationServer instance containing the automators
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # Get the operation name from the function
            operation_name = f.__name__
            if operation_name.startswith("_"):
                operation_name = operation_name[1:]  # Remove leading underscore

            # Get sindarin_email using our utility function with fallbacks
            sindarin_email = get_email_with_fallbacks(server_instance)

            # Get the appropriate automator instance
            automator = None
            if sindarin_email and hasattr(server_instance, "automators"):
                automator = server_instance.automators.get(sindarin_email)

            # For backward compatibility
            if not automator and hasattr(server_instance, "automator"):
                automator = server_instance.automator

            # No longer taking pre-operation snapshots to improve performance

            try:
                # Wrap the function call in retry logic
                def wrapped_func():
                    # Get the original response from the endpoint
                    response = f(*args, **kwargs)

                    # Handle Flask Response objects directly
                    import flask
                    from flask import Response

                    if isinstance(response, (flask.Response, Response)):
                        return response

                    # If response is already a tuple with status code, unpack it
                    if isinstance(response, tuple):
                        result, status_code = response
                    else:
                        result, status_code = response, 200

                    # No longer taking post-operation snapshots to improve performance

                    # Check for Title Not Available error
                    if automator and hasattr(automator, "title_not_available_error"):
                        time_taken = round(time.time() - start_time, 3)
                        error_info = automator.title_not_available_error

                        logger.error(
                            f"Title Not Available error detected for book: {error_info.get('book_title', 'Unknown')}"
                        )

                        # Create response with error details
                        response_data = {
                            "error": error_info.get("error", "Title Not Available"),
                            "book_title": error_info.get("book_title", "Unknown"),
                            "time_taken": time_taken,
                            "status": "title_not_available",
                        }

                        # Clear the error flag to avoid affecting future requests
                        automator.title_not_available_error = None

                        return response_data, 400

                    # Check for special states that need handling
                    if automator and hasattr(automator, "state_machine") and automator.state_machine:
                        current_state = automator.state_machine.current_state

                        # Handle CAPTCHA state
                        if current_state == AppState.CAPTCHA:
                            time_taken = round(time.time() - start_time, 3)

                            # Get the screenshot ID directly from the state machine
                            # This comes from the auth handler's captured screenshot during captcha processing
                            screenshot_id = automator.state_machine.get_captcha_screenshot_id()

                            # Default fallback URL - use image endpoint for consistent access
                            image_url = "/image/captcha"

                            # Use the captured screenshot ID if available
                            if screenshot_id:
                                image_url = f"/image/{screenshot_id}"
                                logger.info(f"Using captcha screenshot from auth handler: {image_url}")
                            else:
                                logger.info(
                                    f"No captcha screenshot ID found, using fallback URL: {image_url}"
                                )

                            # Check if we have an interactive captcha
                            interactive_captcha = False
                            if hasattr(automator.state_machine.auth_handler, "interactive_captcha_detected"):
                                interactive_captcha = (
                                    automator.state_machine.auth_handler.interactive_captcha_detected
                                )

                            # Create response body with appropriate message
                            response_data = {
                                "status": "captcha_required",
                                "time_taken": time_taken,
                                "image_url": image_url,
                            }

                            if interactive_captcha:
                                response_data[
                                    "message"
                                ] = "Grid-based image captcha detected - app has been restarted automatically"
                                response_data["captcha_type"] = "grid"
                                response_data["requires_restart"] = True
                            else:
                                response_data["message"] = "Authentication requires captcha solution"
                                response_data["captcha_type"] = "text"

                            return response_data, 403

                    # Check if this is a known authentication error that shouldn't be retried
                    if isinstance(result, dict) and result.get("error_type") == "incorrect_password":
                        logger.info("Authentication failed with incorrect password - won't retry")
                        return result, status_code

                    # Return original response if no special handling needed
                    return result, status_code

                return retry_with_app_relaunch(wrapped_func, server_instance)

            except Exception as e:
                time_taken = round(time.time() - start_time, 3)
                logger.error(f"Error in endpoint {operation_name}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

                # We still take error snapshots for debugging
                if automator and hasattr(automator, "driver") and automator.driver:
                    try:
                        automator.take_diagnostic_snapshot(f"error_{operation_name}")
                    except Exception as snap_e:
                        logger.warning(f"Failed to take error snapshot for {operation_name}: {snap_e}")

                return {"error": str(e), "time_taken": time_taken}, 500

        return wrapper

    return decorator
