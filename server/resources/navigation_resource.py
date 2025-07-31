"""Navigation resource for page navigation in books."""

import logging
from datetime import datetime, timezone

from flask import request
from flask_restful import Resource

from handlers.navigation_handler import NavigationResourceHandler
from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class NavigationResource(Resource):
    def __init__(self, default_direction=1):
        """Initialize the NavigationResource.

        Args:
            default_direction: Default navigation direction (1 for forward, -1 for backward)
        """
        self.default_direction = default_direction
        super().__init__()

    def _navigate_impl(self, direction=None):
        """Internal implementation for navigation - shared by GET and POST."""
        server = AutomationServer.get_instance()

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        if not sindarin_email:
            return {"error": "No email provided to identify which profile to use"}, 400

        # Get the appropriate automator
        automator = server.automators.get(sindarin_email)
        if not automator:
            return {"error": f"No automator found for {sindarin_email}"}, 404

        # Check initial state and restart if UNKNOWN
        automator.state_machine.check_initial_state_with_restart()

        # Create navigation handler
        nav_handler = NavigationResourceHandler(automator, automator.screenshots_dir)

        # Process and parse navigation parameters
        params = NavigationResourceHandler.parse_navigation_params(request)

        # If a specific direction was provided in the route initialization, override navigate_count
        if direction is not None:
            # Set the navigate_count based on the requested direction
            params["navigate_count"] = direction
        # If no navigate_count was provided in the request, use the default direction
        elif "navigate" not in request.args and "navigate" not in request.form:
            params["navigate_count"] = self.default_direction

        # Log the navigation parameters
        logger.info(f"Navigation params: {params}")

        # Mark snapshot as dirty since user navigated
        self._mark_snapshot_dirty(sindarin_email)

        # Delegate to the handler
        return nav_handler.navigate(
            navigate_count=params["navigate_count"],
            preview_count=params["preview_count"],
            show_placemark=params["show_placemark"],
            use_base64=params["use_base64"],
            perform_ocr=params["perform_ocr"],
            book_title=params.get("title"),
        )

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self, direction=None):
        """Handle page navigation via POST."""
        return self._navigate_impl(direction)

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def get(self):
        """Handle navigation via GET requests, using query parameters"""
        # For preview endpoints, add preview parameter if not present
        endpoint = request.endpoint if hasattr(request, "endpoint") else ""
        if endpoint in ["preview_next", "preview_previous"] and "preview" not in request.args:
            # Set preview=1 for preview_next and preview=-1 for preview_previous
            preview_value = 1 if endpoint == "preview_next" else -1
            # Clone request.args to a mutable dictionary and add preview parameter
            request.args = dict(request.args)
            request.args["preview"] = str(preview_value)

        # Process and parse navigation parameters
        params = NavigationResourceHandler.parse_navigation_params(request)

        # If no navigate parameter was provided, use the default direction
        if "navigate" not in request.args:
            direction = self.default_direction
        else:
            direction = None  # Will use the parsed navigate_count from params

        # Call the internal implementation
        return self._navigate_impl(direction)

    def _mark_snapshot_dirty(self, sindarin_email):
        """Mark the snapshot as dirty since the user navigated."""
        try:
            from database.repositories.user_repository import UserRepository

            user_repo = UserRepository()
            user = user_repo.get_by_email(sindarin_email)
            if user and not user.snapshot_dirty:
                user.snapshot_dirty = True
                user.snapshot_dirty_since = datetime.now(timezone.utc)
                user_repo.update(user)
                logger.info(f"Marked snapshot as dirty for {sindarin_email}")
        except Exception as e:
            logger.error(f"Error marking snapshot as dirty for {sindarin_email}: {e}", exc_info=True)
