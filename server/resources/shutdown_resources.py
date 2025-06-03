"""Shutdown resources for managing emulator and VNC instances."""

import logging

from flask_restful import Resource

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

        try:
            # Use the shutdown manager to handle the shutdown
            shutdown_summary = self.shutdown_manager.shutdown_emulator(
                sindarin_email,
                preserve_reading_state=preserve_reading_state,
                mark_for_restart=mark_for_restart,
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

            if message_parts:
                message = f"Successfully shut down for {sindarin_email}: {', '.join(message_parts)}"
            else:
                message = f"No active resources found to shut down for {sindarin_email}"

            return {
                "success": True,
                "message": message,
                "details": shutdown_summary,
            }, 200

        except Exception as e:
            logger.error(f"Error during shutdown for {sindarin_email}: {e}")
            return {
                "success": False,
                "error": str(e),
            }, 500

    def get(self):
        """GET method for shutdown - same as POST"""
        return self.post()
