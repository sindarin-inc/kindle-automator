"""Shutdown resources for managing emulator and VNC instances."""

import logging

from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class ShutdownResource(Resource):
    """Resource for shutting down emulator and VNC/xvfb display for a profile."""

    def __init__(self, server_instance=None):
        """Initialize the shutdown resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        self.shutdown_manager = EmulatorShutdownManager(server_instance)
        super().__init__()

    @ensure_automator_healthy
    def post(self):
        """Shutdown emulator and VNC/xvfb display for the email"""
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to shut down"}, 400

        # Check if we should preserve reading state (default: True)
        # Note: UI clients should pass preserve_reading_state=false for user-initiated shutdowns
        # to ensure the Kindle app navigates to library and syncs reading position
        from server.utils.request_utils import get_boolean_param

        preserve_reading_state = get_boolean_param("preserve_reading_state", default=False)
        mark_for_restart = get_boolean_param("mark_for_restart", default=False)
        cold_restart = get_boolean_param("cold", default=False)

        try:
            # Use the shutdown manager to handle the shutdown
            shutdown_summary = self.shutdown_manager.shutdown_emulator(
                sindarin_email,
                preserve_reading_state=preserve_reading_state,
                mark_for_restart=mark_for_restart or cold_restart,  # Mark for restart if cold boot requested
                skip_snapshot=cold_restart,  # Skip snapshot if cold boot requested
            )

            # If cold restart requested, restart the emulator with cold boot
            if cold_restart:
                logger.info(f"Cold restart requested for {sindarin_email}, restarting emulator...")
                # Import here to avoid circular imports
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager.get_instance()
                if (
                    avd_manager
                    and avd_manager.emulator_manager
                    and avd_manager.emulator_manager.emulator_launcher
                ):
                    # Start the emulator with cold boot flag
                    (
                        success,
                        emulator_id,
                        display_num,
                    ) = avd_manager.emulator_manager.emulator_launcher.launch_emulator(
                        sindarin_email, cold_boot=True
                    )
                    if success:
                        logger.info(f"Successfully restarted emulator {emulator_id} with cold boot")
                        shutdown_summary["cold_restarted"] = True
                    else:
                        logger.error(f"Failed to restart emulator with cold boot for {sindarin_email}")
                        shutdown_summary["cold_restarted"] = False

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
            if shutdown_summary.get("cold_restarted"):
                message_parts.append("emulator restarted with cold boot")

            if message_parts:
                message = f"Successfully shut down for {sindarin_email}: {', '.join(message_parts)}"
            else:
                message = f"No active resources found to shut down for {sindarin_email}"

            return {
                "success": True,
                "message": message,
                "details": shutdown_summary,
                "cold_restart": cold_restart,
            }, 200

        except Exception as e:
            logger.error(f"Error during shutdown for {sindarin_email}: {e}")
            return {
                "success": False,
                "error": str(e),
            }, 500

    @ensure_automator_healthy
    def get(self):
        """GET method for shutdown - same as POST"""
        return self.post()
