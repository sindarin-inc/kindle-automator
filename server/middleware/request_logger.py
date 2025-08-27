import copy
import json
import logging
import time
from functools import wraps
from io import BytesIO

import sentry_sdk
from flask import Response, current_app, g, request
from user_agents import parse

# Removed set_current_request_email import as it's no longer needed
from server.utils.ansi_colors import (
    BLUE,
    BRIGHT_WHITE,
    DIM_YELLOW,
    GREEN,
    MAGENTA,
    RED,
    RESET,
)
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class RequestBodyLogger:
    """Middleware for logging Flask request and response bodies."""

    @staticmethod
    def get_ua_identifier(ua_string):
        """Parse user agent string and return a short identifier."""
        if not ua_string:
            return "unknown"

        try:
            ua = parse(ua_string)

            # For mobile devices
            if ua.is_mobile:
                if ua.os.family == "iOS":
                    return "ios"
                elif ua.os.family == "Android":
                    return "android"

            # For desktop browsers
            if ua.is_pc:
                browser = ua.browser.family.lower() if ua.browser.family else ""
                os_family = ua.os.family.lower() if ua.os.family else ""

                if "edge" in browser:
                    return "edge"
                elif "safari" in browser and "mac" in os_family:
                    return "safari"
                elif "chrome" in browser:
                    if "mac" in os_family:
                        return "chrome-mac"
                    elif "windows" in os_family:
                        return "chrome-win"
                    elif "linux" in os_family:
                        return "chrome-linux"
                    else:
                        return "chrome"
                elif "firefox" in browser:
                    if "mac" in os_family:
                        return "firefox-mac"
                    elif "windows" in os_family:
                        return "firefox-win"
                    elif "linux" in os_family:
                        return "firefox-linux"
                    else:
                        return "firefox"

            # For bots/crawlers
            if ua.is_bot:
                return "bot"

            # For specific libraries
            if "python-requests" in ua_string:
                return "python-requests"
            elif "python-httpx" in ua_string:
                return "python-httpx"
            elif "curl" in ua_string.lower():
                return "curl"

            # Default fallback
            return "unknown"
        except Exception:
            return "unknown"

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

        # Get user agent
        user_agent = request.headers.get("User-Agent", "")
        ua_identifier = RequestBodyLogger.get_ua_identifier(user_agent)
        user_agent_info = f" {BLUE}[UA: {ua_identifier}]{RESET}"

        # For GET requests, use query parameters as the body
        if request.method == "GET" and request.args:
            request_data = RequestBodyLogger.sanitize_sensitive_data(dict(request.args))
        elif request.is_json:
            try:
                request_data = request.get_json()
                # Sanitize sensitive data
                request_data = RequestBodyLogger.sanitize_sensitive_data(request_data)
            except Exception:
                # Don't log error, just show the raw data
                try:
                    raw_data = request.data.decode("utf-8")
                    request_data = f"Invalid JSON: {raw_data}" if raw_data else "Invalid JSON: <empty body>"
                except UnicodeDecodeError:
                    request_data = f"Invalid JSON: Binary data ({len(request.data)} bytes)"
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
                if len(json_str) > 5000:
                    logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_agent_info}: {DIM_YELLOW}{json_str[:5000]}{RESET}... (truncated, total {len(json_str)} bytes)"
                    )
                else:
                    logger.info(
                        f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_agent_info}: {DIM_YELLOW}{json_str}{RESET}"
                    )
            elif isinstance(request_data, str) and len(request_data) > 5000:
                logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_agent_info}: {DIM_YELLOW}{request_data[:5000]}{RESET}... (truncated, total {len(request_data)} bytes)"
                )
            else:
                logger.info(
                    f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_agent_info}: {DIM_YELLOW}{request_data}{RESET}"
                )
        else:
            logger.info(
                f"REQUEST [{request.method} {MAGENTA}{request.path}{RESET}]{user_agent_info}: No body"
            )

    @staticmethod
    def log_response(response):
        """Log the response body."""
        response_data = None

        # Calculate elapsed time
        elapsed_time = ""
        if hasattr(g, "request_start_time"):
            elapsed = time.time() - g.request_start_time
            elapsed_time = f" {BLUE}{elapsed:.1f}s{RESET}"

        # Format status code with color
        status_code = response.status_code
        if 200 <= status_code < 300:
            status_color = GREEN
        elif 400 <= status_code < 500:
            status_color = BLUE
        else:  # 500+ and other codes
            status_color = RED
        status_info = f" {status_color}{status_code}{RESET}"

        if response.direct_passthrough:
            logger.info(
                f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}Direct passthrough (file/image){RESET}"
            )
            return response

        # Skip logging for streaming responses (SSE, etc.)
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type or response.is_streamed:
            logger.info(
                f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}Streaming response ({content_type}){RESET}"
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
                    if len(json_str) > 5000:
                        logger.info(
                            f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{json_str[:5000]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        logger.info(
                            f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{json_str}{RESET}"
                        )
                else:
                    json_str = json.dumps(response_data, default=str)
                    if len(json_str) > 5000:
                        logger.info(
                            f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{json_str[:5000]}{RESET}... (truncated, total {len(json_str)} bytes)"
                        )
                    else:
                        logger.info(
                            f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{json_str}{RESET}"
                        )
            except json.JSONDecodeError:
                if len(response_text) > 5000:
                    logger.info(
                        f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{response_text[:5000]}{RESET}... (truncated, total {len(response_text)} bytes)"
                    )
                else:
                    logger.info(
                        f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}{response_text}{RESET}"
                    )
        except UnicodeDecodeError:
            logger.info(
                f"RESPONSE{status_info} [{request.method} {MAGENTA}{request.path}{RESET}{elapsed_time}]: {DIM_YELLOW}Binary data ({len(original_data)} bytes){RESET}"
            )

        return response


def setup_request_logger(app):
    """Set up request/response logging for Flask app.

    This sets up middleware for:
    1. Storing the current request's email in flask.g.request_email
    2. Logging request and response details
    """

    @app.before_request
    def before_request():
        # Store the request start time for accurate timing
        g.request_start_time = time.time()

        # Get the email from the request
        email = get_sindarin_email()

        # Store the email in flask.g for this request
        g.request_email = email

        # Early request number assignment for logging visibility
        # This ensures request numbers appear in the initial REQUEST log line
        if email:
            from server.core.redis_connection import get_redis_client
            from server.core.request_manager import RequestManager

            # Only assign numbers for paths that use deduplication
            path = request.path if hasattr(request, "path") else "/"
            method = request.method if hasattr(request, "method") else "GET"

            # Skip for paths that don't deduplicate
            skip_paths = ["/staff-auth", "/staff-tokens"]
            if not any(path.startswith(skip) for skip in skip_paths) and method in ["GET", "POST"]:
                # Create a temporary request manager just to assign number
                temp_manager = RequestManager(email, path, method)
                request_number = temp_manager._assign_request_number()
                if request_number:
                    g.request_number = request_number
                    temp_manager._check_and_notify_multiple_requests()

                    # Only show numbers if this is request 2 or higher
                    # Request 1 shouldn't show [1] until request 2 arrives
                    redis_client = get_redis_client()
                    if redis_client:
                        if request_number >= 2:
                            # This is request 2 or higher, enable number display
                            g.show_request_number = True
                            # No need to set a separate flag - active_request_count already tracks this
                        else:
                            # This is request 1, don't show number yet
                            g.show_request_number = False

        # Set Sentry user context if email is available
        if email:
            sentry_sdk.set_user({"email": email})

        # Set request context for Sentry
        sentry_sdk.set_context(
            "request",
            {
                "method": request.method,
                "path": request.path,
                "endpoint": request.endpoint,
                "remote_addr": request.remote_addr,
            },
        )

        # Log the request details
        RequestBodyLogger.log_request()

    @app.after_request
    def after_request(response):
        # Log the response details
        response_with_logs = RequestBodyLogger.log_response(response)

        # Clear from g for safety (Flask automatically clears g after request)
        if hasattr(g, "request_email"):
            g.request_email = None

        return response_with_logs
