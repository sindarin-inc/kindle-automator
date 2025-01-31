import logging
import traceback
from functools import wraps

from views.core.app_state import AppState

logger = logging.getLogger(__name__)


def handle_automator_response(server_instance):
    """Decorator to standardize response handling for automator endpoints.

    Handles special cases like CAPTCHA requirements and ensures consistent
    response format across all endpoints.

    Args:
        server_instance: The AutomationServer instance containing the automator
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
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
                        return {
                            "status": "captcha_required",
                            "message": "Authentication requires captcha solution",
                            "image_url": "/screenshots/captcha.png",
                        }, 403

                    # Could add other special states here (2FA, etc)

                # Return original response if no special handling needed
                return result, status_code

            except Exception as e:
                logger.error(f"Error in endpoint: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return {"error": str(e)}, 500

        return wrapper

    return decorator
