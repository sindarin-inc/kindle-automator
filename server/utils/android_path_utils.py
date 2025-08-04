"""Utility functions for Android SDK and AVD path determination."""

import os
import platform


def get_android_home() -> str:
    """
    Get the Android SDK home directory based on environment.

    Returns:
        str: Path to Android SDK
    """
    if os.environ.get("ANDROID_HOME"):
        return os.environ.get("ANDROID_HOME")
    elif platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Android/sdk")
    else:
        return "/opt/android-sdk"


def get_avd_dir() -> str:
    """
    Get the AVD directory based on environment.

    Returns:
        str: Path to AVD directory
    """
    android_home = get_android_home()

    # Mac development environment
    if platform.system() == "Darwin" and os.environ.get("FLASK_ENV") == "development":
        return os.path.expanduser("~/.android/avd")
    else:
        # Production/staging environment
        return os.path.join(android_home, "avd")
