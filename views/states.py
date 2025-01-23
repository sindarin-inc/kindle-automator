from enum import Enum, auto


class AppState(Enum):
    UNKNOWN = auto()
    NOTIFICATIONS = auto()
    HOME = auto()
    SIGN_IN = auto()
    LIBRARY = auto()
    LIBRARY_SIGN_IN = auto()
    READING = auto()


def get_state_from_view(view):
    """Convert view_inspector result to AppState"""
    # If view is already an AppState enum, return it directly
    if isinstance(view, AppState):
        return view

    # Otherwise map string view names to states
    state_mapping = {
        "notifications_permission": AppState.NOTIFICATIONS,
        "home": AppState.HOME,
        "sign_in": AppState.SIGN_IN,
        "library": AppState.LIBRARY,
        "library_sign_in": AppState.LIBRARY_SIGN_IN,
        "reading": AppState.READING,
        "unknown": AppState.UNKNOWN,
        None: AppState.UNKNOWN,
    }
    return state_mapping.get(str(view).lower(), AppState.UNKNOWN)
