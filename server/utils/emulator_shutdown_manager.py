"""Manager for gracefully shutting down emulators."""

import logging
import platform
import subprocess
import time
import traceback
from datetime import datetime

from server.utils.vnc_instance_manager import VNCInstanceManager
from views.core.app_state import AppState
from views.state_machine import KindleStateMachine

logger = logging.getLogger(__name__)


class EmulatorShutdownManager:
    """Manages graceful shutdown of emulators."""

    def __init__(self, server_instance):
        """Initialize the shutdown manager.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance

    def shutdown_emulator(self, email):
        """Gracefully shutdown an emulator for a specific email.

        This parks the emulator in the Library view, takes a snapshot,
        then stops the emulator and cleans up resources.

        Args:
            email: The email address associated with the emulator

        Returns:
            dict: Shutdown summary with status information
        """
        logger.info(f"Processing shutdown request for {email}")

        # Track what was shut down
        shutdown_summary = {
            "email": email,
            "emulator_stopped": False,
            "vnc_stopped": False,
            "xvfb_stopped": False,
            "automator_cleaned": False,
            "snapshot_taken": False,
        }

        # Find the automator for this email
        automator = self.server.automators.get(email)
        if not automator:
            logger.info(f"No automator found for {email}, nothing to shut down")
            return shutdown_summary

        # Before shutting down, park the emulator in the Library view and take a snapshot
        try:
            if hasattr(automator, "driver") and automator.driver:
                logger.info(f"Parking emulator in Library view before shutdown for {email}")
                # Initialize state machine to handle transitions
                state_machine = KindleStateMachine(automator.driver)

                # Transition to library (this handles navigation from any state)
                try:
                    result = state_machine.transition_to_library(max_transitions=10, server=self.server)
                    if result and result == AppState.LIBRARY:
                        logger.info("Successfully parked emulator in Library view")
                        # Wait 5 seconds as requested
                        time.sleep(5)
                        # Take snapshot
                        if hasattr(automator.emulator_manager, "emulator_launcher"):
                            (
                                emulator_id,
                                _,
                            ) = automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                            if emulator_id:
                                logger.info(f"Taking ADB snapshot of emulator {emulator_id}")
                                # Get AVD name for cleaner snapshot naming
                                avd_name = (
                                    automator.emulator_manager.emulator_launcher._extract_avd_name_from_email(
                                        email
                                    )
                                )
                                if avd_name and avd_name.startswith("KindleAVD_"):
                                    # Extract just the email part from the AVD name
                                    avd_identifier = avd_name.replace("KindleAVD_", "")
                                else:
                                    avd_identifier = email.replace("@", "_").replace(".", "_")

                                # Include date for snapshot version management
                                date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                                snapshot_name = f"library_park_{avd_identifier}_{date_str}"

                                if automator.emulator_manager.emulator_launcher.save_snapshot(
                                    email, snapshot_name
                                ):
                                    logger.info(f"Saved snapshot '{snapshot_name}' for {email}")
                                    shutdown_summary["snapshot_taken"] = True
                                    # Save the snapshot name to the user profile
                                    try:
                                        from views.core.avd_profile_manager import (
                                            AVDProfileManager,
                                        )

                                        avd_manager = AVDProfileManager()
                                        avd_manager.set_user_field(email, "last_snapshot", snapshot_name)
                                        logger.info(
                                            f"Saved snapshot name '{snapshot_name}' to user profile for {email}"
                                        )
                                    except Exception as profile_error:
                                        logger.warning(
                                            f"Failed to save snapshot name to profile: {profile_error}"
                                        )
                                    # Clean up old snapshots to save disk space
                                    try:
                                        deleted_count = automator.emulator_manager.emulator_launcher.cleanup_old_snapshots(
                                            email, keep_count=3
                                        )
                                        if deleted_count > 0:
                                            logger.info(
                                                f"Cleaned up {deleted_count} old library park snapshots for {email}"
                                            )
                                    except Exception as cleanup_error:
                                        logger.warning(f"Failed to clean up old snapshots: {cleanup_error}")
                                else:
                                    logger.error(f"Failed to save snapshot '{snapshot_name}' for {email}")
                    else:
                        logger.warning("Failed to transition to Library view before shutdown")
                except Exception as e:
                    logger.warning(f"Error transitioning to Library before shutdown: {e}")
                    # Continue with shutdown even if parking fails
        except Exception as e:
            logger.warning(f"Error preparing for shutdown parking: {e}")
            # Continue with shutdown even if parking fails

        try:
            # Stop the emulator
            if hasattr(automator, "emulator_manager") and hasattr(
                automator.emulator_manager, "emulator_launcher"
            ):
                emulator_id, display_num = automator.emulator_manager.emulator_launcher.get_running_emulator(
                    email
                )
                if emulator_id:
                    logger.info(f"Stopping emulator {emulator_id} for {email}")
                    success = automator.emulator_manager.emulator_launcher.stop_emulator(email)
                    shutdown_summary["emulator_stopped"] = success
                    if success:
                        logger.info(f"Successfully stopped emulator {emulator_id}")
                    else:
                        logger.error(f"Failed to stop emulator {emulator_id}")
                else:
                    logger.info(f"No running emulator found for {email}")

                # Stop VNC and Xvfb (Linux only)
                if platform.system() != "Darwin" and display_num:
                    vnc_port = 5900 + display_num

                    # Stop x11vnc
                    try:
                        subprocess.run(["pkill", "-f", f"x11vnc.*rfbport {vnc_port}"], check=False, timeout=3)
                        logger.info(f"Stopped VNC server on port {vnc_port}")
                        shutdown_summary["vnc_stopped"] = True
                    except Exception as e:
                        logger.error(f"Error stopping VNC server: {e}")

                    # Stop Xvfb
                    try:
                        subprocess.run(["pkill", "-f", f"Xvfb :{display_num}"], check=False, timeout=3)
                        # Clean up lock files
                        subprocess.run(
                            [
                                "rm",
                                "-f",
                                f"/tmp/.X{display_num}-lock",
                                f"/tmp/.X11-unix/X{display_num}",
                            ],
                            check=False,
                        )
                        logger.info(f"Stopped Xvfb display :{display_num}")
                        shutdown_summary["xvfb_stopped"] = True
                    except Exception as e:
                        logger.error(f"Error stopping Xvfb: {e}")

                    # Release the VNC instance from the profile
                    try:
                        vnc_manager = VNCInstanceManager.get_instance()
                        vnc_manager.release_instance_from_profile(email)
                        logger.info(f"Released VNC instance for {email}")
                    except Exception as e:
                        logger.error(f"Error releasing VNC instance: {e}")

            # Clean up the automator
            if automator:
                try:
                    logger.info(f"Cleaning up automator for {email}")
                    automator.cleanup()
                    self.server.automators[email] = None
                    shutdown_summary["automator_cleaned"] = True
                except Exception as e:
                    logger.error(f"Error cleaning up automator: {e}")

            # Clear current book tracking
            self.server.clear_current_book(email)

            return shutdown_summary

        except Exception as e:
            logger.error(f"Error during shutdown for {email}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return shutdown_summary

    def shutdown_all_emulators(self):
        """Shutdown all running emulators gracefully.

        This method will iterate through all active automators and
        shut them down one by one.

        Returns:
            list: List of shutdown summaries for each emulator
        """
        logger.info("Starting graceful shutdown of all running emulators")
        summaries = []

        # Get a list of all emails with active automators
        active_emails = [email for email, automator in self.server.automators.items() if automator]

        if not active_emails:
            logger.info("No active emulators to shut down")
            return summaries

        logger.info(f"Found {len(active_emails)} active emulators to shut down")

        # Shut down each emulator
        for email in active_emails:
            logger.info(f"Shutting down emulator for {email}")
            summary = self.shutdown_emulator(email)
            summaries.append(summary)

            # Brief pause between shutdowns to avoid resource contention
            time.sleep(1)

        logger.info(f"Completed shutdown of {len(summaries)} emulators")
        return summaries
