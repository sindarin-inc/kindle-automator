"""Dashboard resource for VNC viewing and other dashboard functionality."""

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path

from flask import make_response, request
from flask_restful import Resource
from sqlalchemy import select

from database.connection import db_connection
from database.models import VNCInstance

logger = logging.getLogger(__name__)


class DashboardResource(Resource):
    """Resource for dashboard functionality including VNC viewer."""

    def get(self):
        """
        Get dashboard data or HTML page.

        Query params:
        - format: 'json' for data, 'html' for page (default: html)
        """
        # Check staff authentication via cookie
        token = request.cookies.get("staff_token")
        if not token:
            return {"error": "Staff authentication required"}, 401

        # Check requested format
        response_format = request.args.get("format", "html").lower()

        if response_format == "json":
            return self._get_vnc_data()
        else:
            return self._get_dashboard_html()

    def _get_vnc_data(self):
        """Get VNC instance data as JSON."""
        try:
            with db_connection.get_session() as session:
                # Get all VNC instances that have an assigned profile (active emulator)
                # Also join with User table to get last_used
                from database.models import User

                stmt = (
                    select(VNCInstance, User.last_used)
                    .join(User, User.email == VNCInstance.assigned_profile, isouter=True)
                    .where(VNCInstance.assigned_profile.isnot(None))
                    .order_by(VNCInstance.server_name, VNCInstance.display)
                )
                results = session.execute(stmt).all()

                # Get current server name for localhost handling
                current_server = socket.gethostname()

                vnc_list = []
                for row in results:
                    instance = row[0]
                    last_used = row[1]
                    # Map server names to accessible hostnames
                    server_hostname_map = {
                        "kindle-automator-1": "kindle1.sindarin.com",
                        "kindle-automator-3": "kindle3.sindarin.com",
                        "kindle-automator-staging": "kindle-staging.sindarin.com",
                    }

                    # Determine the VNC host - use mapped hostname if available, otherwise use server name
                    # Only use localhost for local development (when server is not in the map)
                    if instance.server_name in server_hostname_map:
                        vnc_host = server_hostname_map[instance.server_name]
                    elif instance.server_name == current_server:
                        # Only use localhost for local development
                        vnc_host = "localhost"
                    else:
                        # Use the server name as-is
                        vnc_host = instance.server_name

                    # Calculate WebSocket port (VNC port + 1000)
                    ws_port = instance.vnc_port + 1000

                    # Calculate session duration in minutes
                    session_duration_minutes = None
                    if instance.boot_started_at:
                        # Make sure boot_started_at is timezone-aware
                        boot_time = instance.boot_started_at
                        if boot_time.tzinfo is None:
                            boot_time = boot_time.replace(tzinfo=timezone.utc)

                        now = datetime.now(timezone.utc)
                        duration = now - boot_time
                        session_duration_minutes = int(duration.total_seconds() / 60)

                    # Calculate idle state and duration based on last_used (2 minutes = 120 seconds)
                    is_idle = False
                    idle_duration_minutes = None
                    if last_used and not instance.is_booting:
                        # Make sure last_used is timezone-aware
                        if last_used.tzinfo is None:
                            last_used = last_used.replace(tzinfo=timezone.utc)

                        now = datetime.now(timezone.utc)
                        time_since_activity = now - last_used
                        idle_seconds = time_since_activity.total_seconds()
                        is_idle = idle_seconds > 120  # 2 minutes

                        # Calculate idle duration in minutes if idle
                        if is_idle:
                            idle_duration_minutes = int(idle_seconds / 60)

                    vnc_info = {
                        "server_name": instance.server_name,
                        "vnc_host": vnc_host,
                        "vnc_port": instance.vnc_port,
                        "ws_port": ws_port,  # WebSocket port for noVNC
                        "display": instance.display,
                        "user_email": instance.assigned_profile,
                        "emulator_id": instance.emulator_id,
                        "emulator_port": instance.emulator_port,
                        "is_booting": instance.is_booting,
                        "is_idle": is_idle,
                        "idle_duration_minutes": idle_duration_minutes,
                        "last_used": last_used.isoformat() if last_used else None,
                        "appium_running": instance.appium_running,
                        "session_duration_minutes": session_duration_minutes,
                        "created_at": instance.created_at.isoformat() if instance.created_at else None,
                        "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                    }
                    vnc_list.append(vnc_info)

                return {
                    "success": True,
                    "vnc_instances": vnc_list,
                    "count": len(vnc_list),
                    "current_server": current_server,
                }, 200

        except Exception as e:
            logger.error(f"Error getting VNC instances for dashboard: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500

    def _get_dashboard_html(self):
        """Serve the dashboard HTML page."""
        # Read the HTML file
        html_path = Path(__file__).parent.parent / "templates" / "vnc-dashboard.html"

        try:
            with open(html_path, "r") as f:
                html_content = f.read()

            response = make_response(html_content)
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            return response

        except FileNotFoundError:
            logger.error(f"Dashboard HTML file not found at {html_path}")
            return {"error": "Dashboard page not found"}, 404
        except Exception as e:
            logger.error(f"Error serving dashboard HTML: {e}", exc_info=True)
            return {"error": "Internal server error"}, 500
