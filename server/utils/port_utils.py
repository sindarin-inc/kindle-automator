"""
Centralized port configuration and calculation utilities.

This module consolidates all port-related logic to avoid duplication
across the codebase. All port calculations should use these functions.
"""

import os
import platform


class PortConfig:
    """Port configuration constants and calculations."""

    # Appium port configuration
    APPIUM_BASE_PORT = 4723
    APPIUM_MAX_PORT = 4999
    APPIUM_PORT_RANGE = APPIUM_MAX_PORT - APPIUM_BASE_PORT  # 276

    # Emulator ports (even numbers: 5554, 5556, 5558...)
    EMULATOR_BASE_PORT = 5554

    # VNC ports (sequential: 5900, 5901, 5902...)
    VNC_BASE_PORT = 5900

    # Other ports used by the system
    SYSTEM_BASE_PORT = 8200
    CHROMEDRIVER_BASE_PORT = 9515
    MJPEG_BASE_PORT = 7810


def calculate_appium_port(email: str = None, instance_id: int = None) -> int:
    """
    Calculate Appium port for a given email or instance ID.

    Args:
        email: Email address to calculate port for (hash-based)
        instance_id: Instance ID to calculate port for (sequential)

    Returns:
        Calculated Appium port number

    Note:
        In macOS development environment, returns the base port (4723)
        only when no instance_id is provided. With an instance_id,
        it correctly calculates unique ports for multiple emulators.
    """
    # Check if we're in macOS development environment
    environment = os.getenv("ENVIRONMENT", "DEV")
    is_mac_dev = environment.lower() == "dev" and platform.system() == "Darwin"

    # If we have an instance_id, use it regardless of platform
    if instance_id is not None:
        # Sequential calculation for instance ID
        return PortConfig.APPIUM_BASE_PORT + instance_id

    # Only use macOS default if no instance_id is provided
    if is_mac_dev:
        # On macOS dev, use port 4723 when no instance is specified
        return PortConfig.APPIUM_BASE_PORT

    if email is not None:
        # Hash-based calculation for email
        email_hash = hash(email) % PortConfig.APPIUM_PORT_RANGE
        return PortConfig.APPIUM_BASE_PORT + email_hash
    else:
        # Default to base port if no identifier provided
        return PortConfig.APPIUM_BASE_PORT


def calculate_emulator_port(instance_id: int) -> int:
    """
    Calculate emulator port based on instance ID.

    Args:
        instance_id: The instance ID (1-based)

    Returns:
        int: The emulator port

    Note:
        Emulator ports are typically 5554, 5556, 5558, etc. (even numbers)
    """
    return PortConfig.EMULATOR_BASE_PORT + ((instance_id - 1) * 2)


def calculate_vnc_port(instance_id: int) -> int:
    """
    Calculate VNC port based on instance ID.

    Args:
        instance_id: The instance ID

    Returns:
        int: The VNC port

    Note:
        VNC ports start at 5900 and increment by 1 (5900, 5901, 5902...)
    """
    return PortConfig.VNC_BASE_PORT + instance_id


def calculate_emulator_ports(instance_id: int) -> dict:
    """
    Calculate all ports needed for an emulator instance.

    Args:
        instance_id: Instance ID for the emulator

    Returns:
        Dictionary with all port assignments
    """
    return {
        "appium_port": calculate_appium_port(instance_id=instance_id),
        "emulator_port": calculate_emulator_port(instance_id),
        "vnc_port": calculate_vnc_port(instance_id),
        "system_port": PortConfig.SYSTEM_BASE_PORT + instance_id,
        "chromedriver_port": PortConfig.CHROMEDRIVER_BASE_PORT + instance_id,
    }


def get_appium_port_for_email(email: str, vnc_manager=None, profiles_index=None) -> int:
    """
    Get Appium port for an email, checking stored value first.

    Args:
        email: Email address
        vnc_manager: VNC instance manager to check for stored port
        profiles_index: Direct profiles_index dict for backward compatibility

    Returns:
        Appium port number
    """
    # Check if we have a stored port from VNC manager
    if vnc_manager:
        try:
            stored_port = vnc_manager.get_appium_port(email)
            if stored_port:
                return stored_port
        except Exception:
            pass

    # Check profiles_index for backward compatibility
    if profiles_index and email in profiles_index:
        profile_entry = profiles_index.get(email)
        if isinstance(profile_entry, dict) and "appium_port" in profile_entry:
            return profile_entry["appium_port"]

    # Calculate port if not stored
    return calculate_appium_port(email=email)


def get_vnc_port_for_email(email: str, vnc_manager=None) -> int:
    """
    Get VNC port for an email.

    Args:
        email: Email address
        vnc_manager: VNC instance manager to check for assigned instance

    Returns:
        VNC port number or None if no instance assigned
    """
    if vnc_manager:
        try:
            return vnc_manager.get_vnc_port(email)
        except Exception:
            pass

    return None


def calculate_console_port(emulator_port: int) -> int:
    """
    Calculate console port from emulator port.

    Args:
        emulator_port: The emulator port (e.g., 5554)

    Returns:
        int: The console port (emulator_port - 1)

    Note:
        Console ports are always one less than the emulator port.
        For example, emulator port 5554 has console port 5553.
    """
    return emulator_port - 1


def construct_emulator_id(emulator_port: int) -> str:
    """
    Construct emulator ID from port number.

    Args:
        emulator_port: The emulator port number

    Returns:
        str: The emulator ID (e.g., "emulator-5554")
    """
    return f"emulator-{emulator_port}"


def parse_emulator_id(emulator_id: str) -> int:
    """
    Parse emulator port from emulator ID.

    Args:
        emulator_id: The emulator ID (e.g., "emulator-5554")

    Returns:
        int: The emulator port number
    """
    return int(emulator_id.split("-")[1])
