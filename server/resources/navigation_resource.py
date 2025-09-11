"""Navigation resource for page navigation in books."""

import logging
from datetime import datetime, timezone

from flask import request
from flask_restful import Resource

from handlers.navigation_handler import NavigationResourceHandler
from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.request_deduplication_middleware import deduplicate_request
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

        # Check for book_session_key parameter
        book_session_key = request.args.get("book_session_key") or request.form.get("book_session_key")
        if request.is_json and request.json:
            book_session_key = request.json.get("book_session_key", book_session_key)

        # Handle absolute position parameters (navigate_to and preview_to)
        # Convert them to relative movements based on current position
        if params.get("navigate_to") is not None or params.get("preview_to") is not None:
            # Get the current book title to work with sessions
            current_book = server.get_current_book(sindarin_email)

            # If navigate_to is specified, handle with session tracking
            if params.get("navigate_to") is not None:
                target_position = params["navigate_to"]

                # If we have a session key, use the database to calculate adjustment
                if book_session_key and current_book:
                    from database.connection import get_db
                    from database.repositories.book_session_repository import (
                        BookSessionRepository,
                    )

                    with get_db() as session:
                        book_session_repo = BookSessionRepository(session)

                        # Calculate the adjustment needed based on session tracking
                        adjustment, navigation_allowed, server_session_key = (
                            book_session_repo.calculate_position_adjustment(
                                sindarin_email, current_book, book_session_key, target_position
                            )
                        )

                        if not navigation_allowed:
                            # Session key mismatch - client needs to reset
                            logger.warning(f"Navigation rejected for {sindarin_email}. Session key mismatch.")
                            return {
                                "success": False,
                                "error": "session_key_mismatch",
                                "message": "Your session is out of sync. Please reset your position tracking.",
                                "current_session_key": server_session_key,
                                "current_position": 0,  # Client should reset to 0
                            }, 400

                        params["navigate_count"] = adjustment
                        logger.info(
                            f"Session-aware navigate_to={target_position}: adjustment={adjustment} "
                            f"(session_key={book_session_key[:8]}...)"
                        )
                else:
                    # No session key or book - fall back to simple position tracking
                    current_position = server.get_position(sindarin_email)
                    params["navigate_count"] = target_position - current_position
                    logger.info(
                        f"Converting absolute navigate_to={target_position} to relative: current={current_position}, delta={params['navigate_count']}"
                    )

            # If preview_to is specified, calculate relative preview movement
            if params.get("preview_to") is not None:
                preview_target = params["preview_to"]

                # If we have a session key, use session-aware position calculation
                if book_session_key and current_book:
                    from database.connection import get_db
                    from database.repositories.book_session_repository import (
                        BookSessionRepository,
                    )

                    with get_db() as session:
                        book_session_repo = BookSessionRepository(session)

                        # Get or create session to track client's perspective
                        book_session = book_session_repo.get_or_create_session(
                            sindarin_email,
                            current_book,
                            book_session_key,
                            server.get_position(sindarin_email),  # Current position from client's perspective
                        )

                        # Calculate preview relative to session position
                        final_position = book_session.position + params.get("navigate_count", 0)
                        params["preview_count"] = preview_target - final_position
                        logger.info(
                            f"Session-aware preview_to={preview_target}: session_pos={book_session.position}, "
                            f"final_pos={final_position}, preview_delta={params['preview_count']} "
                            f"(session_key={book_session_key[:8]}...)"
                        )
                else:
                    # No session key - fall back to simple position tracking
                    current_position = server.get_position(sindarin_email)
                    final_position = current_position + params.get("navigate_count", 0)
                    params["preview_count"] = preview_target - final_position
                    logger.info(
                        f"Converting absolute preview_to={preview_target} to relative: position_after_nav={final_position}, preview_delta={params['preview_count']}"
                    )

        # If a specific direction was provided in the route initialization, override navigate_count
        elif direction is not None:
            # Set the navigate_count based on the requested direction
            params["navigate_count"] = direction
        # If no navigate_count was provided in the request AND no preview was specified,
        # use the default direction. If preview is specified without navigate, navigate should be 0.
        elif (
            "navigate" not in request.args
            and "navigate" not in request.form
            and params.get("navigate_to") is None
        ):
            # Only use default direction if preview is also not specified
            if (
                "preview" not in request.args
                and "preview" not in request.form
                and params.get("preview_to") is None
            ):
                params["navigate_count"] = self.default_direction
            # Otherwise navigate_count stays at 0 (from parse_navigation_params)

        # Log the navigation parameters
        logger.info(f"Navigation params: {params}")

        # Mark snapshot as dirty since user navigated (before actual navigation)
        self._mark_snapshot_dirty(sindarin_email)

        # Delegate to the handler
        result = nav_handler.navigate(
            navigate_count=params["navigate_count"],
            preview_count=params["preview_count"],
            show_placemark=params["show_placemark"],
            use_base64=params["use_base64"],
            perform_ocr=params["perform_ocr"],
            book_title=params.get("title"),
        )

        # Extract the response and status code from the result
        if isinstance(result, tuple) and len(result) == 2:
            response, status_code = result
        else:
            # Handle unexpected return format
            response = result
            status_code = 200 if isinstance(result, dict) and result.get("success") else 500

        # Update position if navigation was successful
        # IMPORTANT: Only navigation updates position, NOT preview
        navigate_count = params.get("navigate_count", 0)
        preview_count = params.get("preview_count", 0)

        # Update position after successful navigation (but not preview)
        if status_code == 200 and isinstance(response, dict) and response.get("success"):
            # Update server position if we actually navigated
            if navigate_count != 0:
                new_position = server.update_position(sindarin_email, navigate_count)
            else:
                new_position = server.get_position(sindarin_email)

            # Always update the book session position after successful navigation
            current_book = server.get_current_book(sindarin_email)
            if current_book:
                from database.connection import get_db
                from database.repositories.book_session_repository import (
                    BookSessionRepository,
                )

                with get_db() as session:
                    book_session_repo = BookSessionRepository(session)
                    # If using navigate_to, use the target position, otherwise use calculated position
                    final_position = (
                        params.get("navigate_to") if params.get("navigate_to") is not None else new_position
                    )
                    # Update the existing session's position (don't create new sessions during navigation)
                    updated = book_session_repo.update_position(sindarin_email, current_book, final_position)
                    if updated:
                        logger.debug(
                            f"Updated book session position to {final_position} for {sindarin_email}"
                        )
                    else:
                        logger.warning(f"No book session found to update for {sindarin_email}/{current_book}")

            if navigate_count != 0:
                if preview_count != 0:
                    logger.info(
                        f"Updated position for {sindarin_email} by {navigate_count} (navigate={navigate_count}, preview={preview_count} did not affect position) to {new_position}"
                    )
                else:
                    logger.info(
                        f"Updated position for {sindarin_email} by {navigate_count} to {new_position}"
                    )
        elif navigate_count != 0:
            logger.info(
                f"Navigation failed or returned non-success, not updating position for {sindarin_email}"
            )
        elif preview_count != 0 and status_code == 200:
            # Preview was successful but doesn't update position
            logger.info(f"Preview={preview_count} successful for {sindarin_email}, position unchanged")

        return response, status_code

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
    @handle_automator_response
    def post(self, direction=None):
        """Handle page navigation via POST."""
        return self._navigate_impl(direction)

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @deduplicate_request
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

        # If no navigate parameter was provided AND no preview was specified, use the default direction
        if "navigate" not in request.args and "preview" not in request.args:
            direction = self.default_direction
        else:
            direction = None  # Will use the parsed navigate_count from params

        # Call the internal implementation
        return self._navigate_impl(direction)

    def _mark_snapshot_dirty(self, sindarin_email):
        """Mark the snapshot as dirty since the user navigated."""
        try:
            from database.connection import get_db
            from database.repositories.user_repository import UserRepository

            with get_db() as session:
                user_repo = UserRepository(session)
                # Use the repository method to update snapshot dirty status
                success = user_repo.update_snapshot_dirty_status(
                    sindarin_email, is_dirty=True, dirty_since=datetime.now(timezone.utc)
                )
                if success:
                    logger.info(f"Marked snapshot as dirty for {sindarin_email}")
        except Exception as e:
            logger.error(f"Error marking snapshot as dirty for {sindarin_email}: {e}", exc_info=True)
