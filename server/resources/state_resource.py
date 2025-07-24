"""State resource for getting automator state."""

import logging
import traceback

from flask_restful import Resource

from server.core.automation_server import AutomationServer
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.utils.appium_error_utils import is_appium_error
from server.utils.request_utils import get_automator_for_request

logger = logging.getLogger(__name__)


class StateResource(Resource):
    @ensure_user_profile_loaded
    @ensure_automator_healthy
    def get(self):
        server = AutomationServer.get_instance()

        try:
            automator, _, error_response = get_automator_for_request(server)
            if error_response:
                return error_response

            # Update the current state before returning it to ensure it's not stale
            current_state = automator.state_machine.update_current_state()
            return {"state": current_state.name}, 200
        except Exception as e:
            if is_appium_error(e):
                raise
            logger.error(f"Error getting state: {e}", exc_info=True)
            logger.error(f"Traceback: {traceback.format_exc()}", exc_info=True)
            return {"error": str(e)}, 500
