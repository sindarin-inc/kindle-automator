import logging
import time
import traceback
from functools import wraps

from selenium.common import exceptions as selenium_exceptions

from views.core.app_state import AppState

logger = logging.getLogger(__name__)


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
        """Restart the Appium driver"""
        if not server_instance.automator:
            server_instance.initialize_automator()
            return server_instance.automator.initialize_driver()

        server_instance.automator.cleanup()
        server_instance.initialize_automator()
        return server_instance.automator.initialize_driver()
    
    def restart_emulator():
        """Restart the emulator if it's not running properly"""
        logger.info("Restarting emulator due to device list error")
        current_profile = server_instance.profile_manager.get_current_profile()
        if current_profile and "email" in current_profile:
            email = current_profile["email"]
            logger.info(f"Attempting to restart emulator for profile: {email}")
            # Force a new emulator to be created
            server_instance.switch_profile(email, force_new_emulator=True)
            return True
        else:
            logger.error("No current profile found for restarting emulator")
            return False

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
        return "Failed to get devices list after multiple attempts" in error_str

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

    Args:
        server_instance: The AutomationServer instance containing the automator
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # Get the operation name from the function
            operation_name = f.__name__
            if operation_name.startswith("_"):
                operation_name = operation_name[1:]  # Remove leading underscore

            # Take diagnostic snapshot before operation if driver is ready
            if server_instance.automator and server_instance.automator.driver:
                try:
                    server_instance.automator.take_diagnostic_snapshot(f"pre_{operation_name}")
                except Exception as snap_e:
                    logger.warning(f"Failed to take pre-operation snapshot for {operation_name}: {snap_e}")

            try:
                # Wrap the function call in retry logic
                def wrapped_func():
                    # Get the original response from the endpoint
                    response = f(*args, **kwargs)

                    # If response is already a tuple with status code, unpack it
                    if isinstance(response, tuple):
                        result, status_code = response
                    else:
                        result, status_code = response, 200

                    # Get automator from server instance
                    automator = server_instance.automator

                    # Take diagnostic snapshot after successful operation
                    if automator and automator.driver and status_code < 400:
                        try:
                            automator.take_diagnostic_snapshot(f"post_{operation_name}")
                        except Exception as snap_e:
                            logger.warning(
                                f"Failed to take post-operation snapshot for {operation_name}: {snap_e}"
                            )

                    # Check for special states that need handling
                    if automator and automator.state_machine:
                        current_state = automator.state_machine.current_state

                        # Handle CAPTCHA state
                        if current_state == AppState.CAPTCHA:
                            time_taken = round(time.time() - start_time, 3)
                            return {
                                "status": "captcha_required",
                                "message": "Authentication requires captcha solution",
                                "image_url": "/screenshots/captcha.png",
                                "time_taken": time_taken,
                            }, 403

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

                # Take diagnostic snapshot on error if the driver is still alive
                if server_instance.automator and server_instance.automator.driver:
                    try:
                        server_instance.automator.take_diagnostic_snapshot(f"error_{operation_name}")
                    except Exception as snap_e:
                        logger.warning(f"Failed to take error snapshot for {operation_name}: {snap_e}")

                return {"error": str(e), "time_taken": time_taken}, 500

        return wrapper

    return decorator
