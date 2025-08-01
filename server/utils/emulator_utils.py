"""Utility functions for safe emulator operations in multi-user environment."""

import logging
import os
from typing import Optional

from server.core.automation_server import AutomationServer
from server.utils.emulator_launcher import EmulatorLauncher
from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)


def get_emulator_launcher_for_user(email: str) -> Optional[EmulatorLauncher]:
    """
    Get the correct emulator launcher for a specific user.

    This ensures we always use the user-specific emulator launcher to avoid
    cross-user interference with port forwarding and emulator operations.

    Args:
        email: The user's email address

    Returns:
        EmulatorLauncher: The user-specific launcher, or a new instance if needed
    """
    # First try to get from the user's automator
    server = AutomationServer.get_instance()
    if server and hasattr(server, "automators"):
        automator = server.automators.get(email)
        if automator and hasattr(automator, "emulator_manager"):
            return automator.emulator_manager.emulator_launcher

    # Fallback: create a new launcher instance for this operation
    # This ensures we don't use another user's launcher
    logger.warning(f"No automator found for {email}, creating temporary emulator launcher")
    android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
    avd_dir = os.path.join(android_home, "avd")

    # Try to detect architecture from profile manager
    host_arch = "x86_64"  # default
    try:
        from views.core.avd_profile_manager import AVDProfileManager

        pm = AVDProfileManager.get_instance()
        if pm and hasattr(pm, "host_arch"):
            host_arch = pm.host_arch
    except Exception:
        pass

    return EmulatorLauncher(android_home, avd_dir, host_arch)


def get_emulator_id_for_user(email: str) -> Optional[str]:
    """
    Get the emulator ID for a specific user from the VNC instance manager.

    This is the database-backed source of truth for user-to-emulator mapping.

    Args:
        email: The user's email address

    Returns:
        str: The emulator ID (e.g., "emulator-5554") or None
    """
    vnc_manager = VNCInstanceManager.get_instance()
    return vnc_manager.get_emulator_id(email)


def get_running_emulator_for_user(email: str) -> tuple[Optional[str], Optional[int]]:
    """
    Get the running emulator info for a specific user.

    Args:
        email: The user's email address

    Returns:
        tuple: (emulator_id, display_number) or (None, None)
    """
    launcher = get_emulator_launcher_for_user(email)
    if launcher:
        return launcher.get_running_emulator(email)
    return None, None
