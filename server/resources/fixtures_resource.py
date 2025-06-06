"""Fixtures resource for creating test fixtures."""

import logging
import traceback

from flask_restful import Resource

from handlers.test_fixtures_handler import TestFixturesHandler
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_automator_for_request

logger = logging.getLogger(__name__)


class FixturesResource(Resource):
    """Resource for creating test fixtures."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def post(self):
        """Create fixtures for major views"""
        try:
            automator, _, error_response = get_automator_for_request(self.server)
            if error_response:
                return error_response

            fixtures_handler = TestFixturesHandler(automator.driver)
            if fixtures_handler.create_fixtures():
                return {"status": "success", "message": "Created fixtures for all major views"}, 200
            return {"error": "Failed to create fixtures"}, 500

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error creating fixtures: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}, 500
