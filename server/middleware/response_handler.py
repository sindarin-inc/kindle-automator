import logging
import os
import subprocess
import time
import traceback
from functools import wraps
from typing import Optional

from flask import Response, current_app, make_response, send_file
from selenium.common import exceptions as selenium_exceptions

from server.utils.request_utils import get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


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


def retry_with_app_relaunch(func, server_instance, start_time=None, *args, **kwargs):
    """Helper function to retry operations with app relaunch.

    Args:
        func: The function to retry
        server_instance: The AutomationServer instance
        start_time: Optional start time from the parent function for accurate timing
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The result from the function or a formatted error response
    """
    max_retries = 2
    if start_time is None:
        start_time = time.time()
    logger.info(f"Starting retry loop for {func.__name__}, time_taken start time: {start_time}")
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
        # Get sindarin_email from request
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.error("No email found to restart driver")
            return False

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

        # Get sindarin_email from request
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            logger.error("No email found to restart emulator")
            return False

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
        """Check if the error is a UiAutomator2 server crash or lost session"""
        error_str = str(error)
        return (
            (
                isinstance(error, selenium_exceptions.WebDriverException)
                and "cannot be proxied to UiAutomator2 server because the instrumentation process is not running"
                in error_str
            )
            or ("The session identified by" in error_str and "is not known" in error_str)
            or "NoSuchDriverException" in error_str
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
                # Special case: Don't retry captcha responses
                elif (
                    status_code == 403
                    and isinstance(response, dict)
                    and (
                        response.get("status") == "captcha_detected"
                        or "captcha" in str(response.get("error", "")).lower()
                    )
                ):
                    logger.info("Captcha detected response - passing through without retry")
                    return format_response(result)
                elif status_code >= 400:
                    # Client errors (4xx) should not be retried
                    if 400 <= status_code < 500:
                        logger.info(f"Client error {status_code} - not retrying")
                        return format_response((response, status_code))
                    # Server errors (5xx) should be retried
                    else:
                        # For server errors, include status_code in the response to maintain it through retries
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


def _get_timezone_from_request():
    """Extract timezone parameter from request (query params, JSON body, or form data).

    Returns:
        Optional[str]: The timezone string if provided and valid, None otherwise
    """
    from flask import has_request_context, request

    if not has_request_context():
        return None

    # Check URL query parameters first
    timezone = request.args.get("timezone")
    if timezone and isinstance(timezone, str) and timezone.strip():
        return timezone.strip()

    # Check JSON body
    if request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            timezone = json_data.get("timezone")
            # Ensure it's a non-empty string
            if timezone and isinstance(timezone, str) and timezone.strip():
                return timezone.strip()
        except Exception as e:
            logger.warning(f"Error parsing JSON for timezone parameter: {e}")

    # Check form data
    timezone = request.form.get("timezone")
    if timezone and isinstance(timezone, str) and timezone.strip():
        return timezone.strip()

    return None


def _apply_timezone_to_device(server_instance, sindarin_email: str, timezone: str) -> bool:
    """Apply timezone setting to the Android device using ADB.

    Args:
        server_instance: The AutomationServer instance
        sindarin_email: The user's email
        timezone: The timezone to set (e.g., "America/Chicago")

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the automator for this email
        automator = server_instance.automators.get(sindarin_email)
        if not automator:
            logger.warning(f"No automator found for {sindarin_email}, cannot apply timezone")
            return False

        device_id = automator.device_id
        android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        adb_path = os.path.join(android_home, "platform-tools", "adb")

        # Set timezone using setprop command
        cmd = [adb_path, "-s", device_id, "shell", "setprop", "persist.sys.timezone", timezone]
        logger.info(f"Setting timezone for {sindarin_email} on device {device_id}: {timezone}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            logger.error(f"Failed to set timezone: {result.stderr}")
            return False

        # Broadcast the time change to ensure apps pick it up
        broadcast_cmd = [
            adb_path,
            "-s",
            device_id,
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.TIME_SET",
        ]
        subprocess.run(broadcast_cmd, capture_output=True, text=True, timeout=5)

        logger.info(f"Successfully set timezone to {timezone} for {sindarin_email}")
        return True

    except Exception as e:
        logger.error(f"Error applying timezone to device: {e}")
        return False


def _handle_timezone_parameter(server_instance, sindarin_email: Optional[str]):
    """Check for timezone parameter in request and handle it if present.

    Args:
        server_instance: The AutomationServer instance
        sindarin_email: The user's email
    """
    if not sindarin_email:
        return

    # Check if timezone is provided in the request
    timezone = _get_timezone_from_request()

    # Ensure timezone is not None, empty string, or just whitespace
    if timezone and timezone.strip():
        timezone = timezone.strip()  # Remove any leading/trailing whitespace
        logger.info(f"Timezone parameter detected: {timezone} for {sindarin_email}")

        try:
            # Get the profile manager instance
            from views.core.avd_profile_manager import AVDProfileManager

            profile_manager = AVDProfileManager.get_instance()

            # Get the current timezone from the profile
            current_timezone = profile_manager.get_user_field(sindarin_email, "timezone")

            # Only update if timezone is different
            if current_timezone != timezone:
                logger.info(f"Timezone changed from {current_timezone} to {timezone} for {sindarin_email}")

                # Save the timezone to the user's profile
                success = profile_manager.set_user_field(sindarin_email, "timezone", timezone)

                if success:
                    logger.info(f"Saved timezone {timezone} for {sindarin_email}")

                    # Apply timezone to the device
                    if _apply_timezone_to_device(server_instance, sindarin_email, timezone):
                        logger.info(f"Applied timezone {timezone} to device for {sindarin_email}")
                    else:
                        logger.warning(f"Failed to apply timezone to device for {sindarin_email}")
                else:
                    logger.error(f"Failed to save timezone for {sindarin_email}")
            else:
                logger.debug(f"Timezone unchanged ({timezone}) for {sindarin_email}, skipping device update")

        except Exception as e:
            logger.error(f"Error handling timezone parameter: {e}")


def handle_automator_response(f):
    """Decorator to standardize response handling for automator endpoints.

    Handles special cases like CAPTCHA requirements and ensures consistent
    response format across all endpoints. Includes retry logic with app relaunch.
    Also captures diagnostic snapshots before and after operations.
    Works with the multi-emulator approach.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        # Try to get start time from request context first (set by request logger middleware)
        from flask import g, request

        start_time = getattr(g, "request_start_time", None)
        if start_time is None:
            # Fallback to current time if not available
            start_time = time.time()
            logger.debug("Request start time not found in g, using current time")

        # Get server instance from request context
        server_instance = current_app.config.get("server_instance")
        if server_instance is None:
            logger.error("No server instance found in app config")
            return {"error": "Server configuration error"}, 500

        # Get the operation name from the function
        operation_name = f.__name__
        if operation_name.startswith("_"):
            operation_name = operation_name[1:]  # Remove leading underscore

        # Get sindarin_email from request
        sindarin_email = get_sindarin_email()

        # Check if timezone parameter is provided in the request
        _handle_timezone_parameter(server_instance, sindarin_email)

        # Get the appropriate automator instance
        automator = None
        if sindarin_email:
            automator = server_instance.automators.get(sindarin_email)

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

                # Check for special states that need handling
                if automator and hasattr(automator, "state_machine") and automator.state_machine:
                    current_state = automator.state_machine.current_state

                    # Handle LIBRARY_SIGN_IN state - lost auth token
                    if current_state == AppState.LIBRARY_SIGN_IN:
                        # Check if user was previously authenticated (has auth_date)
                        profile_manager = automator.profile_manager
                        auth_date = profile_manager.get_user_field(sindarin_email, "auth_date")

                        # Only return auth error if user was previously authenticated
                        if auth_date:
                            logger.info(f"User {sindarin_email} was previously authenticated on {auth_date}")
                            time_taken = round(time.time() - start_time, 3)

                            logger.warning(
                                f"LIBRARY_SIGN_IN state detected - auth token lost for {sindarin_email}, "
                                f"was authenticated on {auth_date}, manual login required"
                            )

                            # Get the emulator ID for this email
                            emulator_id = automator.emulator_manager.emulator_launcher.get_emulator_id(
                                sindarin_email
                            )
                            logger.info(f"Using emulator ID {emulator_id} for {sindarin_email}")

                            return {
                                "error": "Authentication token lost",
                                "requires_auth": True,
                                "manual_login_required": True,  # Keep for backwards compatibility
                                "current_state": current_state.name,
                                "message": "Your Kindle authentication token was lost. Authentication is required via VNC. This may require a cold boot restart.",
                                "emulator_id": emulator_id,
                                "time_taken": time_taken,
                                "previous_auth_date": auth_date,
                                "auth_token_lost": True,
                            }, 401
                        else:
                            logger.info(
                                f"LIBRARY_SIGN_IN state detected but user {sindarin_email} has no auth_date - not treating as lost auth"
                            )

                    # Handle CAPTCHA state
                    if current_state == AppState.CAPTCHA:
                        time_taken = round(time.time() - start_time, 3)

                        # Create response body for CAPTCHA detection
                        response_data = {
                            "status": "captcha_detected",
                            "time_taken": time_taken,
                            "error": "CAPTCHA detected - manual intervention required via VNC",
                            "requires_auth": True,
                            "requires_manual_intervention": True,  # Keep for backwards compatibility
                            "message": "Please complete the CAPTCHA manually via VNC",
                        }

                        return response_data, 403

                # Check if this is a known authentication error that shouldn't be retried
                if isinstance(result, dict) and result.get("error_type") == "incorrect_password":
                    logger.info("Authentication failed with incorrect password - won't retry")
                    return result, status_code

                # Check if we need to add timezone_missing flag
                if isinstance(result, dict) and sindarin_email:
                    # Get the profile manager instance
                    try:
                        from views.core.avd_profile_manager import AVDProfileManager

                        profile_manager = AVDProfileManager.get_instance()

                        # Check if timezone exists in the user's profile
                        timezone = profile_manager.get_user_field(sindarin_email, "timezone")
                        logger.debug(f"Timezone check for {sindarin_email}: {timezone}")
                        if timezone is None:
                            logger.info(f"Adding timezone_missing flag for {sindarin_email}")
                            result["timezone_missing"] = True
                    except Exception as e:
                        logger.warning(f"Error checking timezone for {sindarin_email}: {e}")

                # Add time_taken to successful responses if it's a dict
                if isinstance(result, dict):
                    time_taken = round(time.time() - start_time, 3)
                    result["time_taken"] = time_taken

                # Return original response if no special handling needed
                return result, status_code

            return retry_with_app_relaunch(wrapped_func, server_instance, start_time)

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
