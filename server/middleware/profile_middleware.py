import logging
import os
import platform
from functools import wraps

import flask
from flask import Response, jsonify, request

from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)

# Environment variable access (to match the original server.py behavior)
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")


def ensure_user_profile_loaded(f):
    @wraps(f)
    def middleware(*args, **kwargs):
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
        from flask import current_app as app

        if not hasattr(app, "config") or "server_instance" not in app.config:
            logger.error("Server instance not available in app.config")
            return jsonify({"error": "Server configuration error"}), 500

        server = app.config["server_instance"]

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

        # Get our currently active profile (before switching)
        current_profile = server.profile_manager.get_current_profile()
        current_email = current_profile.get("email") if current_profile else None

        # If we're switching to a different email than what's in current_profile.json,
        # then force a new emulator to ensure we get the correct profile
        force_new_emulator = current_email is not None and current_email != sindarin_email

        logger.info(
            f"Switching to profile for email: {sindarin_email} (forcing new emulator: {force_new_emulator})"
        )
        success, message = server.switch_profile(sindarin_email, force_new_emulator=force_new_emulator)

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
