import logging
import os
from typing import Optional

from flask import request

from server.config import VNC_BASE_URL

logger = logging.getLogger(__name__)


def get_sindarin_email() -> Optional[str]:
    """
    Extract sindarin_email from request (query params, JSON body, or form data).
    No fallback to default_email - either the email exists in the request or not.

    Returns:
        The extracted email or None if not found
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

    if not sindarin_email:
        logger.debug("No sindarin_email found in request")

    return sindarin_email


def get_formatted_vnc_url(
    sindarin_email: Optional[str] = None, view_type: Optional[str] = None, emulator_id: Optional[str] = None
) -> Optional[str]:
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
    from urllib.parse import urlparse

    from server.utils.vnc_instance_manager import VNCInstanceManager
    from views.core.device_discovery import DeviceDiscovery

    # Extract hostname from the base URL (removing any port number)
    hostname = urlparse(VNC_BASE_URL).netloc.split(":")[0]

    # If no email provided, try to get from request
    # This ensures emails aren't mixed up across concurrent requests
    if not sindarin_email:
        # Try getting from request context, don't fall back to server.current_email
        sindarin_email = get_sindarin_email()

    # If still no email after checking request, we can't look up a VNC instance
    if not sindarin_email:
        logger.warning("No email provided for VNC URL, cannot determine port")
        return None

    logger.info(f"Looking up VNC URL for sindarin_email={sindarin_email}, emulator_id={emulator_id}")

    try:
        # Use the VNCInstanceManager to get the port
        vnc_manager = VNCInstanceManager()
        android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        avd_dir = os.path.join(android_home, "avd")
        device_discovery = DeviceDiscovery(android_home, avd_dir)

        # If emulator_id is provided, determine the correct AVD from it
        if emulator_id:
            # First log the email we're using
            logger.info(f"Finding AVD name for emulator_id={emulator_id} for email {sindarin_email}")

            # Use device discovery to map running emulators
            running_emulators = device_discovery.map_running_emulators()
            # Invert the mapping to get AVD name from emulator ID
            emulator_to_avd = {emu_id: avd_name for avd_name, emu_id in running_emulators.items()}

            if emulator_id in emulator_to_avd:
                avd_name = emulator_to_avd[emulator_id]
                logger.info(f"Found AVD name {avd_name} for emulator_id {emulator_id}")

                # Verify this AVD is associated with the requested email
                is_running, found_emulator_id, found_avd = device_discovery.find_running_emulator_for_email(
                    sindarin_email
                )
                if is_running and found_avd == avd_name:
                    logger.info(f"Confirmed AVD {avd_name} belongs to {sindarin_email}")
                else:
                    logger.warning(
                        f"AVD {avd_name} for emulator_id {emulator_id} doesn't match the expected AVD "
                        f"for {sindarin_email} which is {found_avd}"
                    )
                    # Continue anyway - we trust the emulator_id parameter
            else:
                logger.warning(f"Emulator ID {emulator_id} not found in running emulators")
                # Fall back to email-based lookup

        # Check if this email has an AVD mapping
        avd_id = vnc_manager._get_avd_id_for_email(sindarin_email)
        logger.info(f"AVD ID for email {sindarin_email}: {avd_id}")

        # Get the VNC port using the email
        vnc_port = vnc_manager.get_vnc_port(sindarin_email)

        # If port is found, return formatted URL
        if vnc_port:
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
