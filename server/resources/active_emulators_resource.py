"""Resource for listing active emulators."""

import logging

from flask_restful import Resource

logger = logging.getLogger(__name__)


class ActiveEmulatorsResource(Resource):
    """Resource for getting list of active emulators."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    def get(self):
        """Get list of emails with active emulators."""
        try:
            # Get all emails with active automators
            active_emails = []

            for email, automator in self.server.automators.items():
                if automator is not None:
                    # Check if the automator has a running emulator
                    has_emulator = False

                    if hasattr(automator, "emulator_manager") and hasattr(
                        automator.emulator_manager, "emulator_launcher"
                    ):
                        try:
                            (
                                emulator_id,
                                _,
                            ) = automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                            if emulator_id:
                                has_emulator = True
                        except Exception as e:
                            logger.debug(f"Error checking emulator for {email}: {e}")

                    if has_emulator:
                        active_emails.append(email)

            logger.info(f"Found {len(active_emails)} active emulators")

            return {"success": True, "emulators": active_emails, "count": len(active_emails)}, 200

        except Exception as e:
            logger.error(f"Error getting active emulators: {e}")
            return {"success": False, "error": str(e)}, 500
