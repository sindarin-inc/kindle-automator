"""Shutdown resources for managing emulator and VNC instances."""

import logging
import platform
import subprocess
import traceback

from flask import request
from flask_restful import Resource

from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.utils.request_utils import get_sindarin_email
from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)


class ShutdownResource(Resource):
    """Resource for shutting down emulator and VNC/xvfb display for a profile."""

    def __init__(self, server_instance=None):
        """Initialize the shutdown resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    @ensure_user_profile_loaded
    def post(self):
        """Shutdown emulator and VNC/xvfb display for the email"""
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to shut down"}, 400

        logger.info(f"Processing shutdown request for {sindarin_email}")

        # Find the automator for this email
        automator = self.server.automators.get(sindarin_email)
        if not automator:
            logger.info(f"No automator found for {sindarin_email}, nothing to shut down")
            return {"success": True, "message": f"No running instances found for {sindarin_email}"}, 200

        # Track what was shut down
        shutdown_summary = {
            "email": sindarin_email,
            "emulator_stopped": False,
            "vnc_stopped": False,
            "xvfb_stopped": False,
            "automator_cleaned": False,
        }

        try:
            # Stop the emulator
            if hasattr(automator, "emulator_manager") and hasattr(
                automator.emulator_manager, "emulator_launcher"
            ):
                emulator_id, display_num = automator.emulator_manager.emulator_launcher.get_running_emulator(
                    sindarin_email
                )
                if emulator_id:
                    logger.info(f"Stopping emulator {emulator_id} for {sindarin_email}")
                    success = automator.emulator_manager.emulator_launcher.stop_emulator(sindarin_email)
                    shutdown_summary["emulator_stopped"] = success
                    if success:
                        logger.info(f"Successfully stopped emulator {emulator_id}")
                    else:
                        logger.error(f"Failed to stop emulator {emulator_id}")
                else:
                    logger.info(f"No running emulator found for {sindarin_email}")

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
                        vnc_manager.release_instance_from_profile(sindarin_email)
                        logger.info(f"Released VNC instance for {sindarin_email}")
                    except Exception as e:
                        logger.error(f"Error releasing VNC instance: {e}")

            # Clean up the automator
            if automator:
                try:
                    logger.info(f"Cleaning up automator for {sindarin_email}")
                    automator.cleanup()
                    self.server.automators[sindarin_email] = None
                    shutdown_summary["automator_cleaned"] = True
                except Exception as e:
                    logger.error(f"Error cleaning up automator: {e}")

            # Clear current book tracking
            self.server.clear_current_book(sindarin_email)

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
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "details": shutdown_summary,
            }, 500

    def get(self):
        """GET method for shutdown - same as POST"""
        return self.post()
