import logging
import os
import platform
import subprocess
import time
import traceback
from functools import wraps

import flask
from flask import Response, jsonify, request

from views.core.app_state import AppState

logger = logging.getLogger(__name__)


def get_sindarin_email(default_email=None):
    """
    Extract sindarin_email from request (query params, JSON body, or form data).

    Args:
        default_email: Default email to return if not found in request

    Returns:
        The extracted email or the default email if not found
    """
    sindarin_email = None

    # Check in URL parameters
    if "sindarin_email" in request.args:
        sindarin_email = request.args.get("sindarin_email")
        logger.debug(f"Found sindarin_email in URL parameters: {sindarin_email}")

    # Check in JSON body if present
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        if "sindarin_email" in data:
            sindarin_email = data.get("sindarin_email")
            logger.debug(f"Found sindarin_email in JSON body: {sindarin_email}")

    # Check in form data
    elif "sindarin_email" in request.form:
        sindarin_email = request.form.get("sindarin_email")
        logger.debug(f"Found sindarin_email in form data: {sindarin_email}")

    # Return either found email or default
    return sindarin_email or default_email


def ensure_user_profile_loaded(f):
    """Middleware to check and load user profile based on sindarin_email."""

    @wraps(f)
    def middleware(*args, **kwargs):
        from flask import current_app

        # Get sindarin_email from request data using our utility function
        sindarin_email = get_sindarin_email()

        # If sindarin_email was found, log it at INFO level
        if sindarin_email:
            logger.info(f"Found sindarin_email in request: {sindarin_email}")

        # If no sindarin_email found, don't attempt to load a profile and continue
        if not sindarin_email:
            logger.debug("No sindarin_email provided in request, continuing without profile check")
            return f(*args, **kwargs)

        # Check if a server instance exists (it should always be available after app startup)
        if not hasattr(current_app, "config") or "server_instance" not in current_app.config:
            logger.error("Server instance not available in current_app.config")
            return jsonify({"error": "Server configuration error"}), 500

        server = current_app.config["server_instance"]

        # Get environment information for development checks
        ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")

        # Check if this profile exists by looking for an AVD
        # This doesn't create the AVD - just checks if it's registered or exists
        avd_name = server.profile_manager.get_avd_for_email(sindarin_email)

        # Check if AVD file path exists
        avd_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)

        # Check if the AVD is already running for this email
        is_running, emulator_id, _ = server.profile_manager.find_running_emulator_for_email(sindarin_email)

        # Skip AVD existence check in development environment on macOS
        is_mac_dev = ENVIRONMENT.lower() == "dev" and platform.system() == "Darwin"

        if not avd_exists and not is_mac_dev:
            # AVD doesn't exist - require the user to call /auth first to create it
            logger.warning(
                f"No AVD exists for email {sindarin_email}, user must authenticate first to create profile"
            )
            return {
                "error": "No AVD profile found for this email",
                "message": "You need to authenticate first using the /auth endpoint to create a profile",
                "requires_auth": True,
            }, 401
        elif not avd_exists and is_mac_dev:
            logger.info(f"In macOS dev environment: bypassing AVD existence check for {sindarin_email}")
            # Try to create a mock AVD profile mapping for this email
            server.profile_manager.register_email_to_avd(sindarin_email, "Pixel_API_30")

        # Check if we already have a working automator for this email
        automator = server.automators.get(sindarin_email)
        if automator and hasattr(automator, "driver") and automator.driver:
            # Set as current email for backward compatibility
            server.current_email = sindarin_email
            logger.info(f"Already have automator for email: {sindarin_email}")

            # If the emulator is running for this profile, we're good to go
            if is_running:
                logger.debug(f"Emulator already running for {sindarin_email}")
                result = f(*args, **kwargs)
                # Handle Flask Response objects appropriately
                if isinstance(result, (flask.Response, Response)):
                    return result
                return result

        # Need to switch to this profile - server.switch_profile handles both:
        # 1. Switching to an existing profile
        # 2. Loading a profile with a running emulator
        logger.info(f"Switching to profile for email: {sindarin_email}")
        success, message = server.switch_profile(sindarin_email)

        if not success:
            logger.error(f"Failed to switch to profile for {sindarin_email}: {message}")
            return {
                "error": f"Failed to load profile: {message}",
                "message": "There was an error loading this user profile",
            }, 500

        logger.info(f"Successfully switched to profile for {sindarin_email}")

        # Get the automator for this email
        automator = server.automators.get(sindarin_email)

        # Profile switch was successful, initialize automator if needed
        if not automator:
            logger.info(f"Initializing automator for {sindarin_email}")
            automator = server.initialize_automator(sindarin_email)

            if not automator:
                logger.error(f"Failed to initialize automator for {sindarin_email}")
                return {
                    "error": f"Failed to initialize automator for {sindarin_email}",
                    "message": "Could not create automator instance",
                }, 500

            # Try initializing the driver if needed
            if not automator.driver:
                if not automator.initialize_driver():
                    logger.error(f"Failed to initialize driver for {sindarin_email}")
                    return {
                        "error": f"Failed to initialize driver for {sindarin_email}",
                        "message": "The device could not be connected",
                    }, 500

        # Continue with the original endpoint handler
        result = f(*args, **kwargs)
        # Handle Flask Response objects appropriately
        if isinstance(result, (flask.Response, Response)):
            return result
        return result

    return middleware


