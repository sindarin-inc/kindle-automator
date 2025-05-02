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

        # If no sindarin_email found, don't attempt to load a profile and continue
        if not sindarin_email:
            logger.debug("No sindarin_email provided in request, continuing without profile check")
            return f(*args, **kwargs)

        # Check if a server instance exists (it should always be available after app startup)
        from flask import current_app as app
        from flask import request

        if not hasattr(app, "config") or "server_instance" not in app.config:
            logger.error("Server instance not available in app.config")
            return jsonify({"error": "Server configuration error"}), 500

        server = app.config["server_instance"]

        # Check if this email exists in profiles_index first
        # If not, register it immediately to avoid profile creation issues
        profiles_index = server.profile_manager.profiles_index

        if sindarin_email not in profiles_index:
            # Create standardized AVD name for this email
            normalized_avd_name = server.profile_manager.get_avd_name_from_email(sindarin_email)
            logger.info(f"Registering {sindarin_email} with AVD {normalized_avd_name}")

            # Register this profile to ensure it's in profiles_index
            server.profile_manager.register_profile(sindarin_email, normalized_avd_name)

            # Verify it was added correctly
            if sindarin_email not in server.profile_manager.profiles_index:
                logger.error(f"Failed to register {sindarin_email} in profiles_index")
        else:
            logger.info(f"Email {sindarin_email} already registered")

        # Now check if this profile exists by looking for an AVD
        avd_name = server.profile_manager.get_avd_for_email(sindarin_email)

        # Check if AVD file path exists
        avd_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)

        # Check if the AVD is already running for this email - make sure we use the actual email, not a normalized version
        # Important: Always pass the original email to find_running_emulator_for_email, never a normalized version
        is_running, emulator_id, _ = server.profile_manager.find_running_emulator_for_email(sindarin_email)

        # Skip AVD existence check in development environment on macOS
        is_mac_dev = ENVIRONMENT.lower() == "dev" and platform.system() == "Darwin"

        # Check if this is the /auth endpoint - we should allow it to proceed even without an AVD
        is_auth_endpoint = request.path.endswith("/auth")

        if not avd_exists and not is_mac_dev and not is_auth_endpoint:
            # AVD doesn't exist - require the user to call /auth first to create it
            logger.warning(
                f"No AVD exists for email {sindarin_email}, user must authenticate first to create profile"
            )
            return {
                "error": "No AVD profile found for this email",
                "message": "You need to authenticate first using the /auth endpoint to create a profile",
                "requires_auth": True,
            }, 401
        elif not avd_exists and (is_mac_dev or is_auth_endpoint):
            if is_auth_endpoint:
                logger.info(f"Auth endpoint: bypassing AVD existence check for {sindarin_email}")
            else:
                logger.info(f"In macOS dev environment: bypassing AVD existence check for {sindarin_email}")
            # Try to create a mock AVD profile mapping for this email
            server.profile_manager.register_email_to_avd(sindarin_email, "Pixel_API_30")

        # First check if we need to start a dedicated Appium server for this email
        if sindarin_email not in server.appium_processes:
            logger.info(f"Starting dedicated Appium server for {sindarin_email}")

            # Check if we have a stored Appium port for this email
            stored_port = server.profile_manager.get_appium_port_for_email(sindarin_email)

            if stored_port:
                port = stored_port
                logger.info(f"Using stored Appium port {port} for {sindarin_email}")
            else:
                # Calculate a unique port based on email hash if not stored
                base_port = 4723
                port_range = 276  # 4999 - 4723
                email_hash = hash(sindarin_email) % port_range
                port = base_port + email_hash

                # Store this port in the profile for future use
                if hasattr(server.profile_manager, "register_profile"):
                    # Get the AVD name for this email
                    avd_name = server.profile_manager.get_avd_for_email(sindarin_email)
                    if avd_name:
                        # Get existing VNC instance if any
                        vnc_instance = server.profile_manager.get_vnc_instance_for_email(sindarin_email)
                        # Register the profile with the new port
                        server.profile_manager.register_profile(
                            email=sindarin_email,
                            avd_name=avd_name,
                            vnc_instance=vnc_instance,
                            appium_port=port,
                        )
                        logger.info(f"Stored Appium port {port} for {sindarin_email} in profile")

            # Start the Appium server on this port and check for success
            appium_started = server.start_appium(port=port, email=sindarin_email)
            if not appium_started:
                logger.error(f"Failed to start Appium server for {sindarin_email} on port {port}")
                return {
                    "error": f"Failed to start Appium server for {sindarin_email}",
                    "message": "Could not initialize Appium server",
                }, 500

            logger.info(f"Started Appium server for {sindarin_email} on port {port}")

        # Check if we already have a working automator for this email
        automator = server.automators.get(sindarin_email)
        if automator and hasattr(automator, "driver") and automator.driver:
            # Set as current email for backward compatibility
            # No longer setting current_email as it has been removed
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

        # We no longer have a concept of "current" profile
        # Always use the individual profile for the requested email

        # Only use force_new_emulator when explicitly requested with recreate=1
        force_new_emulator = request.args.get("recreate") == "1"

        # Check if the user's AVD is running
        is_running, emulator_id, found_avd = server.profile_manager.find_running_emulator_for_email(
            sindarin_email
        )

        # Get the AVD name for this user
        avd_name = server.profile_manager.get_avd_for_email(sindarin_email)

        # Check if the AVD exists (whether running or not)
        avd_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)

        # Special handling for auth endpoint
        if request.path.endswith("/auth"):
            if not is_running:
                if avd_exists:
                    # AVD exists but isn't running - we'll start it
                    logger.info(f"AVD {avd_name} for {sindarin_email} exists but is not running")
                    logger.info(f"Will start existing AVD for {sindarin_email}")
                    force_new_emulator = False
                else:
                    # AVD doesn't exist - create it
                    logger.info(f"No AVD exists for {sindarin_email} on auth endpoint")
                    logger.info(f"Will create a new AVD for {sindarin_email}")
                    force_new_emulator = True
        else:
            # For all other endpoints, if the user's AVD isn't running, we should fail
            if not is_running and not force_new_emulator:
                logger.error(f"User {sindarin_email}'s AVD ({avd_name}) is not running")
                if avd_exists:
                    message = "Your device exists but is not running. Please authenticate first."
                else:
                    message = "You don't have a device set up. Please authenticate first to create one."

                return {
                    "error": f"AVD for {sindarin_email} not running",
                    "message": message,
                    "requires_auth": True,
                }, 400

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
