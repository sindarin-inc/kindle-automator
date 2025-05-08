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
"""

import logging
import os
from typing import Optional

from flask import request

from server.config import VNC_BASE_URL
from server.logging_config import get_email_logger

logger = logging.getLogger(__name__)


def get_sindarin_email() -> Optional[str]:
    """
    Extract email from request (query params, JSON body, or form data).
    Supports both 'sindarin_email' and 'email' parameters for convenience.
    No fallback to default_email - either the email exists in the request or not.

    Returns:
        The extracted email or None if not found
    """
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

    if not email:
        logger.debug("No email found in request")

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

    # Use the appropriate logger - either email-specific or standard
    request_logger = get_request_logger()

    if not sindarin_email:
        error = {"error": "No email provided to identify which profile to use"}
        request_logger.error("No email provided in request to identify profile")
        return None, None, (error, 400)

    # Get the appropriate automator
    automator = server.automators.get(sindarin_email)
    if not automator:
        error = {"error": f"No automator found for {sindarin_email}"}
        request_logger.error(f"No automator found for {sindarin_email}")
        return None, None, (error, 404)

    request_logger.debug(f"Found automator for {sindarin_email}")
    return automator, sindarin_email, None


def get_request_logger() -> logging.Logger:
    """
    Get a logger for the current request based on the sindarin_email in the request.

    This function first tries to get the email-specific logger from the Flask request context.
    If that's not available, it extracts the email from the current request and returns
    an appropriate logger. If an email is found, it returns a logger that will write to 
    both the main log file and an email-specific log file (logs/<email>.log).
    If no email is found, it falls back to the standard logger.

    This is the preferred way to get a logger in request handlers, as it automatically
    handles the logic of determining the appropriate logger based on the current context.

    Example usage in a Flask route or resource:

        @app.route('/api/books')
        def get_books():
            # Get a logger for the current request
            request_logger = get_request_logger()

            # Use the logger - logs will go to both the main log and email-specific log if applicable
            request_logger.info("Processing books request")

            # Rest of the function...

    Returns:
        logging.Logger: A logger appropriate for the current request context
    """
    try:
        # Try to get the email logger from the flask.g object first (set in before_request)
        from flask import g
        if hasattr(g, 'email_logger'):
            return g.email_logger
    except (ImportError, RuntimeError):
        # Not in Flask context or g not available
        pass
    
    # Fall back to extracting email from request and getting logger
    email = get_sindarin_email()
    if email:
        email_logger = get_email_logger(email)
        if email_logger:
            return email_logger

    # Fall back to the standard logger if no email is found or email logger creation fails
    return logger


def get_formatted_vnc_url(sindarin_email: Optional[str] = None) -> Optional[str]:
    """
    Format the VNC URL with the given sindarin_email.
    Returns a VNC protocol URL (vnc://hostname:port).

    Args:
        sindarin_email: The email to include in the VNC URL
        view_type: Optional view type (unused in direct VNC protocol URL)
        emulator_id: Optional emulator ID to explicitly find the VNC port by emulator ID

    Returns:
        Optional[str]: The VNC protocol URL for the allocated VNC server, or None if not found
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
            # Return the VNC URL
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
                vnc_url = f"vnc://{hostname}:{instance['vnc_port']}"
                logger.info(f"Assigned new VNC URL for {sindarin_email}: {vnc_url}")
                return vnc_url

            return None

    except Exception as e:
        logger.error(f"Error getting VNC port for {sindarin_email}: {e}")
        return None
