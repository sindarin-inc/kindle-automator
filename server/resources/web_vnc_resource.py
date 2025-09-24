"""Web VNC resource for single-user VNC viewing."""

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path

from flask import make_response, request
from flask_restful import Resource
from sqlalchemy import select

from database.connection import db_connection
from database.models import User, VNCInstance
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class WebVNCResource(Resource):
    """Resource for single-user VNC viewing functionality."""

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        """
        Get VNC viewer for a specific user's emulator.

        Query params:
        - user_email or sindarin_email: Email of the user whose emulator to view
        - format: 'json' for data, 'html' for page (default: html)
        """
        # Get the user email from request
        user_email = get_sindarin_email()
        if not user_email:
            return {"error": "No email provided to identify which emulator to view"}, 400

        # Check requested format
        response_format = request.args.get("format", "html").lower()

        if response_format == "json":
            return self._get_vnc_data(user_email)
        else:
            return self._get_vnc_html(user_email)

    def _get_vnc_data(self, user_email):
        """Get VNC instance data for a specific user as JSON."""
        try:
            with db_connection.get_session() as session:
                # Get VNC instance for the specific user
                stmt = (
                    select(VNCInstance, User.last_used)
                    .join(User, User.email == VNCInstance.assigned_profile, isouter=True)
                    .where(VNCInstance.assigned_profile == user_email)
                )
                result = session.execute(stmt).first()

                if not result:
                    return {
                        "success": False,
                        "error": f"No active emulator found for {user_email}",
                    }, 404

                instance = result[0]
                last_used = result[1]

                # Get current server name for localhost handling
                current_server = socket.gethostname()

                # Map server names to accessible hostnames
                server_hostname_map = {
                    "kindle-automator-1": "kindle1.sindarin.com",
                    "kindle-automator-3": "kindle3.sindarin.com",
                    "kindle-automator-staging": "kindle-staging.sindarin.com",
                }

                # Determine the VNC host
                if instance.server_name in server_hostname_map:
                    vnc_host = server_hostname_map[instance.server_name]
                elif instance.server_name == current_server:
                    vnc_host = "localhost"
                else:
                    vnc_host = instance.server_name

                # Calculate WebSocket port (VNC port + 1000)
                ws_port = instance.vnc_port + 1000

                # Calculate session duration in minutes
                session_duration_minutes = None
                if instance.boot_started_at:
                    boot_time = instance.boot_started_at
                    if boot_time.tzinfo is None:
                        boot_time = boot_time.replace(tzinfo=timezone.utc)

                    now = datetime.now(timezone.utc)
                    duration = now - boot_time
                    session_duration_minutes = int(duration.total_seconds() / 60)

                # Calculate idle state based on last_used (2 minutes = 120 seconds)
                is_idle = False
                if last_used and not instance.is_booting:
                    if last_used.tzinfo is None:
                        last_used = last_used.replace(tzinfo=timezone.utc)

                    now = datetime.now(timezone.utc)
                    time_since_activity = now - last_used
                    is_idle = time_since_activity.total_seconds() > 120  # 2 minutes

                vnc_info = {
                    "server_name": instance.server_name,
                    "vnc_host": vnc_host,
                    "vnc_port": instance.vnc_port,
                    "ws_port": ws_port,
                    "display": instance.display,
                    "user_email": instance.assigned_profile,
                    "emulator_id": instance.emulator_id,
                    "emulator_port": instance.emulator_port,
                    "is_booting": instance.is_booting,
                    "is_idle": is_idle,
                    "last_used": last_used.isoformat() if last_used else None,
                    "appium_running": instance.appium_running,
                    "session_duration_minutes": session_duration_minutes,
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                }

                return {
                    "success": True,
                    "vnc_instance": vnc_info,
                    "current_server": current_server,
                }, 200

        except Exception as e:
            logger.error(f"Error getting VNC instance for {user_email}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500

    def _get_vnc_html(self, user_email):
        """Serve the web VNC HTML page for a specific user."""
        # Read the HTML file
        html_path = Path(__file__).parent.parent / "templates" / "web-vnc.html"

        try:
            with open(html_path, "r") as f:
                html_content = f.read()

            # Replace the user email placeholder
            html_content = html_content.replace("{{USER_EMAIL}}", user_email)

            response = make_response(html_content)
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            return response

        except FileNotFoundError:
            logger.error(f"Web VNC HTML file not found at {html_path}")
            return {"error": "Web VNC page not found"}, 404
        except Exception as e:
            logger.error(f"Error serving web VNC HTML: {e}", exc_info=True)
            return {"error": "Internal server error"}, 500
