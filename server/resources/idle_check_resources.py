"""Idle check resources for monitoring and shutting down idle emulators."""

import logging
import time
from datetime import datetime, timedelta

from flask import request
from flask_restful import Resource

logger = logging.getLogger(__name__)


class IdleCheckResource(Resource):
    """Resource for checking idle emulators and shutting them down."""

    def __init__(self, server_instance=None):
        """Initialize the idle check resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        self.idle_timeout_minutes = 30  # Default to 30 minutes
        super().__init__()

    def get(self):
        """Check for idle emulators and shut them down."""
        return self._check_and_shutdown_idle()

    def post(self):
        """Check for idle emulators and shut them down (supports customizable timeout)."""
        # Allow custom timeout from request body
        data = request.get_json() or {}
        custom_timeout = data.get("idle_timeout_minutes", self.idle_timeout_minutes)
        return self._check_and_shutdown_idle(custom_timeout)

    def _check_and_shutdown_idle(self, timeout_minutes=None):
        """Check all running emulators and shut down those that have been idle.

        Args:
            timeout_minutes: Custom idle timeout in minutes (optional)

        Returns:
            Response with list of shut down emulators
        """
        if timeout_minutes is None:
            timeout_minutes = self.idle_timeout_minutes

        current_time = time.time()
        idle_threshold = current_time - (timeout_minutes * 60)

        shutdown_emails = []
        active_emails = []

        logger.info(f"Checking for emulators idle for more than {timeout_minutes} minutes")

        # Check each automator for idle time
        for email, automator in self.server.automators.items():
            if automator is None:
                continue

            # Get last activity time
            last_activity = self.server.get_last_activity_time(email)

            if last_activity is None:
                # If no activity recorded, consider it as just started
                logger.info(f"No activity recorded for {email}, considering it as active")
                active_emails.append(email)
                continue

            # Check if idle
            if last_activity < idle_threshold:
                idle_duration = (current_time - last_activity) / 60  # Convert to minutes
                logger.info(
                    f"Emulator for {email} has been idle for {idle_duration:.1f} minutes - shutting down"
                )

                # Use the shutdown manager directly instead of going through HTTP
                try:
                    # Import and use shutdown manager directly
                    from server.utils.emulator_shutdown_manager import EmulatorShutdownManager

                    shutdown_manager = EmulatorShutdownManager(self.server)
                    shutdown_summary = shutdown_manager.shutdown_emulator(email)

                    # Check if shutdown was successful
                    if any(shutdown_summary.values()):
                        shutdown_emails.append(
                            {
                                "email": email,
                                "idle_minutes": round(idle_duration, 1),
                                "status": "shutdown",
                                "details": shutdown_summary,
                            }
                        )
                    else:
                        logger.warning(f"No active resources found to shut down for {email}")
                        shutdown_emails.append(
                            {
                                "email": email,
                                "idle_minutes": round(idle_duration, 1),
                                "status": "failed",
                                "error": "No active resources found",
                            }
                        )

                except Exception as e:
                    logger.error(f"Error shutting down idle emulator for {email}: {e}")
                    shutdown_emails.append(
                        {
                            "email": email,
                            "idle_minutes": round(idle_duration, 1),
                            "status": "error",
                            "error": str(e),
                        }
                    )
            else:
                active_duration = (current_time - last_activity) / 60
                logger.info(
                    f"Emulator for {email} is active (last activity {active_duration:.1f} minutes ago)"
                )
                active_emails.append({"email": email, "active_minutes": round(active_duration, 1)})

        # Prepare summary
        summary = {
            "timestamp": datetime.now().isoformat(),
            "idle_timeout_minutes": timeout_minutes,
            "total_checked": len(self.server.automators),
            "shut_down": len([s for s in shutdown_emails if s.get("status") == "shutdown"]),
            "active": len(active_emails),
            "failed": len([s for s in shutdown_emails if s.get("status") != "shutdown"]),
            "shutdown_details": shutdown_emails,
            "active_emulators": active_emails,
        }

        logger.info(f"Idle check complete: {summary['shut_down']} shut down, {summary['active']} active")

        return summary, 200
