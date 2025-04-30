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


def get_formatted_vnc_url(
    sindarin_email: Optional[str] = None, view_type: Optional[str] = None, emulator_id: Optional[str] = None
) -> Optional[str]:
    """
    Format the VNC URL with the given sindarin_email.
    Returns a VNC protocol URL (vnc://hostname:port) rather than a NoVNC HTML URL.

    Args:
        sindarin_email: The email to include in the VNC URL
        view_type: Optional view type (unused in direct VNC protocol URL)
        emulator_id: Optional emulator ID (unused in direct VNC protocol URL)

    Returns:
        Optional[str]: The VNC protocol URL for the allocated VNC server, or None if not found
    """
    # Import needed modules
    from urllib.parse import urlparse
    from server.utils.vnc_instance_manager import VNCInstanceManager
    
    # Extract hostname from the base URL (removing any port number)
    hostname = urlparse(VNC_BASE_URL).netloc.split(':')[0]
    
    # If no email provided, we can't look up a VNC instance
    if not sindarin_email:
        logger.warning("No email provided for VNC URL, cannot determine port")
        return None
    
    try:
        # Use the VNCInstanceManager to get the port
        vnc_manager = VNCInstanceManager()
        vnc_port = vnc_manager.get_vnc_port(sindarin_email)
        
        if vnc_port:
            return f"vnc://{hostname}:{vnc_port}"
        else:
            logger.warning(f"No VNC port found for {sindarin_email}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting VNC port for {sindarin_email}: {e}")
        return None
