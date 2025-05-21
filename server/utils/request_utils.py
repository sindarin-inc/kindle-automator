"""
Utility functions for processing requests and extracting user information.

This module provides functions to:
1. Extract email information from requests
2. Get email-specific loggers
3. Find the appropriate automator for a request
4. Build VNC URLs with proper user contexts

Usage:
    # Get the email from the current request
    email = get_sindarin_email()

    # Get a logger specific to the current request's email (or fall back to standard logger)
    request_logger = get_request_logger()

    # Get the automator for the current request
    automator, email, error = get_automator_for_request(server)
    
    # Set email override for operations outside request context
    with email_override("user@example.com"):
        email = get_sindarin_email()  # Returns "user@example.com"
"""

import logging
import os
import threading
from contextlib import contextmanager
from typing import Optional, Tuple

from flask import request

from server.config import VNC_BASE_URL

logger = logging.getLogger(__name__)

# Thread-local storage for email override
_email_override = threading.local()


@contextmanager
def email_override(email: str):
    """
    Context manager to override the email returned by get_sindarin_email().
    Useful for operations outside of Flask request context.

    Usage:
        with email_override("user@example.com"):
            # get_sindarin_email() will return "user@example.com" here
            do_something()
    """
    old_email = getattr(_email_override, "email", None)
    _email_override.email = email
    try:
        yield
    finally:
        if old_email is None:
            delattr(_email_override, "email")
        else:
            _email_override.email = old_email


def get_sindarin_email() -> Optional[str]:
    """
    Extract email from request (query params, JSON body, or form data).
    Handles staff impersonation by returning user_email when both sindarin_email
    and user_email are present in the request.

    Returns:
        The extracted email (impersonated user email or regular email) or None if not found
    """
    # First check for thread-local override (for operations outside request context)
    override_email = getattr(_email_override, "email", None)
    if override_email:
        return override_email

    # Check if we're in a request context
    from flask import has_request_context

    if not has_request_context():
        # Outside request context - return None
        # The calling code should use email_override() context manager
        return None

    # First check for impersonation scenario
    # Check query parameters
    if request.args.get("sindarin_email") and request.args.get("user_email"):
        staff_email = request.args.get("sindarin_email")
        user_email = request.args.get("user_email")
        return user_email

    # Check JSON body for impersonation
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if data.get("sindarin_email") and data.get("user_email"):
            staff_email = data.get("sindarin_email")
            user_email = data.get("user_email")
            logger.info(f"Staff impersonation: {staff_email} impersonating {user_email}")
            return user_email

    # Check form data for impersonation
    if request.form.get("sindarin_email") and request.form.get("user_email"):
        staff_email = request.form.get("sindarin_email")
        user_email = request.form.get("user_email")
        logger.info(f"Staff impersonation: {staff_email} impersonating {user_email}")
        return user_email

    # Standard email extraction if not impersonating
    email = None

    # Check in URL parameters - try both parameter names
    if "sindarin_email" in request.args:
        email = request.args.get("sindarin_email")
    elif "email" in request.args:
        email = request.args.get("email")

    # Check in JSON body if present
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        if "sindarin_email" in data:
            email = data.get("sindarin_email")
            logger.debug(f"Found sindarin_email in JSON body: {email}")
        elif "email" in data:
            email = data.get("email")
            logger.debug(f"Found email in JSON body: {email}")

    # Check in form data
    elif "sindarin_email" in request.form:
        email = request.form.get("sindarin_email")
        logger.debug(f"Found sindarin_email in form data: {email}")
    elif "email" in request.form:
        email = request.form.get("email")
        logger.debug(f"Found email in form data: {email}")

    return email


def get_automator_for_request(server):
    """Get the appropriate automator based on sindarin_email in the request.

    Args:
        server: The AutomationServer instance

    Returns:
        tuple: (automator, sindarin_email, error_response)
        where error_response is None if successful, or a tuple of (error_dict, status_code) if failed
    """
    # Get sindarin_email from request to determine which automator to use
    sindarin_email = get_sindarin_email()

    if not sindarin_email:
        error = {"error": "No email provided to identify which profile to use"}
        logger.error("No email provided in request to identify profile")
        return None, None, (error, 400)

    # Get the appropriate automator
    automator = server.automators.get(sindarin_email)
    if not automator:
        error = {"error": f"No automator found for {sindarin_email}"}
        logger.error(f"No automator found for {sindarin_email}")
        return None, None, (error, 404)

    logger.debug(f"Found automator for {sindarin_email}")
    return automator, sindarin_email, None


def get_boolean_param(param_name: str, default=False):
    """Extract boolean parameter from request (query params, JSON body, or form data).
    
    Similar to the OCR parameter extraction pattern.
    
    Args:
        param_name: Name of the parameter to extract  
        default: Default value if parameter not found
        
    Returns:
        bool: The extracted boolean value
    """
    from flask import has_request_context
    
    # Check if we're in a request context
    if not has_request_context():
        return default
        
    # Check URL query parameters first
    query_param = request.args.get(param_name)
    if query_param is not None:
        if isinstance(query_param, str):
            return query_param.lower() in ("1", "true", "yes")
        return bool(query_param)
    
    # Check JSON body 
    if request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            json_param = json_data.get(param_name)
            if json_param is not None:
                if isinstance(json_param, bool):
                    return json_param
                elif isinstance(json_param, str):
                    return json_param.lower() in ("1", "true", "yes")
                elif isinstance(json_param, int):
                    return json_param == 1
        except Exception as e:
            logger.warning(f"Error parsing JSON for {param_name} parameter: {e}")
    
    # Check form data
    form_param = request.form.get(param_name)
    if form_param is not None:
        if isinstance(form_param, str):
            return form_param.lower() in ("1", "true", "yes")
        return bool(form_param)
        
    return default


