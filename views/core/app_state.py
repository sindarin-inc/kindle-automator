from enum import Enum, auto


class AppState(Enum):
    """Enum representing the current state of the Kindle app.

    Each state represents a distinct UI state that requires specific handling
    for navigation and interaction.
    """

    UNKNOWN = auto()
    NOTIFICATION_PERMISSION = auto()  # Notification permission dialog is showing
    HOME = auto()  # Home tab is selected
    SIGN_IN = auto()  # Email sign in screen
    SIGN_IN_PASSWORD = auto()  # Password entry screen
    LIBRARY = auto()  # Library tab is selected
    LIBRARY_SIGN_IN = auto()  # Library view with sign in button
    READING = auto()  # Book reading view
    CAPTCHA = auto()  # Captcha verification screen
    APP_NOT_RESPONDING = auto()  # App not responding dialog is showing


class AppView(Enum):
    """Enum representing the current view in the Kindle app."""

    UNKNOWN = auto()
    NOTIFICATION_PERMISSION = auto()
    HOME = auto()
    SIGN_IN = auto()
    SIGN_IN_PASSWORD = auto()
    LIBRARY = auto()
    LIBRARY_SIGN_IN = auto()
    READING = auto()
    CAPTCHA = auto()  # Captcha verification screen
    APP_NOT_RESPONDING = auto()  # App not responding dialog is showing
