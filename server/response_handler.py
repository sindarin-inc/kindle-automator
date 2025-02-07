import logging
import time
import traceback
from functools import wraps

from views.core.app_state import AppState

logger = logging.getLogger(__name__)


def retry_with_app_relaunch(func, server_instance, *args, **kwargs):
    """Helper function to retry operations with app relaunch.

    Args:
        func: The function to retry
        server_instance: The AutomationServer instance
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The result from the function or raises the last error encountered
    """
    max_retries = 1
    last_error = None
    start_time = time.time()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.info(f"Retry attempt {attempt + 1}/{max_retries}")
                # Cleanup and reinitialize automator
                if server_instance.automator:
                    server_instance.automator.cleanup()
                server_instance.initialize_automator()

            result = func(*args, **kwargs)

            # If result is a tuple with error status code, retry
            if isinstance(result, tuple) and len(result) == 2:
                response, status_code = result
                if status_code >= 400:
                    raise Exception(f"Request failed with status {status_code}: {response}")

            # Add time taken to response
            time_taken = round(time.time() - start_time, 3)
            if isinstance(result, tuple):
                response, status_code = result
                if isinstance(response, dict):
                    response["time_taken"] = time_taken
                return response, status_code
            elif isinstance(result, dict):
                result["time_taken"] = time_taken
            return result

        except Exception as e:
            last_error = e
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

            if attempt < max_retries - 1:
                time.sleep(1)  # Wait before retry
                continue
            else:
                time_taken = round(time.time() - start_time, 3)
                logger.error(f"All retry attempts failed. Last error: {last_error}")
                return {"error": str(last_error), "time_taken": time_taken}, 500


def handle_automator_response(server_instance):
    """Decorator to standardize response handling for automator endpoints.

    Handles special cases like CAPTCHA requirements and ensures consistent
    response format across all endpoints. Includes retry logic with app relaunch.

    Args:
        server_instance: The AutomationServer instance containing the automator
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            start_time = time.time()
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

                    # Return original response if no special handling needed
                    return result, status_code

                return retry_with_app_relaunch(wrapped_func, server_instance)

            except Exception as e:
                time_taken = round(time.time() - start_time, 3)
                logger.error(f"Error in endpoint: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return {"error": str(e), "time_taken": time_taken}, 500

        return wrapper

    return decorator
