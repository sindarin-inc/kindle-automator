import logging
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def check_port_forwarding(device_id: str, system_port: int) -> bool:
    """Check if port forwarding is active for a specific device and system port."""
    try:
        result = subprocess.run(
            ["adb", "-s", device_id, "forward", "--list"], capture_output=True, text=True, timeout=5
        )

        if result.returncode != 0:
            logger.error(f"Failed to list port forwards for {device_id}: {result.stderr}")
            return False

        # Check if our system port is in the forward list
        forward_str = f"tcp:{system_port}"
        return forward_str in result.stdout

    except Exception as e:
        logger.error(f"Error checking port forwarding for {device_id}: {e}")
        return False


def ensure_port_forwarding(device_id: str, system_port: int, uiautomator_port: int = 6790) -> bool:
    """Ensure port forwarding is set up for UiAutomator2 communication.

    Args:
        device_id: The device/emulator ID (e.g., 'emulator-5556')
        system_port: The host port to forward (e.g., 8202)
        uiautomator_port: The UiAutomator2 port on device (default: 6790)

    Returns:
        True if forwarding is active or successfully set up, False otherwise
    """
    try:
        # First check if forwarding already exists
        if check_port_forwarding(device_id, system_port):
            logger.debug(f"Port forwarding already active for {device_id} port {system_port}")
            return True

        # Set up the port forwarding
        logger.info(f"Setting up port forwarding for {device_id}: {system_port} -> {uiautomator_port}")
        result = subprocess.run(
            ["adb", "-s", device_id, "forward", f"tcp:{system_port}", f"tcp:{uiautomator_port}"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.error(f"Failed to set up port forwarding: {result.stderr}")
            return False

        logger.info(f"Successfully set up port forwarding for {device_id}")
        return True

    except Exception as e:
        logger.error(f"Error ensuring port forwarding for {device_id}: {e}")
        return False


def get_device_port_forwards(device_id: str) -> list[Tuple[str, str]]:
    """Get all port forwards for a specific device.

    Returns:
        List of tuples (host_port, device_port)
    """
    try:
        result = subprocess.run(
            ["adb", "-s", device_id, "forward", "--list"], capture_output=True, text=True, timeout=5
        )

        if result.returncode != 0:
            logger.error(f"Failed to list port forwards: {result.stderr}")
            return []

        forwards = []
        for line in result.stdout.strip().split("\n"):
            if not line or device_id not in line:
                continue
            # Format: emulator-5556 tcp:8202 tcp:6790
            parts = line.split()
            if len(parts) >= 3:
                host_port = parts[1].replace("tcp:", "")
                device_port = parts[2].replace("tcp:", "")
                forwards.append((host_port, device_port))

        return forwards

    except Exception as e:
        logger.error(f"Error getting port forwards: {e}")
        return []


def clear_port_forwarding(device_id: str, system_port: Optional[int] = None) -> bool:
    """Clear port forwarding for a device.

    Args:
        device_id: The device/emulator ID
        system_port: Specific port to clear, or None to clear all

    Returns:
        True if successful, False otherwise
    """
    try:
        if system_port:
            # Clear specific port
            cmd = ["adb", "-s", device_id, "forward", "--remove", f"tcp:{system_port}"]
        else:
            # Clear all forwards for this device
            cmd = ["adb", "-s", device_id, "forward", "--remove-all"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0 and "error" in result.stderr.lower():
            logger.error(f"Failed to clear port forwarding: {result.stderr}")
            return False

        logger.info(
            f"Cleared port forwarding for {device_id}"
            + (f" port {system_port}" if system_port else " (all ports)")
        )
        return True

    except Exception as e:
        logger.error(f"Error clearing port forwarding: {e}")
        return False
