import time
from views.states import AppState


class StateTransitions:
    def __init__(
        self, view_inspector, auth_handler, permissions_handler, library_handler
    ):
        print("Initializing State Transitions...")
        self.view_inspector = view_inspector
        self.auth_handler = auth_handler
        self.permissions_handler = permissions_handler
        self.library_handler = library_handler

    def handle_unknown(self):
        """Handle unknown state by ensuring app is in foreground and rechecking"""
        print("Handling UNKNOWN state - bringing app to foreground...")
        if not self.view_inspector.ensure_app_foreground():
            print("Failed to bring app to foreground")
            return False
        time.sleep(0.5)  # Reduced from 2s to 0.5s
        return True

    def handle_notifications(self):
        """Handle notifications permission dialog"""
        print("Handling NOTIFICATIONS state - accepting permission...")
        if not self.permissions_handler.handle_notifications_permission():
            print("Failed to handle notification permission")
            return False
        time.sleep(0.5)  # Reduced from 2s to 0.5s
        return True

    def handle_home(self):
        """Handle home screen by navigating to library"""
        print("Handling HOME state - navigating to library...")
        return self.library_handler.navigate_to_library()

    def handle_sign_in(self):
        """Handle sign in screen"""
        print("Handling SIGN_IN state - attempting authentication...")
        return self.auth_handler.sign_in()

    def handle_library(self):
        """Already in library, nothing to do"""
        print("Handling LIBRARY state - already at destination")
        return True

    def handle_reading(self):
        """Handle reading view by navigating back to library"""
        print("Handling READING state - navigating back to library...")
        return self.library_handler.navigate_to_library()

    def get_handler_for_state(self, state):
        """Get the appropriate handler for a given state"""
        handlers = {
            AppState.UNKNOWN: self.handle_unknown,
            AppState.NOTIFICATIONS: self.handle_notifications,
            AppState.HOME: self.handle_home,
            AppState.SIGN_IN: self.handle_sign_in,
            AppState.LIBRARY: self.handle_library,
            AppState.READING: self.handle_reading,
        }
        handler = handlers.get(state)
        if handler:
            print(f"Found handler for state {state}: {handler.__name__}")
        else:
            print(f"No handler found for state {state}")
        return handler
