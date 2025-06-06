import logging
import os
import platform
import subprocess
from functools import wraps

import flask
from flask import Response, jsonify, request

from server.utils.request_utils import get_sindarin_email
from server.utils.staff_token_manager import validate_token

logger = logging.getLogger(__name__)

# Environment variable access (to match the original server.py behavior)
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")


def find_device_id_by_android_id(email):
    """Try to find a device ID using Android ID for macOS environments."""
    try:
        # Get Android ID from adb devices (simplified approach)
        devices_output = subprocess.check_output(["adb", "devices"], text=True)
        emulator_ids = [
            line.split("\t")[0]
            for line in devices_output.splitlines()
            if "\tdevice" in line and line.startswith("emulator")
        ]

        if emulator_ids:
            # Just return the first device ID if we find any
            return emulator_ids[0]
        return None
    except Exception as e:
        logger.error(f"Error finding device by Android ID: {e}")
        return None


def ensure_user_profile_loaded(f):
    @wraps(f)
    def middleware(*args, **kwargs):
        # Get sindarin_email from request data using our utility function
        sindarin_email = get_sindarin_email()

        # Extract user_email from request parameters if present
        user_email = None
        if "user_email" in request.args:
            user_email = request.args.get("user_email")
        elif request.is_json and "user_email" in (request.get_json(silent=True) or {}):
            user_email = request.get_json(silent=True).get("user_email")

        # Only require staff authentication when user_email is present
        if user_email:
            # Check if staff token exists
            token = request.cookies.get("staff_token")
            if not token:
                logger.warning("Staff token is required but not found in cookies")
                return {
                    "error": "Staff authentication required",
                    "message": "You must authenticate as staff to impersonate users",
                }, 403

            # Validate the token
            if not validate_token(token):
                logger.warning(f"Invalid staff token: {token}")
                return {
                    "error": "Invalid staff token",
                    "message": "Your staff token is invalid or has been revoked",
                }, 403

            logger.info(f"Staff authentication successful, allowing impersonation of {user_email}")

            # Set sindarin_email to user_email for impersonation by adding it to the request args
            # The get_sindarin_email function checks request.args for "sindarin_email" or "email"
            if request.args and hasattr(request.args, "_mutable") and request.args._mutable:
                # Mutable args - just add directly
                request.args["sindarin_email"] = user_email
            else:
                # Flask's ImmutableMultiDict - need to make a mutable copy and replace
                from werkzeug.datastructures import ImmutableMultiDict

                args_copy = request.args.copy()
                args_copy["sindarin_email"] = user_email
                # This is a bit of a hack but necessary for Flask's immutable request objects
                request.args = ImmutableMultiDict(args_copy)

            # Now get the updated sindarin_email from the request
            sindarin_email = user_email
            logger.info(f"Setting sindarin_email to {user_email} for staff impersonation")

        # If no sindarin_email found, don't attempt to load a profile and continue
        if not sindarin_email:
            logger.debug("No sindarin_email provided in request, continuing without profile check")
            return f(*args, **kwargs)

        # Check if a server instance exists (it should always be available after app startup)
        from flask import current_app as app

        # Use the already imported request object from the global scope

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

        # Now check if this profile exists by looking for an AVD
        avd_name = server.profile_manager.get_avd_for_email(sindarin_email)

        # Skip cold storage check on macOS development environment
        is_mac_dev = ENVIRONMENT.lower() == "dev" and platform.system() == "Darwin"

        if not is_mac_dev:
            # Check if profile is in cold storage
            cold_storage_date = server.profile_manager.get_user_field(sindarin_email, "cold_storage_date")
            if cold_storage_date:
                logger.info(f"Profile {sindarin_email} is in cold storage since {cold_storage_date}")

                # Restore from cold storage
                from server.utils.cold_storage_manager import ColdStorageManager

                cold_storage_manager = ColdStorageManager.get_instance()

                logger.info(f"Restoring profile {sindarin_email} from cold storage...")
                if cold_storage_manager.restore_avd_from_cold_storage(sindarin_email):
                    # Clear the cold storage date
                    server.profile_manager.set_user_field(sindarin_email, "cold_storage_date", None)
                    logger.info(f"Successfully restored profile {sindarin_email} from cold storage")
                else:
                    logger.error(f"Failed to restore profile {sindarin_email} from cold storage")
                    return {
                        "error": "Failed to restore profile from cold storage",
                        "message": f"Could not restore AVD for {sindarin_email} from cold storage",
                    }, 500
        else:
            logger.info(f"Skipping cold storage check on macOS dev environment for {sindarin_email}")

        # Check if AVD file path exists
        avd_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.avd")
        avd_ini_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.ini")
        # AVD is only valid if both the directory and ini file exist
        avd_exists = os.path.exists(avd_path) and os.path.exists(avd_ini_path)

        # If AVD doesn't exist and this is the /auth endpoint, try to prepare seed clone
        if not avd_exists and request.path.endswith("/auth"):
            logger.info(f"AVD doesn't exist for {sindarin_email}, preparing seed clone for fast creation")
            server.ensure_seed_clone_prepared()

        # Check if the AVD is already running for this email - make sure we use the actual email, not a normalized version
        # Important: Always pass the original email to find_running_emulator_for_email, never a normalized version
        is_running, emulator_id, _ = server.profile_manager.find_running_emulator_for_email(sindarin_email)

        # Check if this is the /auth endpoint - we should allow it to proceed even without an AVD
        is_auth_endpoint = request.path.endswith("/auth")

        # For macOS dev, check if any device is available to reuse
        mac_device_id = None
        if is_mac_dev:
            mac_device_id = find_device_id_by_android_id(sindarin_email)

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
                if mac_device_id:
                    logger.info(
                        f"In macOS dev environment: found device {mac_device_id} to reuse for {sindarin_email}"
                    )
                else:
                    logger.info(
                        f"In macOS dev environment: bypassing AVD existence check for {sindarin_email}"
                    )
            # Try to create a mock AVD profile mapping for this email
            server.profile_manager.register_email_to_avd(sindarin_email, "Pixel_API_30")

        # First check if we need to start a dedicated Appium server for this email
        from server.utils.appium_driver import AppiumDriver
        from server.utils.vnc_instance_manager import VNCInstanceManager

        appium_driver = AppiumDriver.get_instance()
        vnc_manager = VNCInstanceManager.get_instance()

        # Ensure VNC instance exists for this profile (even in macOS dev where we don't use VNC)
        # This is needed for port allocation and tracking
        vnc_instance = vnc_manager.get_instance_for_profile(sindarin_email)
        if not vnc_instance:
            logger.info(f"Creating VNC instance for {sindarin_email} for port tracking")
            vnc_instance = vnc_manager.assign_instance_to_profile(sindarin_email)
            if not vnc_instance:
                logger.error(f"Failed to assign VNC instance for {sindarin_email}")
                return {
                    "error": f"Failed to create instance tracking for {sindarin_email}",
                    "message": "Could not initialize instance tracking",
                }, 500

        # Check if we already have a working automator for this email
        automator = server.automators.get(sindarin_email)
        if automator and hasattr(automator, "driver") and automator.driver:
            logger.info(f"Already have automator for email: {sindarin_email}")

            # Special case for macOS dev environment
            is_mac_dev = ENVIRONMENT.lower() == "dev" and platform.system() == "Darwin"

            # If the emulator is running for this profile or we're in macOS dev, we're good to go
            if is_running or (is_mac_dev and find_device_id_by_android_id(sindarin_email)):
                if is_running:
                    logger.debug(f"Emulator already running for {sindarin_email}")
                else:
                    logger.debug(f"In macOS dev mode with available device for {sindarin_email}")
                result = f(*args, **kwargs)
                # Handle Flask Response objects appropriately
                if isinstance(result, (flask.Response, Response)):
                    return result
                return result

        # Need to switch to this profile - server.switch_profile handles both:
        # 1. Switching to an existing profile
        # 2. Loading a profile with a running emulator

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
        avd_ini_path = os.path.join(server.profile_manager.avd_dir, f"{avd_name}.ini")
        # AVD is only valid if both the directory and ini file exist
        avd_exists = os.path.exists(avd_path) and os.path.exists(avd_ini_path)

        # Check if we're on macOS dev environment
        is_mac_dev = ENVIRONMENT.lower() == "dev" and platform.system() == "Darwin"

        if not is_running:
            if avd_exists:
                # AVD exists but isn't running - we'll start it
                logger.info(f"AVD {avd_name} for {sindarin_email} exists but is not running")
                force_new_emulator = False
            elif is_mac_dev and find_device_id_by_android_id(sindarin_email):
                # Special case for macOS: If a device is available by Android ID, use it
                force_new_emulator = False
            else:
                # AVD doesn't exist - create it
                logger.info(f"Will create a new AVD for {sindarin_email}")
                force_new_emulator = True

        success, message = server.switch_profile(sindarin_email, force_new_emulator=force_new_emulator)

        if not success:
            logger.error(f"Failed to switch to profile for {sindarin_email}: {message}")
            return {
                "error": f"Failed to load profile: {message}",
                "message": "There was an error loading this user profile",
            }, 500

        # Get the automator for this email
        automator = server.automators.get(sindarin_email)

        # Profile switch was successful, initialize automator if needed
        if not automator:
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

        # Make sure the Kindle app is running before continuing
        # This is crucial for all endpoints that interact with the app
        if (
            automator
            and hasattr(automator, "state_machine")
            and hasattr(automator.state_machine, "view_inspector")
        ):
            try:
                automator.state_machine.view_inspector.ensure_app_foreground()
            except Exception as e:
                logger.warning(f"Error ensuring app is in foreground: {e}")
                # Continue anyway, the endpoint will handle errors

        # Continue with the original endpoint handler
        result = f(*args, **kwargs)
        # Handle Flask Response objects appropriately
        if isinstance(result, (flask.Response, Response)):
            return result
        return result

    return middleware
