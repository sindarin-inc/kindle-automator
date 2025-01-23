import time
from views.states import AppState, get_state_from_view
from views.transitions import StateTransitions


class KindleStateMachine:
    def __init__(
        self, view_inspector, auth_handler, permissions_handler, library_handler
    ):
        print("Initializing Kindle State Machine...")
        self.view_inspector = view_inspector
        self.transitions = StateTransitions(
            view_inspector, auth_handler, permissions_handler, library_handler
        )
        self.current_state = AppState.UNKNOWN

    def _get_current_state(self):
        """Get current app state using view inspector"""
        print("\nChecking current app state...")
        view = self.view_inspector.get_current_view()
        state = get_state_from_view(view)
        print(f"View '{view}' maps to state: {state}")
        return state

    def transition_to_library(self, max_attempts=5):
        """Main method to ensure we reach the library state"""
        print(f"\nAttempting to reach library state (max {max_attempts} attempts)...")
        attempts = 0

        while attempts < max_attempts:
            attempts += 1
            print(f"\n=== Attempt {attempts}/{max_attempts} to reach library state ===")

            # Get current state
            self.current_state = self._get_current_state()

            # If we're in library, we're done
            if self.current_state == AppState.LIBRARY:
                print("Successfully reached library state!")
                return True

            # Get handler for current state
            print(f"Looking for handler for state: {self.current_state}")
            handler = self.transitions.get_handler_for_state(self.current_state)
            if not handler:
                print(f"No handler found for state {self.current_state}")
                return False

            # Execute handler
            print(f"Executing handler for state {self.current_state}...")
            if not handler():
                print(f"Handler failed for state {self.current_state}")
                return False

            # Brief wait for state change
            time.sleep(0.5)  # Reduced from 2s to 0.5s

        print(f"Failed to reach library state after {max_attempts} attempts")
        return False
