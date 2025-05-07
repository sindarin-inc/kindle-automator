#!/usr/bin/env python3
"""
Interactive shell for Kindle Automator.

This script provides a Django-like shell environment for the Kindle Automator project,
allowing you to investigate various components and interact with them directly.
"""

import code
import logging
import os
import sys
from pathlib import Path

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")

# Load .env files with secrets
if ENVIRONMENT.lower() == "prod":
    logger.info(f"Loading prod environment variables from {os.path.join(BASE_DIR, '.env.prod')}")
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env.prod"), override=True)
elif ENVIRONMENT.lower() == "staging":
    logger.info(f"Loading staging environment variables from {os.path.join(BASE_DIR, '.env.staging')}")
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env.staging"), override=True)
else:
    logger.info(f"Loading dev environment variables from {os.path.join(BASE_DIR, '.env')}")
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

# Import all major components
from automator import KindleAutomator
from driver import Driver
from handlers.auth_handler import LoginVerificationState
from handlers.library_handler import LibraryHandler
from handlers.permissions_handler import PermissionsHandler
from handlers.reader_handler import ReaderHandler
from server.core.automation_server import AutomationServer
from views.core.app_state import AppState
from views.core.avd_creator import AVDCreator
from views.core.device_discovery import DeviceDiscovery
from views.state_machine import KindleStateMachine
from views.view_inspector import ViewInspector


def initialize_environment():
    """Initialize the environment for the shell."""

    # Create automation server (this initializes profile manager)
    server = AutomationServer()

    # Get references to key components
    android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
    profile_manager = server.profile_manager
    emulator_manager = profile_manager.emulator_manager
    emulator_launcher = emulator_manager.emulator_launcher

    # Print initialization message
    print("\nKindle Automator Interactive Shell")
    print("==================================\n")
    print("Available main objects:")
    print("  - server: AutomationServer instance")
    print("  - profile_manager: AVDProfileManager instance")
    print("  - emulator_manager: EmulatorManager instance")
    print("  - emulator_launcher: EmulatorLauncher instance\n")
    print("Example usage:")
    print("  - emulator_launcher.get_x_display('user@example.com')")
    print("  - profile_manager.get_profiles()")
    print("  - emulator_manager.start_emulator('user@example.com')\n")
    print("To initialize an automator for a specific email:")
    print("  automator = server.initialize_automator('user@example.com')\n")

    # Return key objects to make them available in the shell namespace
    return {
        "server": server,
        "profile_manager": profile_manager,
        "emulator_manager": emulator_manager,
        "emulator_launcher": emulator_launcher,
        "KindleAutomator": KindleAutomator,
        "Driver": Driver,
        "AppState": AppState,
        "KindleStateMachine": KindleStateMachine,
        "LoginVerificationState": LoginVerificationState,
        "LibraryHandler": LibraryHandler,
        "ReaderHandler": ReaderHandler,
        "PermissionsHandler": PermissionsHandler,
        "ViewInspector": ViewInspector,
        "AVDCreator": AVDCreator,
        "DeviceDiscovery": DeviceDiscovery,
    }


if __name__ == "__main__":
    # Initialize environment and get namespace objects
    namespace = initialize_environment()

    # Start interactive console with the namespace
    code.interact(local=namespace)
