import copy
import json
import logging
from functools import wraps
from io import BytesIO

from flask import Response, g, request

from server.ansi_colors import BRIGHT_WHITE, DIM_YELLOW, MAGENTA, RESET

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
            "email",
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

        # For GET requests, use query parameters as the body
        if request.method == "GET" and request.args:
            request_data = RequestBodyLogger.sanitize_sensitive_data(dict(request.args))
        elif request.is_json:
            try:
                request_data = request.get_json()
                # Sanitize sensitive data
                request_data = RequestBodyLogger.sanitize_sensitive_data(request_data)
            except Exception as e:
                logger.error(f"Error parsing JSON request: {e}")
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
                    logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                    )
                else:
                    logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str}{RESET}"
                    )
            elif isinstance(request_data, str) and len(request_data) > 500:
                logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{request_data[:500]}{RESET}... (truncated, total {len(request_data)} bytes)"
                )
            else:
                logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{request_data}{RESET}"
                )
        else:
            logger.info(f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]: No body")

    @staticmethod
    def log_response(response):
        """Log the response body."""
        response_data = None

        if response.direct_passthrough:
            logger.info(
                f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}Direct passthrough (file/image){RESET}"
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
                        logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str}{RESET}"
                        )
                else:
                    json_str = json.dumps(response_data, default=str)
                    if len(json_str) > 500:
                        logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str[:500]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        logger.info(
                            f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{json_str}{RESET}"
                        )
            except json.JSONDecodeError:
                if len(response_text) > 500:
                    logger.info(
                        f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{response_text[:500]}{RESET}... (truncated, total {len(response_text)} bytes)"
                    )
                else:
                    logger.info(
                        f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}{response_text}{RESET}"
                    )
        except UnicodeDecodeError:
            logger.info(
                f"RESPONSE [{request.method} {MAGENTA}{request.path}{RESET}]: {DIM_YELLOW}Binary data ({len(original_data)} bytes){RESET}"
            )

        return response


def setup_request_logger(app):
    """Set up request/response logging for Flask app."""

    @app.before_request
    def before_request():
        RequestBodyLogger.log_request()

    @app.after_request
    def after_request(response):
        return RequestBodyLogger.log_response(response)
