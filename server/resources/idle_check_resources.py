"""Idle check resources for monitoring and shutting down idle emulators."""

import logging
import platform
import time
from datetime import datetime, timedelta

from flask import request
from flask_restful import Resource

from server.core.automation_server import AutomationServer
from server.logging_config import IdleTimerContext
from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
from server.utils.request_utils import email_override
from server.utils.vnc_instance_manager import VNCInstanceManager

logger = logging.getLogger(__name__)


class IdleCheckResource(Resource):
    """Resource for checking idle emulators and shutting them down."""

    def __init__(self, server_instance=None):
        """Initialize the idle check resource.

        Args:
            server_instance: The AutomationServer instance (ignored, uses singleton)
        """
        # Accept server_instance for backwards compatibility but use singleton
        # Mac emulators get 30 minutes, Linux gets 3 hours
        if platform.system() == "Darwin":
            self.idle_timeout_minutes = 30  # 30 minutes for Mac
        else:
            self.idle_timeout_minutes = 180  # 3 hours for Linux
        super().__init__()

    def get(self):
        """Check for idle emulators and shut them down."""
        # Get timeout from query parameter only if we're in a request context
        timeout_minutes = None
        if request:
            try:
                timeout_minutes = request.args.get("minutes", type=int)
            except RuntimeError:
                # Outside request context, use default
                pass
        return self._check_and_shutdown_idle(timeout_minutes)

    def post(self):
        """Check for idle emulators and shut them down (supports customizable timeout)."""
        # Allow custom timeout from request body only if we're in a request context
        custom_timeout = self.idle_timeout_minutes
        if request:
            try:
                data = request.get_json() or {}
                custom_timeout = data.get("idle_timeout_minutes", self.idle_timeout_minutes)
            except RuntimeError:
                # Outside request context, use default
                pass
        return self._check_and_shutdown_idle(custom_timeout)

    def _check_and_shutdown_idle(self, timeout_minutes=None):
        """Check all running emulators and shut down those that have been idle.

        Args:
            timeout_minutes: Custom idle timeout in minutes (optional)

        Returns:
            Response with list of shut down emulators
        """
        with IdleTimerContext(__name__):
            if timeout_minutes is None:
                timeout_minutes = self.idle_timeout_minutes

            current_time = time.time()
            idle_threshold = current_time - (timeout_minutes * 60)

            shutdown_emails = []
            active_emails = []

            logger.info(f"Checking for emulators idle for more than {timeout_minutes} minutes")

            # Check each automator for idle time
            server = AutomationServer.get_instance()
            # Create a list copy to avoid dictionary modification during iteration
            automator_items = list(server.automators.items())
            for email, automator in automator_items:
                if automator is None:
                    continue

                # Check if emulator is currently booting
                vnc_manager = VNCInstanceManager.get_instance()
                if vnc_manager.repository.is_booting(email):
                    logger.info(f"Emulator for {email} is currently booting, skipping idle check")
                    active_emails.append({"email": email, "status": "booting"})
                    continue

                # Get last activity time
                server = AutomationServer.get_instance()
                last_activity = server.get_last_activity_time(email)

                if last_activity is None:
                    # If no activity recorded, consider it idle and shut it down
                    logger.info(f"No last_used timestamp for {email} - shutting down as idle")
                    # Treat as infinitely idle (use a large idle duration for logging)
                    idle_duration = 9999  # minutes

                    # Use the shutdown manager directly
                    try:
                        shutdown_manager = EmulatorShutdownManager(server)
                        with email_override(email):
                            shutdown_summary = shutdown_manager.shutdown_emulator(
                                email, preserve_reading_state=False, mark_for_restart=False
                            )

                        # Check if shutdown was successful
                        if any(shutdown_summary.values()):
                            shutdown_emails.append(
                                {
                                    "email": email,
                                    "idle_minutes": idle_duration,
                                    "status": "shutdown",
                                    "reason": "no_last_used_timestamp",
                                    "details": shutdown_summary,
                                }
                            )
                        else:
                            logger.warning(f"No active resources found to shut down for {email}")
                            shutdown_emails.append(
                                {
                                    "email": email,
                                    "idle_minutes": idle_duration,
                                    "status": "failed",
                                    "error": "No active resources found",
                                }
                            )

                    except Exception as e:
                        logger.error(f"Error shutting down idle emulator for {email}: {e}", exc_info=True)
                        shutdown_emails.append(
                            {
                                "email": email,
                                "idle_minutes": idle_duration,
                                "status": "error",
                                "error": str(e),
                            }
                        )
                    continue

                # Check if idle
                if last_activity < idle_threshold:
                    idle_duration = (current_time - last_activity) / 60  # Convert to minutes
                    logger.info(
                        f"Emulator for {email} has been idle for {idle_duration:.1f} minutes ({current_time} - {last_activity} = {current_time - last_activity}) - shutting down"
                    )

                    # Use the shutdown manager directly instead of going through HTTP
                    try:
                        server = AutomationServer.get_instance()
                        shutdown_manager = EmulatorShutdownManager(server)
                        # Idle shutdowns should navigate to library and NOT mark for restart
                        # Set email context for shutdown operations
                        with email_override(email):
                            shutdown_summary = shutdown_manager.shutdown_emulator(
                                email, preserve_reading_state=False, mark_for_restart=False
                            )

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
                        logger.error(f"Error shutting down idle emulator for {email}: {e}", exc_info=True)
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
            server = AutomationServer.get_instance()
            summary = {
                "timestamp": datetime.now().isoformat(),
                "idle_timeout_minutes": timeout_minutes,
                "total_checked": len(server.automators),
                "shut_down": len([s for s in shutdown_emails if s.get("status") == "shutdown"]),
                "active": len(active_emails),
                "failed": len([s for s in shutdown_emails if s.get("status") != "shutdown"]),
                "shutdown_details": shutdown_emails,
                "active_emulators": active_emails,
            }

            logger.info(f"Idle check complete: {summary['shut_down']} shut down, {summary['active']} active")

            return summary, 200
