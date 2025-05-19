"""
Utility functions for server startup and emulator restoration.
"""

import logging
import threading
import time
from typing import List

logger = logging.getLogger(__name__)


def auto_restart_emulators_after_startup(server, delay: float = 3.0):
    """
    Schedule the auto-restart of emulators from previous session after server startup.
    This function starts a background thread that waits for the server to be ready
    before attempting to restart emulators.

    Args:
        server: The AutomationServer instance
        delay: How long to wait after server starts before attempting restarts (seconds)
    """

    def _restart_emulators():
        """Background thread function to restart emulators."""
        from server.utils.request_utils import email_override
        from server.utils.vnc_instance_manager import VNCInstanceManager

        # Wait for server to be fully ready
        logger.info(f"Waiting {delay} seconds for server to be fully ready before restarting emulators...")
        time.sleep(delay)

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

            # Restart each emulator one at a time to avoid resource contention
            successfully_restarted = []
            failed_restarts = []

            for email in emulators_to_restart:
                try:
                    logger.info(f"Auto-restarting emulator for {email}...")

                    # Use email override context to ensure proper email routing
                    with email_override(email):
                        # First start Appium for this email if not already running
                        from server.utils.appium_driver import AppiumDriver
                        
                        appium_driver = AppiumDriver()
                        appium_info = appium_driver.get_appium_process_info(email)
                        
                        if not appium_info or not appium_info.get("running"):
                            appium_started = appium_driver.start_appium_for_profile(email)
                            if not appium_started:
                                logger.error(f"Failed to start Appium server for {email}")
                                failed_restarts.append(email)
                                continue

                        # Use switch_profile instead of start_emulator to ensure proper initialization
                        success, message = server.switch_profile(email, force_new_emulator=False)

                        if success:
                            # Initialize the automator to ensure the driver is ready
                            automator = server.initialize_automator(email)
                            if automator and automator.initialize_driver():
                                logger.info(f"✓ Successfully restarted emulator for {email}")
                                successfully_restarted.append(email)
                                # Add a delay between restarts to avoid overwhelming the system
                                time.sleep(5)
                            else:
                                logger.error(f"✗ Failed to initialize driver for {email}")
                                failed_restarts.append(email)
                        else:
                            logger.error(f"✗ Failed to start emulator for {email}: {message}")
                            failed_restarts.append(email)

                except Exception as e:
                    logger.error(f"✗ Error restarting emulator for {email}: {e}")
                    failed_restarts.append(email)
                    raise e

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