def ensure_automator_healthy(f):
    """Decorator to ensure automator is initialized and healthy before each operation.
    Works with the multi-emulator approach by getting the sindarin_email from the request.
    """
    from flask import current_app

    @wraps(f)
    def wrapper(*args, **kwargs):
        max_retries = 3  # Allow more retries for UiAutomator2 crashes

        # Get server instance from app config
        if not hasattr(current_app, "config") or "server_instance" not in current_app.config:
            logger.error("Server instance not available in current_app.config")
            return {"error": "Server configuration error"}, 500

        server = current_app.config["server_instance"]

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email(default_email=server.current_email)

        # If we still don't have an email after checking current_email, try the current profile
        if not sindarin_email:
            # Try to get from current profile
            current_profile = server.profile_manager.get_current_profile()
            if current_profile:
                sindarin_email = current_profile.get("email")
                logger.debug(f"Using email from current profile: {sindarin_email}")

        if not sindarin_email:
            logger.error("No sindarin_email found in request or current state")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Ensure this is set as the current email for backward compatibility
        server.current_email = sindarin_email

        for attempt in range(max_retries):
            try:
                # Get the automator for this email
                automator = server.automators.get(sindarin_email)

                # Initialize automator if needed
                if not automator:
                    logger.info(f"No automator found for {sindarin_email}. Initializing automatically...")
                    automator = server.initialize_automator(sindarin_email)
                    if not automator:
                        logger.error(f"Failed to initialize automator for {sindarin_email}")
                        return {"error": f"Failed to initialize automator for {sindarin_email}"}, 500

                    if not automator.initialize_driver():
                        logger.error(f"Failed to initialize driver for {sindarin_email}")
                        return {
                            "error": f"Failed to initialize driver for {sindarin_email}. Call /initialize first."
                        }, 500

                # Ensure driver is running
                if not automator.ensure_driver_running():
                    logger.error(f"Failed to ensure driver is running for {sindarin_email}")
                    return {"error": f"Failed to ensure driver is running for {sindarin_email}"}, 500

                # Execute the function
                result = f(*args, **kwargs)

                # Special handling for Flask Response objects to prevent JSON serialization errors
                if isinstance(result, (flask.Response, Response)):
                    return result

                return result

            except Exception as e:
                # Check if it's the UiAutomator2 server crash error or other common crash patterns
                error_message = str(e)
                is_uiautomator_crash = any(
                    [
                        "cannot be proxied to UiAutomator2 server because the instrumentation process is not running"
                        in error_message,
                        "instrumentation process is not running" in error_message,
                        "Failed to establish a new connection" in error_message,
                        "Connection refused" in error_message,
                        "Connection reset by peer" in error_message,
                    ]
                )

                if is_uiautomator_crash and attempt < max_retries - 1:
                    logger.warning(
                        f"UiAutomator2 server crashed on attempt {attempt + 1}/{max_retries}. Restarting driver..."
                    )
                    logger.warning(f"Crash error: {error_message}")

                    # Kill any leftover UiAutomator2 processes directly via ADB
                    try:
                        automator = server.automators.get(sindarin_email)
                        if automator and automator.device_id:
                            device_id = automator.device_id
                            logger.info(f"Forcibly killing UiAutomator2 processes on device {device_id}")
                            subprocess.run(
                                [f"adb -s {device_id} shell pkill -f uiautomator"],
                                shell=True,
                                check=False,
                                timeout=5,
                            )
                            time.sleep(2)  # Give it time to fully terminate
                    except Exception as kill_e:
                        logger.warning(f"Error while killing UiAutomator2 processes: {kill_e}")

                    # Force a complete driver restart for this email
                    automator = server.automators.get(sindarin_email)
                    if automator:
                        logger.info(f"Cleaning up automator resources for {sindarin_email}")
                        automator.cleanup()
                        server.automators[sindarin_email] = None

                    # Reset Appium server state as well
                    try:
                        logger.info("Resetting Appium server state")
                        subprocess.run(["pkill -f 'appium|node'"], shell=True, check=False, timeout=5)
                        time.sleep(2)  # Wait for processes to terminate

                        logger.info("Restarting Appium server")
                        if not server.start_appium():
                            logger.error("Failed to restart Appium server")
                    except Exception as appium_e:
                        logger.warning(f"Error while resetting Appium: {appium_e}")

                    # Try to switch back to the profile
                    logger.info(f"Attempting to switch back to profile for email: {sindarin_email}")
                    success, message = server.switch_profile(sindarin_email)
                    if not success:
                        logger.error(f"Failed to switch back to profile: {message}")
                        return {"error": f"Failed to switch back to profile: {message}"}, 500

                    logger.info(f"Initializing automator after crash recovery for {sindarin_email}")
                    automator = server.initialize_automator(sindarin_email)
                    # Clear current book since we're restarting the driver
                    server.clear_current_book(sindarin_email)

                    if automator and automator.initialize_driver():
                        logger.info(
                            "Successfully restarted driver after UiAutomator2 crash, retrying operation..."
                        )
                        continue  # Retry the operation with the next loop iteration
                    else:
                        logger.error("Failed to restart driver after UiAutomator2 crash")

                # For non-UiAutomator2 crashes or if restart failed, log and return error
                logger.error(f"Error in operation (attempt {attempt + 1}/{max_retries}): {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

                # On the last attempt, return the error
                if attempt == max_retries - 1:
                    return {"error": str(e)}, 500

    return wrapper
