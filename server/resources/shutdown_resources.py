"""Shutdown resources for managing emulator and VNC instances."""

import logging

from flask_restful import Resource

from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
from server.utils.request_utils import get_boolean_param, get_sindarin_email

logger = logging.getLogger(__name__)


class ShutdownResource(Resource):
    """Resource for shutting down emulator and VNC/xvfb display for a profile."""

    def __init__(self, server_instance=None):
        """Initialize the shutdown resource.

        Args:
            server_instance: The AutomationServer instance (ignored, uses singleton)
        """
        # Accept server_instance for backwards compatibility but use singleton
        self.shutdown_manager = EmulatorShutdownManager()
        super().__init__()

    def _try_ensure_driver_connected(self, sindarin_email):
        """Try to ensure driver is connected with retries, but don't fail if it can't connect.

        This is important for shutdown to handle lost driver connections gracefully.
        We don't create new automators during shutdown to avoid conflicts.
        """
        # Get the automator for this email
        server = AutomationServer.get_instance()
        automator = server.automators.get(sindarin_email)

        # If no automator exists, don't create one - just proceed with shutdown
        # This avoids conflicts with concurrent shutdown attempts
        if not automator:
            logger.info(
                f"No automator found for {sindarin_email} during shutdown - proceeding without driver. "
                "Snapshot will still be attempted via ADB."
            )
            return

        # If we have an automator, try to ensure its driver is connected
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Check if driver is already connected and healthy
                if automator.driver:
                    try:
                        # Quick health check
                        automator.driver.current_activity
                        logger.info(f"Driver already connected and healthy for {sindarin_email}")
                        return
                    except Exception:
                        logger.info(
                            f"Driver exists but not healthy for {sindarin_email}, attempting to reconnect..."
                        )

                # Try to initialize/reconnect the driver
                if not automator.initialize_driver():
                    logger.warning(
                        f"Failed to initialize driver for {sindarin_email} during shutdown (attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt == max_retries - 1:
                        logger.info(
                            "Proceeding with shutdown anyway - snapshot will still be attempted via ADB"
                        )
                    continue

                logger.info(f"Successfully reconnected to driver for {sindarin_email} during shutdown")
                return

            except Exception as e:
                error_message = str(e)
                is_connection_error = any(
                    [
                        "instrumentation process is not running" in error_message,
                        "Connection refused" in error_message,
                        "session identified by" in error_message and "is not known" in error_message,
                        "NoSuchDriverException" in error_message,
                        "NoSuchDriverError" in error_message,
                        "socket hang up" in error_message,
                    ]
                )

                if is_connection_error and attempt < max_retries - 1:
                    logger.warning(
                        f"Connection error during shutdown for {sindarin_email} (attempt {attempt + 1}/{max_retries}): {error_message}"
                    )
                    continue
                else:
                    logger.warning(
                        f"Failed to connect to driver for {sindarin_email} during shutdown after {attempt + 1} attempts - "
                        "proceeding anyway. Snapshot will still be attempted via ADB."
                    )
                    return

    def post(self):
        """Shutdown emulator and VNC/xvfb display for the email"""
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to shut down"}, 400

        # Try to ensure we have a healthy automator/driver with retry logic
        # but don't fail the shutdown if we can't connect
        self._try_ensure_driver_connected(sindarin_email)

        # Check if we should preserve reading state (default: True)
        # Note: UI clients should pass preserve_reading_state=false for user-initiated shutdowns
        # to ensure the Kindle app navigates to library and syncs reading position
        preserve_reading_state = get_boolean_param("preserve_reading_state", default=False)
        mark_for_restart = get_boolean_param("mark_for_restart", default=False)
        skip_snapshot = get_boolean_param("skip_snapshot", default=False)

        try:
            # Use the shutdown manager to handle the shutdown
            shutdown_summary = self.shutdown_manager.shutdown_emulator(
                sindarin_email,
                preserve_reading_state=preserve_reading_state,
                mark_for_restart=mark_for_restart,
                skip_snapshot=skip_snapshot,
            )

            # Prepare response
            message_parts = []
            if shutdown_summary["emulator_stopped"]:
                message_parts.append("emulator stopped")
            if shutdown_summary["vnc_stopped"]:
                message_parts.append("VNC stopped")
            if shutdown_summary["xvfb_stopped"]:
                message_parts.append("Xvfb stopped")
            if shutdown_summary["automator_cleaned"]:
                message_parts.append("automator cleaned")
            if shutdown_summary["snapshot_taken"]:
                message_parts.append("snapshot taken")
            elif skip_snapshot:
                message_parts.append("snapshot skipped for cold boot")
            elif (
                not skip_snapshot
                and not shutdown_summary["snapshot_taken"]
                and (shutdown_summary["emulator_stopped"] or shutdown_summary["automator_cleaned"])
            ):
                message_parts.append("SNAPSHOT FAILED - will cold boot next time")

            # Add sync status if attempted
            if shutdown_summary.get("placemark_sync_attempted"):
                if shutdown_summary.get("placemark_sync_success"):
                    message_parts.append("placemarks synced")
                else:
                    message_parts.append("PLACEMARK SYNC FAILED")

            if message_parts:
                message = f"Successfully shut down for {sindarin_email}: {', '.join(message_parts)}"
            else:
                message = f"No active resources found to shut down for {sindarin_email}"

            # Log error if sync failed
            if shutdown_summary.get("placemark_sync_attempted") and not shutdown_summary.get(
                "placemark_sync_success"
            ):
                logger.error(
                    f"PLACEMARK SYNC FAILED during shutdown for {sindarin_email} - user's reading position may be lost!",
                    exc_info=True,
                )

            # Log error if snapshot failed (only if there was an emulator or automator to snapshot)
            if (
                not skip_snapshot
                and not shutdown_summary["snapshot_taken"]
                and (shutdown_summary["emulator_stopped"] or shutdown_summary["automator_cleaned"])
            ):
                logger.error(
                    f"SNAPSHOT FAILED during shutdown for {sindarin_email} - emulator will cold boot next time! "
                    f"This means user will need to navigate back to their book.",
                    exc_info=True,
                )

            return {
                "success": True,
                "message": message,
                "details": shutdown_summary,
                "cold_shutdown": skip_snapshot,
            }, 200

        except Exception as e:
            logger.error(f"Error during shutdown for {sindarin_email}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }, 500

    def get(self):
        """GET method for shutdown - same as POST"""
        return self.post()
