import time
from views.states import AppState, get_state_from_view
from views.transitions import StateTransitions
from .logger import logger


class KindleStateMachine:
    def __init__(
        self, view_inspector, auth_handler, permissions_handler, library_handler
    ):
        logger.info("Initializing Kindle State Machine...")
        self.view_inspector = view_inspector
        self.transitions = StateTransitions(
            view_inspector, auth_handler, permissions_handler, library_handler
        )
        self.current_state = AppState.UNKNOWN

    def _get_current_state(self):
        """Get current app state using view inspector"""
        logger.info("Checking current app state...")
        view = self.view_inspector.get_current_view()
        state = get_state_from_view(view)
        logger.info(f"View '{view}' maps to state: {state}")
        return state

    def transition_to_library(self):
        """Main method to ensure we reach the library state"""
        logger.info("Attempting to reach library state...")

        # Get current state
        self.current_state = self._get_current_state()

        # If we're in library, we're done
        if self.current_state == AppState.LIBRARY:
            logger.info("Successfully reached library state!")
            return True

        # Get handler for current state
        logger.info(f"Looking for handler for state: {self.current_state}")
        handler = self.transitions.get_handler_for_state(self.current_state)
        if not handler:
            logger.error(f"No handler found for state {self.current_state}")
            return False

        # Execute handler
        logger.info(f"Executing handler for state {self.current_state}...")
        if not handler():
            logger.error(f"Handler failed for state {self.current_state}")
            return False

        # Check if we reached library state
        self.current_state = self._get_current_state()
        success = self.current_state == AppState.LIBRARY
        if success:
            logger.info("Successfully reached library state!")
        else:
            logger.error(
                f"Failed to reach library state, ended in {self.current_state}"
            )
        return success