def is_websockets_requested() -> bool:
    """Check if websockets are requested in the current request.

    Returns:
        bool: True if websockets are requested, False otherwise
    """
    return get_boolean_param("websockets", False)


def get_vnc_and_websocket_urls(sindarin_email: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Get both VNC and WebSocket URLs for the given email.

    Args:
        sindarin_email: The email to get URLs for

    Returns:
        Tuple[Optional[str], Optional[str]]: (vnc_url, websocket_url)
    """
    # Get standard VNC URL
    vnc_url = get_formatted_vnc_url(sindarin_email, use_websockets=False)

    # Get WebSocket URL if VNC URL was available
    websocket_url = None
    if vnc_url:
        websocket_url = get_formatted_vnc_url(sindarin_email, use_websockets=True)

    return vnc_url, websocket_url


def get_formatted_vnc_url(
    sindarin_email: Optional[str] = None, use_websockets: bool = False
) -> Optional[str]:
    """
    Format the VNC URL with the given sindarin_email.
    Returns a VNC protocol URL (vnc://hostname:port) or WebSocket URL if use_websockets=True.

    Args:
        sindarin_email: The email to include in the VNC URL
        use_websockets: Whether to return a WebSocket URL for noVNC instead of a direct VNC URL

    Returns:
        Optional[str]: The VNC protocol URL or WebSocket URL for the allocated VNC server, or None if not found
    """
    # Import needed modules
    import platform
    import subprocess
    import time
    from urllib.parse import urlparse

    from server.utils.vnc_instance_manager import VNCInstanceManager

    # Extract hostname from the base URL (removing any port number)
    hostname = urlparse(VNC_BASE_URL).netloc.split(":")[0]

    # If no email provided, try to get from request
    # This ensures emails aren't mixed up across concurrent requests
    if not sindarin_email:
        # Try getting from request context only - no fallbacks
        sindarin_email = get_sindarin_email()

    # If still no email after checking request, we can't look up a VNC instance
    if not sindarin_email:
        logger.warning("No email provided for VNC URL, cannot determine port")
        return None

    try:
        # Use the VNCInstanceManager singleton to get the port
        vnc_manager = VNCInstanceManager.get_instance()
        android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        avd_dir = os.path.join(android_home, "avd")

        # Get the VNC port using the email
        vnc_port = vnc_manager.get_vnc_port(sindarin_email)

        # If port is found, verify VNC server is running and restart if needed
        if vnc_port:
            # Handle WebSocket URL if requested
            if use_websockets:
                # Import WebSocketProxyManager and start a proxy
                from server.utils.websocket_proxy_manager import WebSocketProxyManager

                ws_manager = WebSocketProxyManager.get_instance()

                # Start the proxy and get the WebSocket port
                ws_port = ws_manager.start_proxy(sindarin_email, vnc_port)

                if ws_port:
                    # Return the WebSocket URL (for noVNC)
                    # Format: ws://hostname:port/websockify
                    ws_url = f"ws://{hostname}:{ws_port}/websockify"
                    logger.info(f"WebSocket URL for {sindarin_email}: {ws_url}")
                    return ws_url
                else:
                    logger.error(f"Failed to start WebSocket proxy for {sindarin_email}")
                    # Fall back to regular VNC URL

            # Return the regular VNC URL
            vnc_url = f"vnc://{hostname}:{vnc_port}"
            logger.info(f"VNC URL for {sindarin_email}: {vnc_url}")
            return vnc_url
        else:
            # List all assigned instances for debugging
            assigned = {
                instance.get("assigned_profile"): instance.get("vnc_port")
                for instance in vnc_manager.instances
                if instance.get("assigned_profile")
            }
            logger.warning(f"No VNC port found for {sindarin_email}. Current assignments: {assigned}")

            # Try assign a VNC instance to this profile if none found
            logger.info(f"Attempting to assign a VNC instance to {sindarin_email}")
            instance = vnc_manager.assign_instance_to_profile(sindarin_email)
            if instance and "vnc_port" in instance:
                if use_websockets:
                    # Import WebSocketProxyManager and start a proxy
                    from server.utils.websocket_proxy_manager import (
                        WebSocketProxyManager,
                    )

                    ws_manager = WebSocketProxyManager.get_instance()

                    # Start the proxy and get the WebSocket port
                    ws_port = ws_manager.start_proxy(sindarin_email, instance["vnc_port"])

                    if ws_port:
                        # Return the WebSocket URL (for noVNC)
                        ws_url = f"ws://{hostname}:{ws_port}/websockify"
                        logger.info(f"WebSocket URL for {sindarin_email}: {ws_url}")
                        return ws_url
                    else:
                        logger.error(f"Failed to start WebSocket proxy for {sindarin_email}")
                        # Fall back to regular VNC URL

                vnc_url = f"vnc://{hostname}:{instance['vnc_port']}"
                logger.info(f"Assigned new VNC URL for {sindarin_email}: {vnc_url}")
                return vnc_url

            return None

    except Exception as e:
        logger.error(f"Error getting VNC port for {sindarin_email}: {e}")
        return None
