"""
Network utilities for getting server IP addresses and related network information.
"""

import logging
import os
import socket

logger = logging.getLogger(__name__)


def get_server_ip():
    """
    Get the server's IP address to use in responses.

    First checks for SERVER_IP environment variable, then tries to determine
    the actual IP address that can be reached from external clients.

    Returns:
        str: The server's IP address or hostname
    """
    # Check for environment variable override first
    server_ip = os.environ.get("SERVER_IP")
    if server_ip:
        logger.debug(f"Using SERVER_IP from environment: {server_ip}")
        return server_ip

    # Check for VNC_HOST environment variable as fallback
    vnc_host = os.environ.get("VNC_HOST")
    if vnc_host:
        logger.debug(f"Using VNC_HOST from environment: {vnc_host}")
        return vnc_host

    # Try to get the actual IP address
    try:
        # Create a dummy socket to determine the IP address used for external connections
        # This doesn't actually connect, just determines which interface would be used
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            logger.debug(f"Detected server IP address: {ip_address}")
            return ip_address
    except Exception as e:
        logger.warning(f"Failed to detect server IP address: {e}")

        # Last resort - try to get hostname
        try:
            hostname = socket.gethostname()
            logger.debug(f"Using hostname as fallback: {hostname}")
            return hostname
        except Exception as e2:
            logger.error(f"Failed to get hostname: {e2}")
            # Ultimate fallback
            return "localhost"
