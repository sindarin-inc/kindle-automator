"""Dashboard resource for VNC viewing and other dashboard functionality."""

import logging
import socket
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
                stmt = (
                    select(VNCInstance)
                    .where(VNCInstance.assigned_profile.isnot(None))
                    .order_by(VNCInstance.server_name, VNCInstance.display)
                )
                instances = session.execute(stmt).scalars().all()

                # Get current server name for localhost handling
                current_server = socket.gethostname()

                vnc_list = []
                for instance in instances:
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

                    vnc_info = {
                        "server_name": instance.server_name,
                        "vnc_host": vnc_host,
                        "vnc_port": instance.vnc_port,
                        "ws_port": ws_port,  # WebSocket port for noVNC
                        "display": instance.display,
                        "user_email": instance.assigned_profile,
                        "emulator_id": instance.emulator_id,
                        "is_booting": instance.is_booting,
                        "appium_running": instance.appium_running,
                        "created_at": instance.created_at.isoformat() if instance.created_at else None,
                        "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                    }
                    vnc_list.append(vnc_info)

                logger.info(f"Found {len(vnc_list)} active VNC instances across all servers")

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
