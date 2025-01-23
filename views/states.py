from enum import Enum, auto


class AppState(Enum):
    UNKNOWN = auto()
    NOTIFICATIONS = auto()
    HOME = auto()
    SIGN_IN = auto()
    LIBRARY = auto()
    READING = auto()


def get_state_from_view(view):
    """Convert view_inspector result to AppState"""
    state_mapping = {
        "notifications_permission": AppState.NOTIFICATIONS,
        "home": AppState.HOME,
        "sign_in": AppState.SIGN_IN,
        "library": AppState.LIBRARY,
        "reading": AppState.READING,
        "unknown": AppState.UNKNOWN,
        None: AppState.UNKNOWN,
    }
    return state_mapping.get(view, AppState.UNKNOWN)
