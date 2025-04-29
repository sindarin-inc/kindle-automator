import logging
from typing import Optional

from flask import request

from server.config import VNC_BASE_URL

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


def get_formatted_vnc_url(sindarin_email: Optional[str] = None, view_type: Optional[str] = None) -> str:
    """
    Format the VNC URL with the given sindarin_email and optional view type.

    Args:
        sindarin_email: The email to include in the VNC URL
        view_type: Optional view type (e.g., 'app_only' for app-only view)

    Returns:
        str: The formatted VNC URL with query parameters
    """
    if not sindarin_email:
        # Return the VNC URL without parameters
        return VNC_BASE_URL

    # Construct the query string with sindarin_email and other required params
    query_params = [f"sindarin_email={sindarin_email}", "autoconnect=true", "password=changeme"]
    
    # Add view type parameter if specified
    if view_type:
        query_params.append(f"view={view_type}")

    # Construct the final URL with all parameters
    if "?" in VNC_BASE_URL:
        vnc_url = f"{VNC_BASE_URL}&{'&'.join(query_params)}"
    else:
        vnc_url = f"{VNC_BASE_URL}?{'&'.join(query_params)}"

    return vnc_url
