"""Manager for gracefully shutting down emulators."""

import logging
import os
import platform
import signal
import subprocess
import time
import traceback
from datetime import datetime

from selenium.common.exceptions import InvalidSessionIdException

from server.utils.vnc_instance_manager import VNCInstanceManager
from server.utils.websocket_proxy_manager import WebSocketProxyManager
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

    def shutdown_emulator(self, email, preserve_reading_state=False, mark_for_restart=None):
        """Gracefully shutdown an emulator for a specific email.

        This parks the emulator in the Library view, takes a snapshot,
        then stops the emulator and cleans up resources.

        Args:
            email: The email address associated with the emulator
            preserve_reading_state: If True, keep current state instead of navigating to library
            mark_for_restart: If True, mark emulator to auto-start after server restart.
                             If None (default), uses the same value as preserve_reading_state
                             for backward compatibility.

        Returns:
            dict: Shutdown summary with status information
        """

        logger.info(
            f"Processing shutdown request for {email} (preserve_reading_state={preserve_reading_state}, mark_for_restart={mark_for_restart})"
        )

        # Mark for restart if requested (for deployment restarts)
        # or clear the flag if we're shutting down due to idle/close timer
        try:
            vnc_manager = VNCInstanceManager.get_instance()
            vnc_manager.mark_running_for_deployment(email, should_restart=mark_for_restart)
        except Exception as e:
            logger.error(f"Failed to handle was_running_at_restart flag for {email}: {e}")

        # Track what was shut down
        shutdown_summary = {
            "email": email,
            "emulator_stopped": False,
            "vnc_stopped": False,
            "xvfb_stopped": False,
            "websocket_stopped": False,
            "automator_cleaned": False,
            "snapshot_taken": False,
        }

        # Find the automator for this email
        automator = self.server.automators.get(email)
        if not automator:
            logger.info(f"No automator found for {email}, nothing to shut down")
            return shutdown_summary

        # Before shutting down, conditionally park the emulator in the Library view and take a snapshot
        ui_automator_crashed = False
        if hasattr(automator, "driver") and automator.driver:
            # Initialize state machine to handle transitions
            try:
                state_machine = KindleStateMachine(automator.driver)
            except InvalidSessionIdException:
                logger.warning(f"Emulator for {email} has no valid session ID, skipping shutdown")
                return shutdown_summary
            except Exception as e:
                # Check if this is a UiAutomator2 crash
                error_msg = str(e)
                if (
                    "instrumentation process is not running" in error_msg
                    or "UiAutomator2 server" in error_msg
                ):
                    logger.error(f"UiAutomator2 crashed for {email}, will force shutdown: {e}")
                    ui_automator_crashed = True
                else:
                    logger.error(f"Unexpected error initializing state machine for {email}: {e}")
                    ui_automator_crashed = True

            if not ui_automator_crashed and not preserve_reading_state:
                logger.info(f"Parking emulator in Library view and syncing before shutdown for {email}")
                # Transition to library (this handles navigation from any state)
                try:
                    # First check if we're in READING state
                    current_state = state_machine._get_current_state()
                    was_reading = current_state == AppState.READING

                    if was_reading:
                        logger.info("Currently in READING state - will sync before parking")

                    # Transition to library first
                    result = state_machine.transition_to_library(max_transitions=10, server=self.server)
                    if result:
                        logger.info("Successfully transitioned to Library view")

                        # If we were reading, navigate to More tab and sync
                        if was_reading and state_machine.library_handler:
                            logger.info("Navigating to More tab to sync reading progress...")

                            # Navigate to More tab
                            if state_machine.library_handler.navigate_to_more_settings():
                                logger.info("Successfully navigated to More tab")

                                # Perform sync
                                logger.info("Starting sync_in_more_tab() call...")
                                sync_result = state_machine.library_handler.sync_in_more_tab()
                                logger.info(f"sync_in_more_tab() returned: {sync_result}")
                                if sync_result:
                                    logger.info("Successfully synced in More tab")
                                else:
                                    logger.warning("Sync may not have completed fully")

                                # Navigate back to Library
                                if state_machine.library_handler.navigate_from_more_to_library():
                                    logger.info("Successfully navigated back to Library from More tab")
                                else:
                                    logger.warning("Failed to navigate back to Library from More tab")
                            else:
                                logger.warning("Failed to navigate to More tab for sync")

                        # Wait 5 seconds as requested
                        time.sleep(5)
                    else:
                        logger.warning("Failed to transition to Library view before shutdown")
                except Exception as e:
                    error_msg = str(e)
                    if (
                        "instrumentation process is not running" in error_msg
                        or "UiAutomator2 server" in error_msg
                    ):
                        logger.error(
                            f"UiAutomator2 crashed during navigation for {email}, skipping UI operations: {e}"
                        )
                        ui_automator_crashed = True
                    else:
                        logger.warning(f"Error transitioning to Library before shutdown: {e}")
                    # Continue with shutdown even if parking fails
            elif not ui_automator_crashed and preserve_reading_state:
                logger.info(f"Preserving reading state - staying in current view for {email}")
                try:
                    current_state = state_machine._get_current_state()
                    if current_state == AppState.READING:
                        logger.info(f"Emulator is in reading view - taking snapshot in current state")
                    else:
                        logger.info(f"Emulator is in {current_state} view - taking snapshot in current state")
                except Exception as e:
                    error_msg = str(e)
                    if (
                        "instrumentation process is not running" in error_msg
                        or "UiAutomator2 server" in error_msg
                    ):
                        logger.error(f"UiAutomator2 crashed while checking state for {email}: {e}")
                        ui_automator_crashed = True
                    else:
                        logger.warning(f"Error checking current state: {e}")

            # Take snapshot regardless of whether we navigated to library (unless UiAutomator2 crashed)
            if not ui_automator_crashed and hasattr(automator.emulator_manager, "emulator_launcher"):
                (
                    emulator_id,
                    _,
                ) = automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                if emulator_id:
                    logger.info(f"Taking ADB snapshot of emulator {emulator_id}")
                    # Get AVD name for cleaner snapshot naming
                    avd_name = automator.emulator_manager.emulator_launcher._extract_avd_name_from_email(
                        email
                    )
                    if avd_name and avd_name.startswith("KindleAVD_"):
                        # Extract just the email part from the AVD name
                        avd_identifier = avd_name.replace("KindleAVD_", "")
                    else:
                        avd_identifier = email.replace("@", "_").replace(".", "_")

                    if automator.emulator_manager.emulator_launcher.save_snapshot(email):
                        logger.info(f"Saved snapshot for {email}")
                        shutdown_summary["snapshot_taken"] = True
                        # Save the snapshot timestamp to the user profile for reference
                        # Even though we're using default_boot, we can track when it was last saved
                        try:
                            from views.core.avd_profile_manager import AVDProfileManager

                            avd_manager = AVDProfileManager.get_instance()
                            # Save the timestamp of when default_boot was last updated
                            snapshot_timestamp = datetime.now().isoformat()
                            avd_manager.set_user_field(email, "last_snapshot_timestamp", snapshot_timestamp)
                            # Clear the old last_snapshot field since we're not using named snapshots anymore
                            avd_manager.set_user_field(email, "last_snapshot", None)
                            logger.info(
                                f"Updated default_boot snapshot timestamp to {snapshot_timestamp} for {email}"
                            )
                        except Exception as profile_error:
                            logger.warning(f"Failed to save snapshot timestamp to profile: {profile_error}")
                        # No longer need to clean up old snapshots since we're using default_boot
                        logger.info("Using default_boot snapshot - no cleanup needed")
                    else:
                        logger.error(f"Failed to save snapshot for {email}")
            elif ui_automator_crashed:
                logger.warning(f"Skipping snapshot due to UiAutomator2 crash for {email}")
                logger.info(f"Will proceed with forced emulator shutdown for {email}")

        try:
            # Stop the emulator
            if hasattr(automator, "emulator_manager") and hasattr(
                automator.emulator_manager, "emulator_launcher"
            ):
                try:
                    emulator_id, display_num = (
                        automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                    )
                except Exception as e:
                    # Even if we can't get emulator info through normal means, try to force stop
                    logger.error(f"Error getting running emulator info for {email}: {e}")
                    logger.info(f"Attempting force shutdown for {email} despite error")
                    emulator_id = None
                    display_num = None

                    # Try to stop emulator anyway
                    try:
                        success = automator.emulator_manager.emulator_launcher.stop_emulator(email)
                        shutdown_summary["emulator_stopped"] = success
                        if success:
                            logger.info(f"Successfully force stopped emulator for {email}")
                    except Exception as stop_error:
                        logger.error(f"Failed to force stop emulator for {email}: {stop_error}")
                        shutdown_summary["emulator_stopped"] = False

                if emulator_id:
                    logger.info(f"Stopping emulator {emulator_id} for {email}")
                    success = automator.emulator_manager.emulator_launcher.stop_emulator(email)
                    shutdown_summary["emulator_stopped"] = success
                    if success:
                        logger.info(f"Successfully stopped emulator {emulator_id}")
                        # Clear the emulator_id from VNC instance immediately after stopping
                        try:
                            vnc_manager = VNCInstanceManager.get_instance()
                            vnc_manager.clear_emulator_id_for_profile(email)
                            logger.info(f"Cleared emulator_id {emulator_id} from VNC instance for {email}")
                        except Exception as e:
                            logger.error(f"Error clearing emulator_id from VNC instance: {e}")
                    else:
                        logger.error(f"Failed to stop emulator {emulator_id}")
                elif emulator_id is None and display_num is None:
                    # Already handled in the exception case above
                    pass
                else:
                    logger.info(f"No running emulator found for {email}")

                # Handle platform-specific cleanup
                if platform.system() == "Darwin":
                    # macOS: Release VNC instance and stop WebSocket proxy
                    try:
                        vnc_manager = VNCInstanceManager.get_instance()
                        vnc_manager.release_instance_from_profile(email)
                        logger.info(f"Released VNC instance for {email} on macOS")

                        # The WebSocket proxy cleanup is now handled inside release_instance_from_profile
                        # when cleanup_resources=True is passed
                        shutdown_summary["websocket_stopped"] = True
                    except Exception as e:
                        logger.error(f"Error releasing VNC instance on macOS: {e}")

                # Stop VNC and Xvfb (Linux only)
                elif display_num:
                    from server.utils.port_utils import calculate_vnc_port

                    vnc_port = calculate_vnc_port(display_num)

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

            # Clean up all ports associated with this emulator before cleaning up automator
            if emulator_id:
                logger.info(f"Cleaning up all ports for emulator {emulator_id}")
                self._cleanup_emulator_ports(emulator_id, email)

            # Clean up the automator
            if automator:
                try:
                    logger.info(f"Cleaning up automator for {email}")

                    # Also check if Appium needs to be stopped
                    # This handles cases where the automator cleanup doesn't properly stop Appium
                    try:
                        from server.utils.appium_driver import AppiumDriver

                        appium_driver = AppiumDriver.get_instance()
                        appium_info = appium_driver.get_appium_process_info(email)

                        if appium_info and appium_info.get("running"):
                            logger.info(f"Stopping Appium process for {email}")
                            appium_driver.stop_appium_for_profile(email)
                    except Exception as appium_e:
                        logger.warning(f"Error checking/stopping Appium during shutdown: {appium_e}")

                    automator.cleanup()
                    self.server.automators[email] = None
                    shutdown_summary["automator_cleaned"] = True
                except Exception as e:
                    logger.error(f"Error cleaning up automator: {e}")
                    # Even if cleanup fails, try to clear the automator reference
                    self.server.automators[email] = None

            # Clear current book tracking
            self.server.clear_current_book(email)

            return shutdown_summary

        except Exception as e:
            logger.error(f"Error during shutdown for {email}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return shutdown_summary

    def shutdown_all_emulators(self, preserve_reading_state=False):
        """Shutdown all running emulators gracefully.

        This method will iterate through all active automators and
        shut them down one by one.

        Args:
            preserve_reading_state: If True, keep current state during shutdown

        Returns:
            list: List of shutdown summaries for each emulator
        """
        logger.info(
            f"Starting graceful shutdown of all running emulators (preserve_reading_state={preserve_reading_state})"
        )
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
            summary = self.shutdown_emulator(email, preserve_reading_state=preserve_reading_state)
            summaries.append(summary)

            # Brief pause between shutdowns to avoid resource contention
            time.sleep(1)

        logger.info(f"Completed shutdown of {len(summaries)} emulators")
        return summaries

    def _cleanup_emulator_ports(self, emulator_id: str, email: str) -> None:
        """
        Clean up all ports associated with an emulator.

        This includes:
        - ADB port forwards (systemPort, chromedriverPort, mjpegServerPort)
        - WebSocket proxy port (macOS)
        - Any other ports forwarded to the emulator

        Args:
            emulator_id: The emulator device ID (e.g., "emulator-5554")
            email: Email associated with the emulator
        """
        try:
            # 1. Remove all ADB port forwards for this device
            logger.info(f"Removing all ADB port forwards for {emulator_id}")
            try:
                subprocess.run(
                    [f"adb -s {emulator_id} forward --remove-all"],
                    shell=True,
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                logger.info(f"Successfully removed all ADB port forwards for {emulator_id}")
            except Exception as e:
                logger.error(f"Error removing ADB port forwards: {e}")

            # 2. Kill any lingering UiAutomator2 processes on the device
            logger.info(f"Killing UiAutomator2 processes on {emulator_id}")
            try:
                subprocess.run(
                    [f"adb -s {emulator_id} shell pkill -f uiautomator"],
                    shell=True,
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            except Exception as e:
                logger.warning(f"Error killing UiAutomator2 processes: {e}")

            # 3. Get VNC instance to find all associated ports
            try:
                vnc_manager = VNCInstanceManager.get_instance()
                instance = vnc_manager.get_instance_for_profile(email)

                if instance:
                    # Get all ports from the instance
                    ports_to_check = []

                    # Appium ports
                    if "appium_port" in instance:
                        ports_to_check.append(instance["appium_port"])
                    if "appium_system_port" in instance:
                        ports_to_check.append(instance["appium_system_port"])
                    if "appium_chromedriver_port" in instance:
                        ports_to_check.append(instance["appium_chromedriver_port"])
                    if "appium_mjpeg_server_port" in instance:
                        ports_to_check.append(instance["appium_mjpeg_server_port"])

                    # Check and kill any processes on these ports
                    for port in ports_to_check:
                        self._kill_process_on_port(port)

                    # On macOS, ensure WebSocket proxy is stopped
                    if platform.system() == "Darwin":
                        try:
                            from server.utils.websocket_proxy_manager import (
                                WebSocketProxyManager,
                            )

                            ws_manager = WebSocketProxyManager.get_instance()
                            if ws_manager.is_proxy_running(email):
                                logger.info(f"Stopping WebSocket proxy for {email}")
                                ws_manager.stop_proxy(email)
                        except Exception as e:
                            logger.warning(f"Error stopping WebSocket proxy: {e}")

            except Exception as e:
                logger.error(f"Error getting VNC instance for port cleanup: {e}")

        except Exception as e:
            logger.error(f"Error in _cleanup_emulator_ports: {e}")

    def _kill_process_on_port(self, port: int) -> None:
        """
        Kill any process listening on the specified port.

        Args:
            port: Port number to check and kill processes on
        """
        if not port:
            return

        try:
            # Check if anything is listening on the port
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, check=False
            )

            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    try:
                        logger.info(f"Killing process {pid} on port {port}")
                        os.kill(int(pid), signal.SIGTERM)
                        # Give it a moment to die gracefully
                        time.sleep(0.5)
                        # Force kill if still alive
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except ProcessLookupError:
                            # Process already dead, that's fine
                            pass
                    except Exception as e:
                        logger.warning(f"Error killing process {pid}: {e}")
        except Exception as e:
            logger.warning(f"Error checking for processes on port {port}: {e}")
