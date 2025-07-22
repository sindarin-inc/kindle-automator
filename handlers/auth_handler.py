import logging
import os
import subprocess
import time
from enum import Enum

from appium.webdriver.common.appiumby import AppiumBy
from PIL import Image
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from server.logging_config import store_page_source
from server.utils.request_utils import get_formatted_vnc_url
from views.auth.interaction_strategies import (
    AUTH_ERROR_STRATEGIES,
    CAPTCHA_CONTINUE_BUTTON,
    CAPTCHA_INPUT_FIELD,
    CONTINUE_BUTTON_STRATEGIES,
    EMAIL_FIELD_STRATEGIES,
    PASSWORD_FIELD_STRATEGIES,
    PASSWORD_SIGN_IN_BUTTON_STRATEGIES,
    SIGN_IN_ERROR_STRATEGIES,
    SIGN_IN_RADIO_BUTTON_STRATEGIES,
)
from views.auth.view_strategies import (
    AUTH_RESTART_MESSAGES,
    CAPTCHA_REQUIRED_INDICATORS,
    CAPTCHA_VIEW_IDENTIFIERS,
    EMAIL_VIEW_IDENTIFIERS,
    ERROR_VIEW_IDENTIFIERS,
    INTERACTIVE_CAPTCHA_IDENTIFIERS,
    LIBRARY_VIEW_VERIFICATION_STRATEGIES,
    PASSWORD_VIEW_IDENTIFIERS,
)
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class LoginVerificationState(Enum):
    SUCCESS = "success"
    CAPTCHA = "captcha"
    TWO_FACTOR = "two_factor"
    PUZZLE = "puzzle"
    INCORRECT_PASSWORD = "incorrect_password"
    ERROR = "error"
    UNKNOWN = "unknown"


class AuthenticationHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        self.keyboard_check_active = False  # Flag to track if keyboard hide check is active
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _focus_input_field_if_needed(self, field_strategies, field_type="input"):
        """Helper method to focus an input field only if it doesn't already have focus.

        Args:
            field_strategies: List of tuples (strategy, locator) to find the field
            field_type: String description of field type (e.g., "email", "password")

        Returns:
            The focused field element if successful, None otherwise
        """
        try:
            # First try to find if any edit text already has focus
            has_focus = False
            focused_field = None

            try:
                focused_element = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.EditText[@focused='true']"
                )
                if focused_element and focused_element.is_displayed():
                    logger.info(f"Found a focused edit text field")
                    # Now check if this is the field we're looking for
                    for strategy, locator in field_strategies:
                        try:
                            field = self.driver.find_element(strategy, locator)
                            if field.get_attribute("resource-id") == focused_element.get_attribute(
                                "resource-id"
                            ):
                                logger.info(
                                    f"{field_type.capitalize()} field already has focus, no need to tap"
                                )
                                focused_field = field
                                has_focus = True
                                break
                        except Exception:
                            continue
            except NoSuchElementException:
                # No focused element found
                pass
            except Exception as focus_err:
                logger.debug(f"Error checking for focused element: {focus_err}")

            # If no field has focus, find and tap one
            if not has_focus:
                for strategy, locator in field_strategies:
                    try:
                        field = self.driver.find_element(strategy, locator)
                        if field and field.is_displayed():
                            logger.info(
                                f"Found {field_type} field with strategy: {strategy}={locator}, tapping it"
                            )
                            field.click()
                            logger.info(f"Successfully tapped the {field_type} input field")
                            focused_field = field
                            break
                    except Exception as tap_err:
                        logger.debug(f"Error tapping {field_type} field with {strategy}={locator}: {tap_err}")
                        continue

            # If we have a focused field (either already or newly focused), hide the keyboard
            if focused_field:
                try:
                    self.driver.hide_keyboard()
                    logger.info("Successfully hid the keyboard")
                except Exception as hide_err:
                    logger.warning(f"Could not hide keyboard: {hide_err}")

            return focused_field

        except Exception as e:
            logger.warning(f"Error handling {field_type} field focus: {e}", exc_info=True)
            return None

    def prepare_for_authentication(self):
        """
        Prepare the app for authentication by navigating to the sign-in screen if needed.
        Always requires manual authentication via VNC.

        Returns:
            dict: Status information containing:
                - state: current AppState (LIBRARY, HOME, SIGN_IN, etc.)
                - authenticated: boolean indicating if user is authenticated
                - already_authenticated: boolean indicating if already logged in
                - vnc_url: URL to access VNC for manual login
        """
        try:
            # Access the automator directly from the driver
            # This ensures we're using the correct automator instance for this specific user
            automator = getattr(self.driver, "automator", None)

            if not automator:
                logger.error(
                    "Driver does not have automator reference. This should not happen.", exc_info=True
                )
                return {
                    "state": "UNKNOWN",
                    "authenticated": False,
                    "already_authenticated": False,
                    "error": "Driver is not properly initialized with automator reference",
                    "fatal_error": True,
                }

            # Log automator details for debugging
            if automator:
                device_id = getattr(automator, "device_id", "unknown")
                profile_email = "unknown"
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        profile_email = current_profile["email"]

            # Verify we have the state machine
            if not hasattr(automator, "state_machine") or not automator.state_machine:
                logger.error("Automator does not have state machine. This should not happen.", exc_info=True)
                return {
                    "state": "UNKNOWN",
                    "authenticated": False,
                    "already_authenticated": False,
                    "error": "Automator is not properly initialized with state machine",
                    "fatal_error": True,
                }

            # Force a thorough state update to detect LIBRARY_SIGN_IN if present
            # This is critical to ensure we don't miss the empty library with sign-in button
            try:
                # Force view inspector to check specifically for empty library with sign-in button
                logger.info("Forcing thorough state detection to check for LIBRARY_SIGN_IN state")

                # First check if we can find the sign-in button directly
                found_sign_in_button = False
                from views.library.interaction_strategies import (
                    LIBRARY_SIGN_IN_BUTTON_STRATEGIES,
                )

                for strategy, locator in LIBRARY_SIGN_IN_BUTTON_STRATEGIES:
                    try:
                        button = self.driver.find_element(strategy, locator)
                        if button.is_displayed():
                            logger.info(f"Found sign-in button using strategy: {strategy}={locator}")
                            found_sign_in_button = True
                            break
                    except Exception:
                        continue

                # Now have the state machine update its state
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                state_name = current_state.name if hasattr(current_state, "name") else str(current_state)
                logger.info(f"Current state before authentication preparation: {state_name}")

                # If we found the sign-in button but state_name isn't LIBRARY_SIGN_IN,
                # override it because we know we're in LIBRARY_SIGN_IN
                if found_sign_in_button and state_name != "LIBRARY_SIGN_IN":
                    logger.info(
                        f"State machine reports {state_name} but we found sign-in button - overriding to LIBRARY_SIGN_IN"
                    )
                    state_name = "LIBRARY_SIGN_IN"
            except Exception as e:
                logger.warning(f"Error in thorough state detection: {e}", exc_info=True)
                # Fall back to regular state update
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                state_name = current_state.name if hasattr(current_state, "name") else str(current_state)
                logger.info(f"Current state before authentication preparation: {state_name}")

            # Check for empty library with sign-in button
            if state_name == "LIBRARY_SIGN_IN":
                logger.info(
                    "Found empty library with sign-in button, we'll need to proceed with authentication"
                )
                email = ""
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        email = current_profile["email"]

                # Start the keyboard check to continuously hide the keyboard in AUTH state
                self.start_keyboard_check()

                return {
                    "state": "LIBRARY_SIGN_IN",
                    "authenticated": False,
                    "already_authenticated": False,
                    "vnc_url": get_formatted_vnc_url(email),
                }

            # Check if we're already in a logged-in state (LIBRARY, HOME, or READING)
            if state_name in ["LIBRARY", "HOME", "READING"]:
                logger.info(f"Already authenticated in {state_name} state")

                # If we're in HOME state, try to navigate to LIBRARY for consistency
                if state_name == "HOME":
                    try:
                        logger.info("In HOME state, trying to navigate to LIBRARY tab")
                        library_tab = self.driver.find_element(
                            AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"
                        )
                        library_tab.click()
                        logger.info("Clicked on LIBRARY tab")
                        time.sleep(1)  # Wait for tab transition

                        # After clicking LIBRARY tab, check specifically for sign-in button first
                        # This ensures we detect LIBRARY_SIGN_IN state even if state machine misses it
                        found_sign_in_button = False
                        from views.library.interaction_strategies import (
                            LIBRARY_SIGN_IN_BUTTON_STRATEGIES,
                        )

                        for strategy, locator in LIBRARY_SIGN_IN_BUTTON_STRATEGIES:
                            try:
                                button = self.driver.find_element(strategy, locator)
                                if button.is_displayed():
                                    logger.info(
                                        f"Found sign-in button after LIBRARY tab click using strategy: {strategy}={locator}"
                                    )
                                    found_sign_in_button = True
                                    break
                            except Exception:
                                continue

                        # If we found a sign-in button, we're in LIBRARY_SIGN_IN state
                        if found_sign_in_button:
                            logger.info(
                                "Found sign-in button after clicking LIBRARY tab - we're in LIBRARY_SIGN_IN state"
                            )
                            # For empty library with sign-in button, return LIBRARY_SIGN_IN state
                            email = ""
                            if hasattr(automator, "profile_manager") and automator.profile_manager:
                                current_profile = automator.profile_manager.get_current_profile()
                                if current_profile and "email" in current_profile:
                                    email = current_profile["email"]

                            return {
                                "state": "LIBRARY_SIGN_IN",
                                "authenticated": False,
                                "already_authenticated": False,
                                "vnc_url": get_formatted_vnc_url(email),
                            }

                        # If no sign-in button, proceed with normal state update
                        automator.state_machine.update_current_state()
                        updated_state = automator.state_machine.current_state
                        updated_state_name = (
                            updated_state.name if hasattr(updated_state, "name") else str(updated_state)
                        )

                        if updated_state_name == "LIBRARY":
                            logger.info("Successfully navigated to LIBRARY state")
                            state_name = "LIBRARY"
                        # Check if we navigated to empty library with sign-in button
                        elif updated_state_name == "LIBRARY_SIGN_IN":
                            logger.info("Navigated to empty library with sign-in button")
                            # For empty library with sign-in button, return LIBRARY_SIGN_IN state
                            email = ""
                            if hasattr(automator, "profile_manager") and automator.profile_manager:
                                current_profile = automator.profile_manager.get_current_profile()
                                if current_profile and "email" in current_profile:
                                    email = current_profile["email"]

                            return {
                                "state": "LIBRARY_SIGN_IN",
                                "authenticated": False,
                                "already_authenticated": False,
                                "vnc_url": get_formatted_vnc_url(email),
                            }
                    except Exception as e:
                        logger.warning(f"Error navigating from HOME to LIBRARY: {e}", exc_info=True)
                        # Continue with HOME state

                # For authenticated states, still provide a VNC URL for convenience
                # (it will be ignored by the client if already authenticated)
                email = ""
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        email = current_profile["email"]

                return {
                    "state": state_name,
                    "authenticated": True,
                    "already_authenticated": True,
                    "vnc_url": get_formatted_vnc_url(email),
                }

            # Check if we're in NOTIFICATION_PERMISSION state - handle it first
            if state_name == "NOTIFICATION_PERMISSION":
                logger.info("In NOTIFICATION_PERMISSION state - handling permission dialog")
                # Handle the notification permission directly here
                try:
                    from handlers.permissions_handler import PermissionsHandler

                    permissions_handler = PermissionsHandler(self.driver)
                    if permissions_handler.handle_notifications_permission(should_allow=True):
                        logger.info("Successfully handled notification permission")
                        # Update state after handling permission
                        time.sleep(1)
                        # Get state machine from driver's automator
                        if hasattr(self.driver, "automator") and hasattr(
                            self.driver.automator, "state_machine"
                        ):
                            state_name = self.driver.automator.state_machine.update_current_state().name
                            logger.info(f"State after handling notification permission: {state_name}")

                            # If we're now in HOME state (after first launch), continue with normal flow
                            # to navigate to sign-in screen
                            if state_name == "HOME":
                                logger.info(
                                    "Now in HOME state after handling notification - will continue to navigate to sign-in"
                                )
                                # Don't return early, let the normal flow handle navigation from HOME to SIGN_IN
                            # If we're now in a sign-in state, return that we're ready for manual auth
                            elif state_name in [
                                "SIGN_IN",
                                "SIGN_IN_PASSWORD",
                                "CAPTCHA",
                                "TWO_FACTOR",
                                "PUZZLE",
                            ]:
                                email = ""
                                if hasattr(automator, "profile_manager") and automator.profile_manager:
                                    current_profile = automator.profile_manager.get_current_profile()
                                    if current_profile and "email" in current_profile:
                                        email = current_profile["email"]

                                return {
                                    "state": state_name,
                                    "authenticated": False,
                                    "already_authenticated": False,
                                    "vnc_url": get_formatted_vnc_url(email),
                                }
                            # If we're in LIBRARY or other authenticated state, return success
                            elif state_name == "LIBRARY":
                                email = ""
                                if hasattr(automator, "profile_manager") and automator.profile_manager:
                                    current_profile = automator.profile_manager.get_current_profile()
                                    if current_profile and "email" in current_profile:
                                        email = current_profile["email"]

                                return {
                                    "state": state_name,
                                    "authenticated": True,
                                    "already_authenticated": True,
                                    "vnc_url": get_formatted_vnc_url(email),
                                }
                    else:
                        logger.warning("Failed to handle notification permission")
                except Exception as e:
                    logger.error(f"Error handling notification permission: {e}")

                # If we couldn't handle the permission or determine state, continue with normal flow

            # Check if we're already in a sign-in flow state
            sign_in_states = ["SIGN_IN", "SIGN_IN_PASSWORD", "CAPTCHA", "TWO_FACTOR", "PUZZLE"]
            if state_name in sign_in_states:
                logger.info(f"Already in sign-in flow: {state_name}")

                # Always require manual login
                # Get email from automator's current profile if available
                email = ""
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        email = current_profile["email"]

                # Get the formatted VNC URL with the current email and ensure VNC is running
                formatted_vnc_url = get_formatted_vnc_url(email)

                # Explicitly verify the emulator is running before proceeding
                if hasattr(automator, "emulator_manager") and automator.emulator_manager:
                    try:
                        # Check if the emulator is ready
                        is_ready = automator.emulator_manager.emulator_launcher.is_emulator_ready(email)
                        logger.info(f"Emulator ready check for {email}: {is_ready}")

                        if not is_ready:
                            logger.warning(f"Emulator not ready for {email}, may need to be restarted")
                    except Exception as e:
                        logger.warning(f"Error checking emulator readiness: {e}", exc_info=True)

                # Focus the email field if needed (only for SIGN_IN state)
                if state_name == "SIGN_IN":
                    self._focus_input_field_if_needed(EMAIL_FIELD_STRATEGIES, "email")

                return {
                    "state": state_name,
                    "authenticated": False,
                    "already_authenticated": False,
                    "vnc_url": formatted_vnc_url,
                }

            # We need to navigate to the sign-in screen
            logger.info(f"Need to navigate to sign-in screen from {state_name}")

            # Make sure the Kindle app is running - this is crucial for auth
            # First check if we need to install the app
            if hasattr(automator, "ensure_kindle_installed") and callable(automator.ensure_kindle_installed):
                try:
                    logger.info("Ensuring Kindle app is installed")
                    install_result = automator.ensure_kindle_installed()
                    if install_result:
                        logger.info("Kindle app is installed and ready")
                    else:
                        logger.warning("Could not verify Kindle app installation")
                except Exception as e:
                    logger.warning(f"Error ensuring Kindle app is installed: {e}", exc_info=True)

            # If we're in HOME state, try to use transition_to_library which handles navigation
            # from HOME to sign-in states properly
            success = False
            if state_name == "HOME":
                logger.info("In HOME state - using transition_to_library to navigate to sign-in")
                try:
                    final_state = automator.state_machine.transition_to_library()
                    state_name = final_state.name if hasattr(final_state, "name") else str(final_state)
                    logger.info(f"After transition_to_library, state is: {state_name}")

                    # Check if we reached a sign-in state
                    if state_name in ["SIGN_IN", "SIGN_IN_PASSWORD", "LIBRARY_SIGN_IN"]:
                        success = True
                    elif state_name == "LIBRARY":
                        # Already authenticated
                        logger.info("Already authenticated - in LIBRARY state")
                        email = ""
                        if hasattr(automator, "profile_manager") and automator.profile_manager:
                            current_profile = automator.profile_manager.get_current_profile()
                            if current_profile and "email" in current_profile:
                                email = current_profile["email"]

                        return {
                            "state": state_name,
                            "authenticated": True,
                            "already_authenticated": True,
                            "vnc_url": get_formatted_vnc_url(email),
                        }
                except Exception as e:
                    logger.error(f"Error using transition_to_library: {e}")
                    success = False

            # Only restart the app if we're not in HOME state or if transition failed
            if not success and state_name != "HOME":
                try:
                    if hasattr(automator, "restart_kindle_app"):
                        logger.info("Restarting Kindle app to get to sign-in screen")
                        device_id = getattr(automator, "device_id", "unknown")
                        success = automator.restart_kindle_app()
                        if not success:
                            logger.warning(
                                "restart_kindle_app reported failure, will try alternative approaches"
                            )
                    else:
                        logger.error("Automator doesn't have restart_kindle_app method")
                        # Try to launch app directly as a fallback
                        try:
                            logger.info("Attempting to launch Kindle app directly")
                            device_id = getattr(automator, "device_id", "unknown")
                            automator.driver.activate_app("com.amazon.kindle")
                            time.sleep(3)  # Give it time to launch
                            success = True
                        except Exception as launch_e:
                            logger.error(f"Error launching Kindle app: {launch_e}")
                except Exception as e:
                    logger.error(f"Error restarting app: {e}")
                # Try to at least launch the app
                try:
                    logger.info("Fallback - attempting to launch Kindle app via activate_app")
                    device_id = getattr(automator, "device_id", "unknown")
                    automator.driver.activate_app("com.amazon.kindle")
                    time.sleep(3)  # Give it time to launch
                    success = True
                except Exception as activate_e:
                    logger.warning(f"Error activating Kindle app: {activate_e}", exc_info=True)

            # Update our state to see where we are
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state
            state_name = current_state.name if hasattr(current_state, "name") else str(current_state)
            logger.info(f"Current state after app launch: {state_name}")

            # For authenticated states, provide a VNC URL with current email
            email = ""
            if hasattr(automator, "profile_manager") and automator.profile_manager:
                current_profile = automator.profile_manager.get_current_profile()
                if current_profile and "email" in current_profile:
                    email = current_profile["email"]

            # Check if we've reached a key target state
            if state_name == "SIGN_IN":
                logger.info("Successfully reached sign-in screen")

                # Tap the email address input field and then hide the keyboard
                try:
                    for strategy, locator in EMAIL_FIELD_STRATEGIES:
                        try:
                            email_field = self.driver.find_element(strategy, locator)
                            if email_field and email_field.is_displayed():
                                logger.info(
                                    f"Found email field with strategy: {strategy}={locator}, tapping it"
                                )
                                email_field.click()
                                logger.info("Successfully tapped the email input field")

                                # Hide the keyboard after tapping
                                try:
                                    self.driver.hide_keyboard()
                                    logger.info("Successfully hid the keyboard")
                                except Exception as hide_err:
                                    logger.warning(f"Could not hide keyboard: {hide_err}")

                                break
                        except Exception as tap_err:
                            logger.debug(f"Error tapping email field with {strategy}={locator}: {tap_err}")
                            continue
                except Exception as e:
                    logger.warning(f"Error tapping email field: {e}", exc_info=True)

                # Always require manual login
                # Start the keyboard check to continuously hide the keyboard in AUTH state
                self.start_keyboard_check()

                return {
                    "state": "SIGN_IN",
                    "authenticated": False,
                    "already_authenticated": False,
                    "vnc_url": get_formatted_vnc_url(email),
                }

            # If we reached a library state after restart, we're already logged in
            if state_name in ["LIBRARY", "HOME", "READING"]:
                logger.info(f"Already authenticated in {state_name}")
                return {
                    "state": state_name,
                    "authenticated": True,
                    "already_authenticated": True,
                    "vnc_url": get_formatted_vnc_url(email),
                }

            # As a fallback, always try to use transition_to_library which may go through auth flow
            # This is the most important part - we want to make sure we're in a good state
            logger.info("Using transition_to_library to ensure we reach AUTH or LIBRARY state")
            try:
                # This is a critical operation - we must launch the Kindle app
                # and either get to sign-in screen or library

                # First, let's make sure the app is active
                try:
                    logger.info("Ensuring Kindle app is active via activate_app")
                    device_id = getattr(automator, "device_id", "unknown")
                    automator.driver.activate_app("com.amazon.kindle")
                    time.sleep(3)  # Give it time to launch
                except Exception as launch_e:
                    logger.warning(f"Error activating Kindle app: {launch_e}")

                # Now attempt transition_to_library which will go through the auth flow if needed
                logger.info("Executing transition_to_library to navigate through auth flow")
                device_id = getattr(automator, "device_id", "unknown")
                final_state = automator.transition_to_library()
                logger.info(f"transition_to_library result: {final_state}")

                # Check if transition ended in an acceptable state
                if final_state != AppState.LIBRARY and not final_state.is_auth_state():
                    logger.error(
                        "transition_to_library failed - unable to navigate to library or auth state",
                        exc_info=True,
                    )
                    # Get the formatted VNC URL for error response
                    formatted_vnc_url = get_formatted_vnc_url(email)

                    # Try to get current state for debugging
                    try:
                        automator.state_machine.update_current_state()
                        current_state = automator.state_machine.current_state
                        state_name = (
                            current_state.name if hasattr(current_state, "name") else str(current_state)
                        )
                        logger.warning(f"Current state after failed transition: {state_name}")
                    except Exception as state_err:
                        logger.warning(
                            f"Error getting state after failed transition: {state_err}", exc_info=True
                        )
                        state_name = "UNKNOWN"

                    return {
                        "state": state_name,
                        "authenticated": False,
                        "already_authenticated": False,
                        "vnc_url": formatted_vnc_url,
                        "error": "Failed to navigate to library or authentication state",
                        "message": f"transition_to_library failed while in {state_name} state",
                    }

                # Update our state to see where we are
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                state_name = current_state.name if hasattr(current_state, "name") else str(current_state)
                logger.info(f"Current state after transition_to_library: {state_name}")

                # Get the email for this profile to use in VNC URL
                email = ""
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        email = current_profile["email"]

                # Get the formatted VNC URL with the current email
                formatted_vnc_url = get_formatted_vnc_url(email)

                # Handle based on the state we're now in
                if state_name == "SIGN_IN":
                    logger.info("Successfully navigated to SIGN_IN state")

                    # Focus the email field if needed
                    self._focus_input_field_if_needed(EMAIL_FIELD_STRATEGIES, "email")

                    return {
                        "state": "SIGN_IN",
                        "authenticated": False,
                        "already_authenticated": False,
                        "vnc_url": formatted_vnc_url,
                    }
                elif state_name in ["LIBRARY", "HOME"]:
                    logger.info(f"Successfully navigated to {state_name} state")
                    return {
                        "state": state_name,
                        "authenticated": True,
                        "already_authenticated": True,
                        "vnc_url": formatted_vnc_url,
                    }
                else:
                    # We're in some other state - give detailed information
                    logger.warning(f"After transition_to_library, in unexpected state: {state_name}")

                    # Return with the unexpected state
                    return {
                        "state": state_name,
                        "authenticated": False,
                        "already_authenticated": False,
                        "vnc_url": formatted_vnc_url,
                        "message": f"In unexpected state after navigation attempt: {state_name}",
                    }
            except Exception as e:
                logger.error(f"Error in transition_to_library: {e}", exc_info=True)
                # Capture and log the full stack trace
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}", exc_info=True)

                # Try one more time to update our state
                try:
                    automator.state_machine.update_current_state()
                    current_state = automator.state_machine.current_state
                    state_name = current_state.name if hasattr(current_state, "name") else str(current_state)
                    logger.info(f"Current state after error: {state_name}")
                except Exception as state_err:
                    logger.warning(f"Error getting state after transition error: {state_err}", exc_info=True)
                    state_name = "UNKNOWN"

            # If we get here, we had some serious issues
            # Get email from automator's current profile if available
            email = ""
            if hasattr(automator, "profile_manager") and automator.profile_manager:
                current_profile = automator.profile_manager.get_current_profile()
                if current_profile and "email" in current_profile:
                    email = current_profile["email"]

            # Get the formatted VNC URL with the current email
            formatted_vnc_url = get_formatted_vnc_url(email)

            # Last attempt - if we're in SIGN_IN, HOME, or LIBRARY, we can still give a focused response
            if state_name == "SIGN_IN":
                logger.info("Despite errors, we are in SIGN_IN state")
                return {
                    "state": "SIGN_IN",
                    "authenticated": False,
                    "already_authenticated": False,
                    "vnc_url": formatted_vnc_url,
                }
            elif state_name in ["LIBRARY", "HOME"]:
                logger.info(f"Despite errors, we are in {state_name} state")
                return {
                    "state": state_name,
                    "authenticated": True,
                    "already_authenticated": True,
                    "vnc_url": formatted_vnc_url,
                }

            # Last resort - return error with as much info as possible
            return {
                "state": state_name,
                "authenticated": False,
                "already_authenticated": False,
                "vnc_url": formatted_vnc_url,
                "error": f"Failed to navigate to sign-in screen or library from {state_name}",
            }

        except Exception as e:
            logger.error(f"Error in prepare_for_authentication: {e}", exc_info=True)
            # Even in case of error, try to get the email if possible
            email = ""
            try:
                if hasattr(automator, "profile_manager") and automator.profile_manager:
                    current_profile = automator.profile_manager.get_current_profile()
                    if current_profile and "email" in current_profile:
                        email = current_profile["email"]
            except Exception:
                pass  # Ignore any errors in getting the email

            # Get the formatted VNC URL with the email if available
            formatted_vnc_url = get_formatted_vnc_url(email)

            return {
                "state": "ERROR",
                "authenticated": False,
                "already_authenticated": False,
                "vnc_url": formatted_vnc_url,
                "error": str(e),
            }

    def sign_in(self):
        """
        Manual authentication via VNC is required.

        Returns:
            A tuple indicating automated sign-in is not supported
        """
        try:
            logger.info("Authentication must be done manually via VNC")

            # Check for captcha and log it
            if self._is_captcha_screen():
                logger.info("Captcha detected - manual intervention required")

            # Return error to indicate VNC is required
            return (
                LoginVerificationState.ERROR,
                "Authentication must be done manually via VNC",
            )
        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            return False

    def _select_sign_in_if_needed(self):
        """Select the sign in radio button if present"""
        try:
            for strategy, locator in SIGN_IN_RADIO_BUTTON_STRATEGIES:
                try:
                    radio = self.driver.find_element(strategy, locator)
                    if not radio.is_selected():
                        logger.info("Clicking sign in radio button")
                        radio.click()
                        # Wait for radio button animation to complete
                        WebDriverWait(self.driver, 5).until(
                            lambda driver: any(
                                self._try_find_element(strategy, locator)
                                for strategy, locator in EMAIL_FIELD_STRATEGIES
                            )
                        )
                    return
                except:
                    continue
        except Exception as e:
            logger.debug(f"No sign in radio button found: {e}")

    # Email and password methods removed - now using manual VNC authentication only

    def _verify_login(self):
        """Verify successful login by waiting for library view to load or detect error conditions."""
        try:
            logger.info("Verifying login success...")

            def check_login_result(driver):
                # First check for error message box which indicates authentication problems
                try:
                    error_box = driver.find_element(
                        AppiumBy.XPATH, "//android.view.View[@resource-id='auth-error-message-box']"
                    )
                    if error_box:
                        # Try to find the specific error message within the box
                        try:
                            # First try to find the "Your password is incorrect" message
                            error_message = driver.find_element(
                                AppiumBy.XPATH,
                                "//android.view.View[@resource-id='auth-error-message-box']//android.view.View[contains(@text, 'incorrect')]",
                            )
                            logger.warning(f"Authentication error: {error_message.text}", exc_info=True)
                            return (LoginVerificationState.ERROR, error_message.text)
                        except:
                            # If specific message not found, try to get any text from the error box
                            try:
                                error_texts = []
                                error_elements = driver.find_elements(
                                    AppiumBy.XPATH,
                                    "//android.view.View[@resource-id='auth-error-message-box']//android.view.View",
                                )
                                for elem in error_elements:
                                    if elem.text and elem.text.strip():
                                        error_texts.append(elem.text.strip())

                                if error_texts:
                                    error_message = " - ".join(error_texts)
                                    logger.warning(f"Authentication error: {error_message}", exc_info=True)
                                    return (LoginVerificationState.ERROR, error_message)
                                else:
                                    logger.warning(
                                        "Authentication error box found but couldn't extract message"
                                    )
                                    return (LoginVerificationState.ERROR, "Unknown authentication error")
                            except Exception as e:
                                logger.warning(f"Error extracting message from error box: {e}", exc_info=True)
                                return (LoginVerificationState.ERROR, "Authentication error")
                except:
                    # No error box found, continue with other checks
                    pass

                # Check if the sign-in button is disabled, which *might* indicate an authentication in progress
                # or an error state - we need to carefully distinguish between these states
                try:
                    sign_in_button = driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[@text='Sign in' and @enabled='false']"
                    )
                    if sign_in_button:
                        logger.info("Sign-in button is disabled, could be processing authentication...")

                        # First check if we have any explicit error messages
                        error_found = False
                        for strategy in AUTH_ERROR_STRATEGIES:
                            try:
                                error = driver.find_element(*strategy)
                                if error and error.text.strip():
                                    logger.warning(
                                        f"Found error message with disabled button: {error.text.strip()}",
                                        exc_info=True,
                                    )
                                    error_found = True
                                    return (LoginVerificationState.ERROR, error.text.strip())
                            except:
                                continue

                        # If no error text was found, this could be an in-progress authentication
                        # Return None to continue waiting rather than immediately failing
                        if not error_found:
                            # Check for library view indicators first - maybe we're actually logged in
                            # despite the sign-in button still being visible in the DOM
                            for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                                try:
                                    element = driver.find_element(by, locator)
                                    if element and element.is_displayed():
                                        logger.info(
                                            f"Found library view element '{locator}' while sign-in button is disabled"
                                        )
                                        return LoginVerificationState.SUCCESS
                                except:
                                    pass

                            # Return None to keep waiting
                            return None
                except:
                    # No disabled sign-in button found, continue with other checks
                    pass

                # Check if we're still on the sign-in page with a disabled button
                # This indicates we're in a transitional state where the password is being verified
                try:
                    sign_in_button = driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[@text='Sign in']"
                    )
                    if not sign_in_button.is_enabled():
                        logger.info("Sign-in button is disabled, still processing login...")
                        return None  # Return None to continue waiting
                except:
                    pass

                # Check for password field - if it's still present, we're still on the sign-in page
                try:
                    password_field = driver.find_element(
                        AppiumBy.XPATH, "//android.widget.EditText[@password='true'][@hint='Amazon password']"
                    )
                    if password_field.is_displayed():
                        # Before continuing to wait, check again for error messages that might have appeared
                        for strategy in AUTH_ERROR_STRATEGIES:
                            try:
                                error = driver.find_element(*strategy)
                                if error and error.text.strip():
                                    logger.warning(
                                        f"Found error message: {error.text.strip()}", exc_info=True
                                    )
                                    return (LoginVerificationState.ERROR, error.text.strip())
                            except:
                                continue

                        logger.info("Still on password page, waiting for transition...")
                        return None  # Return None to continue waiting
                except:
                    pass

                # Now check for CAPTCHA since we're not in a transitional state
                logger.info("Checking for CAPTCHA...")
                # Log what indicators we're looking for
                logger.info("Looking for CAPTCHA indicators:")
                indicators_found = 0
                for strategy, locator in CAPTCHA_REQUIRED_INDICATORS:
                    try:
                        driver.find_element(strategy, locator)
                        logger.info(f"Found CAPTCHA indicator: {strategy}={locator}")
                        indicators_found += 1
                    except:
                        logger.debug(f"CAPTCHA indicator not found: {strategy}={locator}")

                if indicators_found >= 3:
                    logger.info(f"CAPTCHA detected! Found {indicators_found} indicators")
                    return LoginVerificationState.CAPTCHA

                # Check for library view
                logger.info("Checking for library view...")
                for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                    try:
                        driver.find_element(by, locator)
                        logger.info(f"Found library element: {locator}")
                        return LoginVerificationState.SUCCESS
                    except:
                        logger.debug(f"Library element not found: {locator}")
                        continue

                # Check for error messages
                logger.info("Checking for error messages...")
                for strategy in AUTH_ERROR_STRATEGIES:
                    try:
                        error = driver.find_element(*strategy)
                        if error and error.text.strip():
                            logger.info(f"Found error message: {error.text.strip()}")
                            return (LoginVerificationState.ERROR, error.text.strip())
                    except:
                        continue

                # Check for auth errors that require restart
                for strategy, locator in AUTH_RESTART_MESSAGES:
                    try:
                        element = driver.find_element(strategy, locator)
                        if element:
                            text = element.get_attribute("text")
                            logger.info(f"Found auth error text: '{text}'")
                            logger.info("Found auth error requiring restart - storing page source")
                            source = driver.page_source
                            store_page_source(source, "auth_restart_error")
                            return (LoginVerificationState.ERROR, text)
                    except NoSuchElementException:
                        logger.debug("No auth restart error text found - continuing")
                        continue

                # Save page source
                filepath = store_page_source(driver.page_source, "auth_unknown_state")
                logger.info(f"Stored unknown state page source at: {filepath}")

                # Log page source when we can't determine the state
                logger.info("No definitive state found, returning UNKNOWN")
                return LoginVerificationState.UNKNOWN

            # Wait for any result with a longer timeout since we're handling transitions
            try:
                logger.info("Waiting for login verification result...")
                result = WebDriverWait(self.driver, 30).until(check_login_result)  # 30 second timeout
                logger.info(f"Login verification result: {result}")

                if result == LoginVerificationState.SUCCESS:
                    logger.info("Successfully verified library view")
                    return True
                elif result == LoginVerificationState.CAPTCHA:
                    # Handle CAPTCHA immediately
                    logger.info("Handling CAPTCHA during verification...")
                    if not self._handle_captcha():
                        # If _handle_captcha returns False, it means we need client interaction
                        # This is actually a success case where we need the client to solve the CAPTCHA
                        logger.info("CAPTCHA needs client interaction - returning True")
                        return True
                    return True
                elif isinstance(result, tuple) and result[0] == LoginVerificationState.INCORRECT_PASSWORD:
                    # Special handling for incorrect password
                    logger.warning(f"Login failed with incorrect password: {result[1]}", exc_info=True)
                    # Return the result tuple directly so the server can handle it specifically
                    return result
                elif isinstance(result, tuple) and result[0] == LoginVerificationState.ERROR:
                    logger.warning(f"Login failed: {result[1]}")
                    return result
                else:
                    logger.warning(f"Could not verify login status, state: {result}")
                    return False

            except TimeoutException:
                # If we timeout, check what state we're in before giving up
                # First, check if we can find any library view indicators
                for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                    try:
                        element = self.driver.find_element(by, locator)
                        if element and element.is_displayed():
                            logger.info(
                                f"Found library view element '{locator}' after timeout - login successful"
                            )
                            # Stop the keyboard check as we've completed authentication
                            self.stop_keyboard_check()
                            return True
                    except:
                        continue

                # Check if we still have a disabled sign-in button
                try:
                    sign_in_button = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.Button[@text='Sign in' and @enabled='false']"
                    )
                    # Check if we have any error messages
                    error_found = False
                    for strategy in AUTH_ERROR_STRATEGIES:
                        try:
                            error_elem = self.driver.find_element(*strategy)
                            if error_elem and error_elem.text.strip():
                                error_found = True
                                break
                        except:
                            continue

                    if sign_in_button and not error_found:
                        # We have a disabled button but no error messages - likely still processing
                        logger.warning("Authentication still processing after timeout - continuing to wait")
                        # Try waiting a bit longer (extra 10 seconds)
                        time.sleep(10)
                        # Check one more time for library view
                        for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                            try:
                                element = self.driver.find_element(by, locator)
                                if element and element.is_displayed():
                                    logger.info(
                                        f"Found library view element '{locator}' after extended wait - login successful"
                                    )
                                    # Stop the keyboard check as we've completed authentication
                                    self.stop_keyboard_check()
                                    return True
                            except:
                                continue
                except:
                    pass

                # If we reach here, we truly timed out
                filepath = store_page_source(self.driver.page_source, "auth_login_timeout")
                logger.info(f"Stored unknown timeout page source at: {filepath}")

                logger.error("Could not verify login status within timeout", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"Error verifying login: {e}", exc_info=True)
            return False

    def hide_keyboard_if_visible(self):
        """Attempt to hide the keyboard if it's visible.

        Used for VNC sessions where we want to hide the Android keyboard
        since the user is using their native OS keyboard.

        Returns:
            bool: True if keyboard was detected and hidden, False otherwise
        """
        try:
            # Check if keyboard is visible
            keyboard_visible = False
            try:
                # Try using the is_keyboard_shown method if available
                if hasattr(self.driver, "is_keyboard_shown") and callable(self.driver.is_keyboard_shown):
                    keyboard_visible = self.driver.is_keyboard_shown()
                    if keyboard_visible:
                        logger.debug("Keyboard detected using is_keyboard_shown()")
            except Exception as e:
                logger.debug(f"Error checking keyboard visibility: {e}")

            # If keyboard visibility check failed or returned false, try alternative detection
            if not keyboard_visible:
                # Look for EditText elements that are in focus
                try:
                    focused_element = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.EditText[@focused='true']"
                    )
                    if focused_element and focused_element.is_displayed():
                        logger.debug("Found focused EditText element, keyboard likely visible")
                        keyboard_visible = True
                except Exception:
                    # No focused input element found
                    pass

            # If keyboard is visible, try to hide it
            if keyboard_visible:
                self.driver.hide_keyboard()
                logger.debug("Successfully hid keyboard")
                return True
            return False
        except Exception as e:
            logger.debug(f"Error in hide_keyboard_if_visible: {e}")
            return False

    def start_keyboard_check(self):
        """Start the continuous keyboard check.

        This sets a flag that will be detected by the state machine to
        continuously check for and hide the keyboard while in AUTH state.
        """
        logger.info("Starting continuous keyboard check for AUTH state")
        self.keyboard_check_active = True

    def stop_keyboard_check(self):
        """Stop the continuous keyboard check."""
        logger.info("Stopping continuous keyboard check for AUTH state")
        self.keyboard_check_active = False

    def is_keyboard_check_active(self):
        """Check if the keyboard check is currently active.

        Returns:
            bool: True if keyboard check is active, False otherwise
        """
        return self.keyboard_check_active

    def _check_for_errors(self):
        """Check for error messages after attempting to sign in."""
        logger.info("Checking for error messages...")

        try:
            error = WebDriverWait(self.driver, 5).until(
                lambda driver: next(
                    (
                        error.text.strip()
                        for strategy in AUTH_ERROR_STRATEGIES
                        if (error := self._try_find_element(*strategy))
                        and error.text.strip()
                        and any(
                            msg in error.text
                            for msg in ["No account found with email address", "incorrect password"]
                        )
                    ),
                    None,
                )
            )
            if error:
                logger.info(f"Found error message: {error}")
                return True
        except TimeoutException:
            logger.info("No error messages found")
            return False

        return False

    def _is_email_screen(self):
        """Check if we're on the email input screen - used for state detection only"""
        try:
            for strategy, locator in EMAIL_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        # Focus the email field if needed
                        self._focus_input_field_if_needed([(strategy, locator)], "email")
                        return True
                except:
                    continue
            return False
        except:
            return False

    def _is_password_screen(self):
        """Check if we're on the password input screen - used for state detection only"""
        try:
            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS:
                try:
                    element = self.driver.find_element(strategy, locator)
                    if element and element.is_displayed():
                        # Focus the password field if needed
                        self._focus_input_field_if_needed([(strategy, locator)], "password")
                        return True
                except:
                    continue
            return False
        except:
            return False

    def _is_captcha_screen(self):
        """Check if we're on the captcha screen."""
        try:
            # Check for multiple captcha indicators to be confident
            indicators_found = 0
            for strategy, locator in CAPTCHA_REQUIRED_INDICATORS:
                try:
                    self.driver.find_element(strategy, locator)
                    indicators_found += 1
                except:
                    continue

            # Also check for interactive captcha specifically
            interactive_indicators_found = 0
            for strategy, locator in INTERACTIVE_CAPTCHA_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
                    interactive_indicators_found += 1
                except:
                    continue

            # Log interactive captcha detection
            if interactive_indicators_found >= 3:
                logger.info(
                    f"Interactive captcha detected! Found {interactive_indicators_found} interactive indicators"
                )

            # If we're confident it's a captcha screen, tap the input field
            is_captcha = indicators_found >= 3
            if is_captcha:
                # Try to find and focus the captcha input field
                try:
                    captcha_input = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.EditText[not(@password)]"
                    )
                    if captcha_input and captcha_input.is_displayed():
                        # Use our helper method to focus the captcha field if needed
                        captcha_strategy = (AppiumBy.XPATH, "//android.widget.EditText[not(@password)]")
                        self._focus_input_field_if_needed([captcha_strategy], "captcha")
                except Exception as e:
                    logger.debug(f"Error focusing captcha field: {e}")

            return is_captcha
        except Exception as e:
            logger.warning(f"Error checking for captcha screen: {e}", exc_info=True)
            return False

    def _try_find_element(self, by, locator):
        """Helper method to safely find an element without raising exceptions."""
        try:
            return self.driver.find_element(by, locator)
        except:
            return None
