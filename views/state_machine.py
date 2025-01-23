from views.transitions import StateTransitions
from views.core.states import AppState, get_state_from_view
from views.core.logger import logger


class KindleStateMachine:
    def __init__(self, view_inspector, auth_handler, permissions_handler, library_handler):
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

        max_transitions = 5  # Maximum number of state transitions to prevent infinite loops
        transitions = 0

        while transitions < max_transitions:
            # Get current state
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

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

            transitions += 1
            logger.info(f"Completed transition {transitions}/{max_transitions}")

        logger.error(f"Failed to reach library state after {max_transitions} transitions")
        logger.error(f"Final state: {self.current_state}")
        return False
