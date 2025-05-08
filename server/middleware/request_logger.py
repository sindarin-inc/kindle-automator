import copy
import json
import logging
from functools import wraps
from io import BytesIO

from flask import Response, current_app, g, request

from server.utils.ansi_colors import BRIGHT_WHITE, DIM_YELLOW, GREEN, MAGENTA, RESET
from server.logging_config import get_email_logger, set_current_request_email
from server.utils.request_utils import get_request_logger, get_sindarin_email

logger = logging.getLogger(__name__)


class RequestBodyLogger:
    """Middleware for logging Flask request and response bodies."""

    @staticmethod
    def sanitize_sensitive_data(data):
        """Remove sensitive information from data before logging."""
        if not isinstance(data, dict):
            return data

        # Create a deep copy to avoid modifying the original data
        sanitized = copy.deepcopy(data)

        # List of sensitive keys to mask
        sensitive_keys = [
            "password",
            "token",
            "secret",
            "key",
            "auth",
            "credential",
            "access_token",
            "refresh_token",
            "code",
        ]

        for key in sanitized:
            if any(sensitive_word in key.lower() for sensitive_word in sensitive_keys):
                if sanitized[key]:  # Only redact if there's a value
                    sanitized[key] = "[REDACTED]"
            # Also sanitize nested dictionaries
            elif isinstance(sanitized[key], dict):
                sanitized[key] = RequestBodyLogger.sanitize_sensitive_data(sanitized[key])
            # And sanitize lists of dictionaries
            elif isinstance(sanitized[key], list) and sanitized[key] and isinstance(sanitized[key][0], dict):
                sanitized[key] = [
                    RequestBodyLogger.sanitize_sensitive_data(item) if isinstance(item, dict) else item
                    for item in sanitized[key]
                ]

        return sanitized

    @staticmethod
    def log_request():
        """Log the request body."""
        request_data = None

        # Get server instance from the Flask app
        server_instance = current_app.config.get("server_instance", None)
        user_info = ""

        # Get the email from the request
        request_email = get_sindarin_email()

        # Get the appropriate logger - either email-specific or standard
        request_logger = get_request_logger()

        if server_instance:
            email = request_email or "not_authenticated"

            # Get the AVD name specifically for this email, not just the current profile
            if request_email and hasattr(server_instance, "profile_manager"):
                avd_name = server_instance.profile_manager.get_avd_for_email(request_email) or "none"
            else:
                # Fallback to current profile
                current_profile = (
                    server_instance.profile_manager.get_current_profile()
                    if hasattr(server_instance, "profile_manager")
                    else None
                )
                avd_name = current_profile.get("avd_name", "none") if current_profile else "none"

            user_info = f" {GREEN}[User: {email} | AVD: {avd_name}]{RESET}"

        # For GET requests, use query parameters as the body
        if request.method == "GET" and request.args:
            request_data = RequestBodyLogger.sanitize_sensitive_data(dict(request.args))
        elif request.is_json:
            try:
                request_data = request.get_json()
                # Sanitize sensitive data
                request_data = RequestBodyLogger.sanitize_sensitive_data(request_data)
            except Exception as e:
                request_logger.error(f"Error parsing JSON request: {e}")
                request_data = "Invalid JSON"
        elif request.form:
            request_data = RequestBodyLogger.sanitize_sensitive_data(request.form.to_dict())
        elif request.data:
            try:
                raw_data = request.data.decode("utf-8")
                # Try to parse as JSON to sanitize
                try:
                    json_data = json.loads(raw_data)
                    if isinstance(json_data, dict):
                        request_data = RequestBodyLogger.sanitize_sensitive_data(json_data)
                    else:
                        request_data = raw_data
                except json.JSONDecodeError:
                    request_data = raw_data
            except UnicodeDecodeError:
                request_data = f"Binary data ({len(request.data)} bytes)"

        if request_data:
            if isinstance(request_data, (dict, list)):
                json_str = json.dumps(request_data, default=str)
                if len(json_str) > 500:
                    request_logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                    )
                else:
                    request_logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str}{RESET}"
                    )
            elif isinstance(request_data, str) and len(request_data) > 500:
                request_logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{request_data[:500]}{RESET}... (truncated, total {len(request_data)} bytes)"
                )
            else:
                request_logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{request_data}{RESET}"
                )
        else:
            request_logger.info(
                f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: No body"
            )

    @staticmethod
    def log_response(response):
        """Log the response body."""
        response_data = None

        # Get server instance from the Flask app
        server_instance = current_app.config.get("server_instance", None)
        user_info = ""

        # Get the email from the request
        request_email = get_sindarin_email()

        # Get the appropriate logger - either email-specific or standard
        request_logger = get_request_logger()

        if server_instance:
            email = request_email or "not_authenticated"

            # Get the AVD name specifically for this email, not just the current profile
            if request_email and hasattr(server_instance, "profile_manager"):
                avd_name = server_instance.profile_manager.get_avd_for_email(request_email) or "none"
            else:
                # Fallback to current profile
                current_profile = (
                    server_instance.profile_manager.get_current_profile()
                    if hasattr(server_instance, "profile_manager")
                    else None
                )
                avd_name = current_profile.get("avd_name", "none") if current_profile else "none"

            user_info = f" {GREEN}[User: {email} | AVD: {avd_name}]{RESET}"

        if response.direct_passthrough:
            request_logger.info(
                f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}Direct passthrough (file/image){RESET}"
            )
            return response

        # Store original response data
        original_data = response.get_data()

        # Try to decode and parse JSON
        try:
            response_text = original_data.decode("utf-8")
            try:
                # Parse and sanitize JSON data
                response_data = json.loads(response_text)

                # Sanitize sensitive data if it's a dictionary
                if isinstance(response_data, dict):
                    sanitized_data = RequestBodyLogger.sanitize_sensitive_data(response_data)
                    json_str = json.dumps(sanitized_data, default=str)
                    if len(json_str) > 500:
                        request_logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        request_logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str}{RESET}"
                        )
                else:
                    json_str = json.dumps(response_data, default=str)
                    if len(json_str) > 500:
                        request_logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        request_logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{json_str}{RESET}"
                        )
            except json.JSONDecodeError:
                if len(response_text) > 500:
                    request_logger.info(
                        f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{response_text[:500]}{RESET}... (truncated, total {len(response_text)} bytes)"
                    )
                else:
                    request_logger.info(
                        f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}{response_text}{RESET}"
                    )
        except UnicodeDecodeError:
            request_logger.info(
                f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]{user_info}: {DIM_YELLOW}Binary data ({len(original_data)} bytes){RESET}"
            )

        return response


def setup_request_logger(app):
    """Set up request/response logging for Flask app.
    
    This also configures a request context for logging that makes all log
    messages during a request go to the email-specific logger for that request.
    """

    @app.before_request
    def before_request():
        # Get the email from the request
        email = get_sindarin_email()
        
        # Store the email in flask.g for this request
        g.request_email = email
        
        # Set the email in thread-local storage for the request
        # This will be used by the DynamicEmailHandler to route logs
        if email:
            set_current_request_email(email)
            logger.debug(f"Set up email logging context for {email} in request: {request.path}")
        
        # Log the request details
        RequestBodyLogger.log_request()

    @app.after_request
    def after_request(response):
        # Log the response details
        response_with_logs = RequestBodyLogger.log_response(response)
        
        # Clear the thread-local storage at the end of the request
        # Set to None instead of deleting to avoid attribute errors
        set_current_request_email(None)
        
        return response_with_logs
