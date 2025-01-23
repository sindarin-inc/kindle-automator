from views.core.logger import logger
from views.core.app_state import AppState
from views.transitions import StateTransitions


class KindleStateMachine:
    """State machine for managing Kindle app states and transitions."""

    def __init__(self, view_inspector, auth_handler, permissions_handler, library_handler):
        """Initialize the state machine with required handlers."""
        self.view_inspector = view_inspector
        self.transitions = StateTransitions(
            view_inspector, auth_handler, permissions_handler, library_handler
        )
        self.current_state = AppState.UNKNOWN

    def _get_current_state(self):
        """Get the current app state using the view inspector."""
        view = self.view_inspector.get_current_view()
        logger.info(f"View {view} maps to state {AppState[view.name]}")
        return AppState[view.name]

    def transition_to_library(self, max_transitions=5):
        """Attempt to transition to the library state.

        Args:
            max_transitions (int): Maximum number of transitions to attempt before giving up.
                                 This prevents infinite loops.

        Returns:
            bool: True if library state was reached, False otherwise.
        """
        transitions = 0
        while transitions < max_transitions:
            self.current_state = self._get_current_state()
            logger.info(f"Current state: {self.current_state}")

            if self.current_state == AppState.LIBRARY:
                logger.info("Successfully reached library state")
                return True

            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                logger.error(f"No handler found for state {self.current_state}")
                return False

            if not handler():
                logger.error(f"Handler failed for state {self.current_state}")
                return False

            transitions += 1

        logger.error(f"Failed to reach library state after {max_transitions} transitions")
        logger.error(f"Final state: {self.current_state}")
        return False
