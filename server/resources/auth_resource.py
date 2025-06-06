"""Auth resource for authentication management."""

import logging
import platform
import subprocess
import time

from appium.webdriver.common.appiumby import AppiumBy
from flask import request
from flask_restful import Resource

from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import (
    get_formatted_vnc_url,
    get_sindarin_email,
    get_vnc_and_websocket_urls,
)
from server.utils.vnc_instance_manager import VNCInstanceManager
from server.utils.websocket_proxy_manager import WebSocketProxyManager
from views.core.app_state import AppState
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class AuthResource(Resource):
    """Resource for authentication operations."""

    def __init__(self, server_instance=None):
        """Initialize the resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    def _handle_recreate(self, sindarin_email, recreate_user=True, recreate_seed=False):
        """Handle deletion of AVDs when recreate is requested"""
        actions = []
        if recreate_user:
            actions.append("user AVD")
        if recreate_seed:
            actions.append("seed clone")

        logger.info(f"Recreate requested for {sindarin_email}, will recreate: {', '.join(actions)}")

        profile_manager = AVDProfileManager.get_instance()

        # Clean up the automator before recreating AVDs
        if sindarin_email in self.server.automators:
            logger.info(f"Cleaning up existing automator for {sindarin_email}")
            automator = self.server.automators[sindarin_email]
            if automator:
                automator.cleanup()
            del self.server.automators[sindarin_email]

        # Use the new recreate_profile_avd method with parameters
        success, message = profile_manager.recreate_profile_avd(sindarin_email, recreate_user, recreate_seed)
        if not success:
            logger.error(f"Failed to recreate profile AVD: {message}")
            return False, message

        return True, f"Successfully recreated: {', '.join(actions)}"

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response
    def _auth(self):
        """Set up a profile for manual authentication via VNC or WebSockets"""
        # Create a unified params dict that combines query params and JSON body
        params = {}
        for key, value in request.args.items():
            params[key] = value

        # Then try to add JSON parameters if available (they override query params)
        if request.is_json:
            try:
                json_data = request.get_json() or {}
                # Update params with JSON data (overriding any query params with the same name)
                for key, value in json_data.items():
                    params[key] = value
            except:
                # In case of JSON parsing error, just continue with query params
                logger.warning("Failed to parse JSON data in request")

        # Get sindarin_email from unified params
        sindarin_email = params.get("sindarin_email")

        # Fall back to form data if needed
        if not sindarin_email and "sindarin_email" in request.form:
            sindarin_email = request.form.get("sindarin_email")

        # Sindarin email is required for profile identification
        if not sindarin_email:
            logger.error("No sindarin_email provided for profile identification")
            return {"error": "sindarin_email is required for profile identification"}, 400

        # Process boolean parameters in a unified way
        # For query params, "1", "true", "yes" (case-insensitive) are considered true
        # For JSON data, use the boolean or convert string values
        def get_bool_param(param_name, default=False):
            if param_name not in params:
                return default

            value = params[param_name]
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ("1", "true", "yes")
            elif isinstance(value, int):
                return value == 1
            return default

        # Get boolean parameters
        recreate = get_bool_param("recreate", False)
        restart_vnc = get_bool_param("restart_vnc", False)
        use_websockets = get_bool_param("websockets", False)

        if restart_vnc:
            logger.info(f"Restart VNC requested for {sindarin_email}")

        if use_websockets:
            logger.info(f"WebSockets requested for {sindarin_email} (will use rfbproxy)")

        # Log authentication attempt details
        logger.info(f"Setting up profile: {sindarin_email} for manual VNC authentication")

        # Debug logging for cross-user interference
        logger.info(f"CROSS_USER_DEBUG: Auth endpoint called for email={sindarin_email}")
        logger.info(f"CROSS_USER_DEBUG: Current automators in server: {list(self.server.automators.keys())}")

        # Get the automator (should have been created by the decorator)
        automator = self.server.automators.get(sindarin_email)
        logger.info(
            f"CROSS_USER_DEBUG: Retrieved automator={id(automator) if automator else 'None'} for email={sindarin_email}"
        )

        # Use the prepare_for_authentication method - always using VNC
        # Make sure the driver has access to the automator for state transitions
        # This fixes the "Could not access automator from driver session" error
        if automator and automator.driver and not hasattr(automator.driver, "automator"):
            logger.info("Setting automator on driver object for state transitions")
            automator.driver.automator = automator
            logger.info(
                f"CROSS_USER_DEBUG: Set driver.automator reference - driver={id(automator.driver)}, automator={id(automator)}"
            )

        # Ensure the automator exists and driver is healthy and all components are initialized
        if not automator:
            logger.error("Failed to get automator for request")
            return {"error": "Failed to initialize automator"}, 500

        if automator.driver:
            logger.info(
                f"CROSS_USER_DEBUG: Before ensure_driver_running - driver={id(automator.driver)}, automator={id(automator)}, device_id={getattr(automator, 'device_id', 'unknown')}"
            )

        if not automator.ensure_driver_running():
            logger.error("Failed to ensure driver is running, cannot proceed with authentication")
            return {"error": "Failed to initialize automator driver"}, 500

        # This is the critical method that ensures we navigate to AUTH or LIBRARY
        logger.info("Calling prepare_for_authentication to navigate to sign-in screen or library")
        logger.info(
            f"CROSS_USER_DEBUG: About to call prepare_for_authentication - automator={id(automator)}, state_machine={id(automator.state_machine)}, auth_handler={id(automator.state_machine.auth_handler)}"
        )
        auth_status = automator.state_machine.auth_handler.prepare_for_authentication()
        logger.info(f"CROSS_USER_DEBUG: prepare_for_authentication returned for email={sindarin_email}")

        logger.info(f"Authentication preparation status: {auth_status}")

        # Check for fatal errors that would prevent continuing
        if auth_status.get("fatal_error", False):
            error_msg = auth_status.get("error", "Unknown fatal error in authentication preparation")
            logger.error(f"Fatal error in authentication preparation: {error_msg}")
            return {"success": False, "error": error_msg}, 500

        # Handle already authenticated cases (LIBRARY or HOME)
        if auth_status.get("already_authenticated", False):
            # If we're in HOME state, try to switch to LIBRARY
            if auth_status.get("state") == "HOME":
                logger.info("Already logged in but in HOME state, switching to LIBRARY")

                # Try to click the LIBRARY tab
                try:
                    library_tab = automator.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"
                    )
                    library_tab.click()
                    logger.info("Clicked on LIBRARY tab")
                    time.sleep(1)  # Wait for tab transition

                    # Update state after clicking
                    automator.state_machine.update_current_state()
                    updated_state = automator.state_machine.current_state

                    if updated_state == AppState.LIBRARY:
                        logger.info("Successfully switched to LIBRARY state")
                        return {
                            "success": True,
                            "message": "Switched to library view",
                            "authorized_kindle_account": True,
                        }, 200
                except Exception as e:
                    logger.error(f"Error clicking on LIBRARY tab: {e}")
                    # Continue with normal authentication process
            else:
                # We're already in LIBRARY state
                return {
                    "success": True,
                    "message": "Already authenticated",
                    "authorized_kindle_account": True,
                }, 200

        # Handle LIBRARY_SIGN_IN state - check if we need to click on the sign-in button
        if auth_status.get("state") == "LIBRARY_SIGN_IN":
            logger.info("Found empty library with sign-in button, clicking it to proceed with authentication")
            try:
                # Use the library handler to click the sign-in button
                result = automator.state_machine.library_handler.handle_library_sign_in()
                if result:
                    logger.info("Successfully clicked sign-in button, now on authentication screen")

                    # Update the state after clicking
                    automator.state_machine.update_current_state()
                    current_state = automator.state_machine.current_state
                    state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

                    logger.info(f"Current state after clicking sign-in button: {state_name}")

                    # Update the auth status with the new state
                    auth_status["state"] = state_name
                    auth_status["requires_manual_login"] = True
                else:
                    logger.error("Failed to click sign-in button")
            except Exception as e:
                logger.error(f"Error handling LIBRARY_SIGN_IN state: {e}")
                # Continue with normal authentication process

        # Always use manual login via VNC (no automation of Amazon credentials)
        # Before getting VNC URL, ensure that VNC server is running

        # Handle restart_vnc parameter if set - force kill existing VNC process
        if restart_vnc:
            # Get the display number for this profile
            logger.info(f"Explicitly restarting VNC server for {sindarin_email}")

            # Skip on macOS
            if platform.system() != "Darwin":
                try:
                    # Get VNC instance manager to find the display
                    vnc_manager = VNCInstanceManager.get_instance()
                    display_num_to_restart = None
                    vnc_port_to_restart = None

                    for instance in vnc_manager.instances:
                        if instance.get("assigned_profile") == sindarin_email:
                            display_num_to_restart = instance.get("display")
                            vnc_port_to_restart = instance.get("vnc_port")
                            break

                    if display_num_to_restart:
                        logger.info(
                            f"Found display :{display_num_to_restart} for {sindarin_email}, killing existing VNC process"
                        )
                        # Kill any existing VNC process for this display
                        subprocess.run(["pkill", "-f", f"x11vnc.*:{display_num_to_restart}"], check=False)
                        # Also force kill by port
                        if vnc_port_to_restart:
                            subprocess.run(
                                ["pkill", "-f", f"x11vnc.*rfbport {vnc_port_to_restart}"], check=False
                            )

                        logger.info(f"Forced VNC restart for display :{display_num_to_restart}")
                    else:
                        logger.warning(f"Could not find display number for {sindarin_email}")
                except Exception as e:
                    logger.error(f"Error restarting VNC server: {e}")

        # Get the formatted VNC URL with the profile email
        # This will also start the VNC server if it's not running
        # If websockets are requested, also get the websocket URL
        if use_websockets:
            # Get both VNC and WebSocket URLs
            vnc_url, ws_url = get_vnc_and_websocket_urls(sindarin_email)
            formatted_vnc_url = vnc_url  # Keep using vnc_url for backward compatibility
        else:
            # Just get the regular VNC URL
            formatted_vnc_url = get_formatted_vnc_url(sindarin_email)
            ws_url = None

        # Prepare manual auth response with details from auth_status
        current_state = automator.state_machine.current_state
        state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

        # Start with base response information
        response_data = {
            "success": True,
            "manual_login_required": auth_status.get("requires_manual_login", True),
            "message": auth_status.get("message", "Ready for manual authentication via VNC"),
            "state": auth_status.get("state", state_name),
            "vnc_url": formatted_vnc_url,  # Include the VNC URL in the response
            "authorized_kindle_account": auth_status.get(
                "already_authenticated", False
            ),  # Indicates if user is signed in
        }

        # Pass through any additional info from auth_status
        if "error" in auth_status:
            response_data["error_info"] = auth_status["error"]

        # If we have custom messages, include them
        if "message" in auth_status:
            response_data["message"] = auth_status["message"]

        # Add WebSocket URL to the response if available
        if use_websockets and ws_url:
            response_data["websocket_url"] = ws_url

        # Log the final response in detail
        logger.info(f"Returning auth response: {response_data}")

        return response_data, 200

    def get(self):
        """Get the auth status"""
        # First check if recreate is requested BEFORE profile loading
        params = {}
        for key, value in request.args.items():
            params[key] = value

        sindarin_email = params.get("sindarin_email")
        recreate_user = params.get("recreate") == 1 or params.get("recreate") == "1"
        recreate_seed = params.get("recreate_seed") == 1 or params.get("recreate_seed") == "1"

        if sindarin_email and (recreate_user or recreate_seed):
            success, message = self._handle_recreate(sindarin_email, recreate_user, recreate_seed)
            if not success:
                return {"error": message}, 500

        # Now proceed with normal auth flow
        return self._auth()

    def post(self):
        """Set up a profile for manual authentication via VNC"""
        # First check if recreate is requested BEFORE profile loading
        params = {}
        if request.is_json:
            params = request.get_json() or {}

        sindarin_email = params.get("sindarin_email") or params.get("email")
        recreate_user = params.get("recreate") == 1 or params.get("recreate") == "1"
        recreate_seed = params.get("recreate_seed") == 1 or params.get("recreate_seed") == "1"

        if sindarin_email and (recreate_user or recreate_seed):
            success, message = self._handle_recreate(sindarin_email, recreate_user, recreate_seed)
            if not success:
                return {"error": message}, 500

        # Now proceed with normal auth flow
        return self._auth()
