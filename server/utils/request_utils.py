import logging
from typing import Optional

from flask import request

from server.config import VNC_URL

logger = logging.getLogger(__name__)


def get_sindarin_email(default_email: Optional[str] = None) -> Optional[str]:
    """
    Extract sindarin_email from request (query params, JSON body, or form data).

    Args:
        default_email: Default email to return if not found in request

    Returns:
        The extracted email or the default email if not found
    """
    sindarin_email = None

    # Check in URL parameters
    if "sindarin_email" in request.args:
        sindarin_email = request.args.get("sindarin_email")
        logger.debug(f"Found sindarin_email in URL parameters: {sindarin_email}")

    # Check in JSON body if present
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        if "sindarin_email" in data:
            sindarin_email = data.get("sindarin_email")
            logger.debug(f"Found sindarin_email in JSON body: {sindarin_email}")

    # Check in form data
    elif "sindarin_email" in request.form:
        sindarin_email = request.form.get("sindarin_email")
        logger.debug(f"Found sindarin_email in form data: {sindarin_email}")

    # Return either found email or default
    return sindarin_email or default_email


def get_formatted_vnc_url(sindarin_email: Optional[str] = None) -> str:
    """
    Format the VNC URL with the given sindarin_email.
    
    Args:
        sindarin_email: The email to include in the VNC URL
        
    Returns:
        str: The formatted VNC URL with the sindarin_email parameter
    """
    if not sindarin_email:
        # Return the VNC URL without an email parameter
        return VNC_URL.replace("?sindarin_email={sindarin_email}", "")
    
    # Format the URL with the sindarin_email
    return VNC_URL.format(sindarin_email=sindarin_email)
