"""
Utility functions for server startup and emulator restoration.
"""

import logging
import platform
import subprocess
import threading
import time
import traceback
from typing import List

logger = logging.getLogger(__name__)


def auto_restart_emulators_after_startup(server):
    """
    Schedule the auto-restart of emulators from previous session after server startup.
    This function starts a background thread that waits for the server to be ready
    before attempting to restart emulators.

    Args:
        server: The AutomationServer instance
    """

    def _restart_emulators():
        """Background thread function to restart emulators."""
        from server.utils.request_utils import email_override
        from server.utils.vnc_instance_manager import VNCInstanceManager

        logger.info("=== Beginning session restoration check ===")
        vnc_manager = VNCInstanceManager.get_instance()

        # Reset any lingering appium states from previous run
        logger.info("Resetting appium states from previous run...")
        vnc_manager.reset_appium_states_on_startup()

        emulators_to_restart = vnc_manager.get_running_at_restart()

        if emulators_to_restart:
            logger.info(
                f"Found {len(emulators_to_restart)} emulators marked for restart from previous session:"
            )
            for email in emulators_to_restart:
                logger.info(f"  - {email}")

            # Clear the flags first to avoid infinite restart loops
            vnc_manager.clear_running_at_restart_flags()
            logger.info("Cleared restart flags to prevent infinite loops")

            # Clean up any lingering port forwards and UiAutomator2 processes before starting
            logger.info("Cleaning up lingering processes and port forwards before restart")
            try:
                # Get all connected devices
                result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
                lines = result.stdout.strip().split("\n")[1:]  # Skip header
                for line in lines:
                    if "\tdevice" in line:
                        device_id = line.split("\t")[0]
                        logger.info(f"Cleaning up device {device_id}")
                        # Port forwards are persistent and tied to instance IDs
                        # We keep them in place for faster startup
                        logger.info(f"Keeping ADB port forwards for {device_id} to speed up startup")
                        # Kill any UiAutomator2 processes
                        subprocess.run(
                            [f"adb -s {device_id} shell pkill -f uiautomator"], shell=True, check=False
                        )
            except Exception as e:
                logger.warning(f"Error during pre-restart cleanup: {e}")

            # Restart each emulator one at a time to avoid resource contention
            successfully_restarted = []
            failed_restarts = []

            # On local development, track which emulators are in use
            import platform

            emulators_in_use = {}  # emulator_id -> email mapping

            for email in emulators_to_restart:
                try:
                    logger.info(f" ---> Auto-restarting emulator for {email}...")

                    # Check if this profile's emulator is already in use (local development only)
                    if platform.system() == "Darwin":
                        (
                            is_running,
                            emulator_id,
                            avd_name,
                        ) = server.profile_manager.find_running_emulator_for_email(email)
                        if emulator_id and emulator_id in emulators_in_use:
                            other_email = emulators_in_use[emulator_id]
                            logger.warning(
                                f"Skipping {email} - emulator {emulator_id} already initialized for {other_email}"
                            )
                            logger.info(f"On local development, only one profile per emulator is allowed")
                            failed_restarts.append(email)
                            continue

                    # Use email override context to ensure proper email routing
                    with email_override(email):
                        # Use switch_profile instead of start_emulator to ensure proper initialization
                        success, message = server.switch_profile(email)

                        if success:
                            # Initialize the automator to ensure the driver is ready
                            automator = server.initialize_automator(email)
                            logger.info(f"Initialized startup automator for {email}: {automator}")
                            if automator:
                                logger.info(f"✓ Successfully restarted emulator for {email}")
                                successfully_restarted.append(email)

                                # Track which emulator this profile is using
                                if platform.system() == "Darwin" and hasattr(automator, "device_id"):
                                    emulators_in_use[automator.device_id] = email
                                    logger.info(f"Marked emulator {automator.device_id} as in use by {email}")
                            else:
                                logger.error(f"✗ Failed to initialize driver for {email}", exc_info=True)
                                failed_restarts.append(email)
                        else:
                            logger.error(f"✗ Failed to start emulator for {email}: {message}", exc_info=True)
                            failed_restarts.append(email)

                except Exception as e:
                    logger.error(f"✗ Error restarting emulator for {email}: {e}", exc_info=True)
                    logger.debug(
                        f"Backtrace for error restarting emulator for {email}: {traceback.format_exc()}"
                    )
                    failed_restarts.append(email)

            # Summary report
            logger.info("=== Session restoration complete ===")
            logger.info(f"Successfully restarted: {len(successfully_restarted)} emulators")
            if successfully_restarted:
                for email in successfully_restarted:
                    logger.info(f"  ✓ {email}")

            if failed_restarts:
                logger.info(f"Failed to restart: {len(failed_restarts)} emulators")
                for email in failed_restarts:
                    logger.info(f"  ✗ {email}")
        else:
            logger.info("=== No emulators marked for restart from previous session ===")

    # Start the background thread
    thread = threading.Thread(target=_restart_emulators, daemon=True)
    thread.start()
    logger.info("Started background thread for emulator restoration")
