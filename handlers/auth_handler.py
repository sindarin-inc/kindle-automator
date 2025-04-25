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

from server.config import VNC_URL
from server.logging_config import store_page_source
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

logger = logging.getLogger(__name__)


class LoginVerificationState(Enum):
    SUCCESS = "success"
    CAPTCHA = "captcha"
    TWO_FACTOR = "two_factor"
    INCORRECT_PASSWORD = "incorrect_password"
    ERROR = "error"
    UNKNOWN = "unknown"


class AuthenticationHandler:
    def __init__(self, driver, captcha_solution=None):
        self.driver = driver
        self.captcha_solution = captcha_solution
        self.screenshots_dir = "screenshots"
        self.last_captcha_screenshot = None  # Track the last captcha screenshot path
        self.interactive_captcha_detected = False  # Flag for the special interactive captcha case
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def prepare_for_authentication(self):
        """
        Prepare the app for authentication by navigating to the sign-in screen if needed.
        Always requires manual authentication via VNC.

        Returns:
            dict: Status information containing:
                - state: current AppState (LIBRARY, HOME, SIGN_IN, etc.)
                - requires_manual_login: boolean indicating if manual login is needed (always True)
                - already_authenticated: boolean indicating if already logged in
                - vnc_url: URL to access VNC for manual login
        """
        try:
            # Access the automator through the driver to get current state
            driver_instance = getattr(self.driver, "_driver", None)
            if driver_instance and hasattr(driver_instance, "automator"):
                automator = driver_instance.automator
            else:
                return {
                    "state": "UNKNOWN",
                    "requires_manual_login": True,
                    "already_authenticated": False,
                    "error": "Could not access automator from driver session",
                }

            # Make sure we have state information
            if not automator.state_machine:
                return {
                    "state": "UNKNOWN",
                    "requires_manual_login": True,
                    "already_authenticated": False,
                    "error": "No state machine available",
                }

            # Update current state to make sure it's accurate
            automator.state_machine.update_current_state()
            current_state = automator.state_machine.current_state
            state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

            logger.info(f"Current state before authentication preparation: {state_name}")

            # Check if we're already in a logged-in state (LIBRARY or HOME)
            if state_name in ["LIBRARY", "HOME"]:
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

                        # Update state after clicking
                        automator.state_machine.update_current_state()
                        updated_state = automator.state_machine.current_state
                        updated_state_name = (
                            updated_state.name if hasattr(updated_state, "name") else str(updated_state)
                        )

                        if updated_state_name == "LIBRARY":
                            logger.info("Successfully navigated to LIBRARY state")
                            state_name = "LIBRARY"
                    except Exception as e:
                        logger.error(f"Error navigating from HOME to LIBRARY: {e}")
                        # Continue with HOME state

                return {
                    "state": state_name,
                    "requires_manual_login": False,
                    "already_authenticated": True,
                    "vnc_url": "",
                }

            # Check if we're already on the sign-in screen
            if state_name == "SIGN_IN":
                logger.info("Already on sign-in screen")
                # Always require manual login
                return {
                    "state": "SIGN_IN",
                    "requires_manual_login": True,
                    "already_authenticated": False,
                    "vnc_url": VNC_URL,
                }

            # We need to navigate to the sign-in screen
            logger.info(f"Need to navigate to sign-in screen from {state_name}")

            # Try restarting the app to get to the sign-in screen
            success = False
            try:
                if hasattr(automator, "restart_kindle_app"):
                    logger.info("Restarting Kindle app to get to sign-in screen")
                    success = automator.restart_kindle_app()
                else:
                    logger.error("Automator doesn't have restart_kindle_app method")
            except Exception as e:
                logger.error(f"Error restarting app: {e}")

            # Check if restart succeeded and we're on the sign-in screen
            if success:
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

                if state_name == "SIGN_IN":
                    logger.info("Successfully navigated to sign-in screen")
                    # Always require manual login
                    return {
                        "state": "SIGN_IN",
                        "requires_manual_login": True,
                        "already_authenticated": False,
                        "vnc_url": VNC_URL,
                    }

                # If we reached a library state after restart, we're already logged in
                if state_name in ["LIBRARY", "HOME"]:
                    return {
                        "state": state_name,
                        "requires_manual_login": False,
                        "already_authenticated": True,
                        "vnc_url": "",
                    }

            # As a fallback, try to use transition_to_library which may go through auth flow
            try:
                logger.info("Trying transition_to_library to navigate through auth flow")
                automator.transition_to_library()
                automator.state_machine.update_current_state()
                current_state = automator.state_machine.current_state
                state_name = current_state.name if hasattr(current_state, "name") else str(current_state)

                if state_name == "SIGN_IN":
                    logger.info("Successfully navigated to sign-in screen via transition_to_library")
                    # Always require manual login
                    return {
                        "state": "SIGN_IN",
                        "requires_manual_login": True,
                        "already_authenticated": False,
                        "vnc_url": VNC_URL,
                    }

                if state_name in ["LIBRARY", "HOME"]:
                    return {
                        "state": state_name,
                        "requires_manual_login": False,
                        "already_authenticated": True,
                        "vnc_url": "",
                    }
            except Exception as e:
                logger.error(f"Error navigating with transition_to_library: {e}")

            # If we couldn't reliably get to the sign-in screen, return current state
            # and indicate manual login is needed
            return {
                "state": state_name,
                "requires_manual_login": True,
                "already_authenticated": False,
                "vnc_url": VNC_URL,
                "error": f"Could not navigate to sign-in screen from {state_name}",
            }

        except Exception as e:
            logger.error(f"Error in prepare_for_authentication: {e}")
            return {
                "state": "ERROR",
                "requires_manual_login": True,
                "already_authenticated": False,
                "vnc_url": VNC_URL,
                "error": str(e),
            }

    def update_captcha_solution(self, solution):
        """Update the captcha solution."""
        self.captcha_solution = solution

    def handle_2fa(self, code):
        """Handle 2FA verification.

        Args:
            code: The 2FA code provided by the user

        Returns:
            bool: True if 2FA verification was successful, False otherwise
        """
        try:
            logger.info(f"Handling 2FA with code: {code}")

            # Find the 2FA input field
            try:
                # Look for input field that might contain a 2FA code
                input_field = self.driver.find_element(
                    AppiumBy.XPATH,
                    "//android.widget.EditText[contains(@hint, 'code') or contains(@text, 'code')]",
                )

                # Clear and enter the 2FA code
                input_field.clear()
                input_field.send_keys(code)

                # Find and click the submit button
                submit_button = self.driver.find_element(
                    AppiumBy.XPATH,
                    "//android.widget.Button[contains(@text, 'Submit') or contains(@text, 'Verify') or contains(@text, 'Continue')]",
                )
                submit_button.click()

                # Wait for transition to complete
                time.sleep(2)

                # Check if we've moved to the library state
                for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                    try:
                        self.driver.find_element(by, locator)
                        logger.info("2FA verification successful")
                        return True
                    except:
                        continue

                logger.error("2FA verification failed - could not detect library view")
                return False

            except NoSuchElementException:
                logger.error("2FA input field or submit button not found")
                return False

        except Exception as e:
            logger.error(f"Error handling 2FA: {e}")
            return False

    def sign_in(self):
        """
        Manual authentication via VNC is required.
        
        Returns:
            A tuple indicating automated sign-in is not supported
        """
        try:
            logger.info("Authentication must be done manually via VNC")
            
            # Check for captcha as the only automated support we still provide
            if self._is_captcha_screen():
                logger.info("Captcha detected!")
                if not self._handle_captcha():
                    logger.error("Failed to handle captcha")
                    return False
                    
            # Return error to indicate VNC is required
            return (
                LoginVerificationState.ERROR,
                "Authentication must be done manually via VNC",
            )
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
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
                            logger.error(f"Authentication error: {error_message.text}")
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
                                    logger.error(f"Authentication error: {error_message}")
                                    return (LoginVerificationState.ERROR, error_message)
                                else:
                                    logger.error(
                                        "Authentication error box found but couldn't extract message"
                                    )
                                    return (LoginVerificationState.ERROR, "Unknown authentication error")
                            except Exception as e:
                                logger.error(f"Error extracting message from error box: {e}")
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
                                    logger.error(
                                        f"Found error message with disabled button: {error.text.strip()}"
                                    )
                                    error_found = True
                                    return (LoginVerificationState.ERROR, error.text.strip())
                            except:
                                continue

                        # If no error text was found, this could be an in-progress authentication
                        # Return None to continue waiting rather than immediately failing
                        if not error_found:
                            # Store page source for debugging but continue waiting
                            filepath = store_page_source(driver.page_source, "auth_button_disabled_waiting")
                            logger.info(
                                f"Stored authentication state page source with disabled button at: {filepath}"
                            )

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
                                    logger.error(f"Found error message: {error.text.strip()}")
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
                    logger.error(f"Login failed with incorrect password: {result[1]}")
                    # Return the result tuple directly so the server can handle it specifically
                    return result
                elif isinstance(result, tuple) and result[0] == LoginVerificationState.ERROR:
                    logger.error(f"Login failed: {result[1]}")
                    return result
                else:
                    logger.error(f"Could not verify login status, state: {result}")
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
                                    return True
                            except:
                                continue
                except:
                    pass

                # If we reach here, we truly timed out
                filepath = store_page_source(self.driver.page_source, "auth_login_timeout")
                logger.info(f"Stored unknown timeout page source at: {filepath}")

                logger.error("Could not verify login status within timeout")
                return False

        except Exception as e:
            logger.error(f"Error verifying login: {e}")
            return False

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

    def _is_password_screen(self):
        """Check if we're on the password input screen - used for state detection only"""
        try:
            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS:
                try:
                    self.driver.find_element(strategy, locator)
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

            # Special handling for interactive captcha - it's a stronger signal
            if interactive_indicators_found >= 3:
                logger.info(
                    f"Interactive captcha detected! Found {interactive_indicators_found} interactive indicators"
                )
                self.interactive_captcha_detected = True
                return True

            # Require at least 3 indicators to be confident it's a captcha screen
            return indicators_found >= 3
        except Exception as e:
            logger.error(f"Error checking for captcha screen: {e}")
            return False

    def _handle_captcha(self):
        """Handle captcha screen by saving the image using scrcpy and returning."""
        try:
            logger.info("Handling CAPTCHA state...")

            # Special handling for grid-based image captcha
            if self.interactive_captcha_detected:
                logger.error("Grid-based image captcha detected - this requires human interaction")
                logger.error(
                    "This type of grid-based captcha cannot be solved automatically - need to restart app"
                )

                # We need to restart the app to try and get around this captcha
                try:
                    # First try to take a screenshot for diagnostic purposes
                    timestamp = int(time.time())
                    screenshot_id = f"interactive_captcha_{timestamp}"
                    screenshot_path = os.path.join(self.screenshots_dir, f"{screenshot_id}.png")

                    # Try to get the driver instance
                    driver_instance = getattr(self.driver, "_driver", None)
                    if driver_instance and hasattr(driver_instance, "automator"):
                        automator = driver_instance.automator
                        if automator:
                            # Use secure screenshot
                            secure_path = automator.take_secure_screenshot(screenshot_path, force_secure=True)
                            if secure_path:
                                logger.info(f"Saved interactive captcha screenshot to {secure_path}")
                                self.last_captcha_screenshot = screenshot_id

                    # Force close the app
                    if hasattr(self.driver, "close_app"):
                        logger.info("Force closing the Kindle app to recover from interactive captcha")
                        self.driver.close_app()
                        time.sleep(2)

                    # Try to launch it again (this would be handled by the restart logic elsewhere)
                    if hasattr(self.driver, "launch_app"):
                        logger.info("Relaunching the Kindle app")
                        self.driver.launch_app()
                        time.sleep(3)

                    # Reset the interactive captcha flag
                    self.interactive_captcha_detected = False

                    # Return False to indicate we need client interaction
                    return False
                except Exception as restart_e:
                    logger.error(f"Error while trying to restart app after interactive captcha: {restart_e}")
                    # Still return False to indicate we need client interaction
                    return False

            # Standard text captcha handling
            # Find the captcha image element
            try:
                captcha_image = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.Image[@text='captcha']"
                )
            except Exception:
                logger.error("Could not find captcha image element")
                return False

            # Access the automator through the driver
            driver_instance = getattr(self.driver, "_driver", None)
            if driver_instance and hasattr(driver_instance, "automator"):
                automator = driver_instance.automator
            else:
                automator = None

            if not automator:
                logger.error("Could not access automator from driver session")
                # Fall back to regular screenshot method, though it will likely fail with FLAG_SECURE
                screenshot_path = os.path.join("screenshots", "temp_full.png")
                try:
                    self.driver.save_screenshot(screenshot_path)
                except Exception as e:
                    logger.error(f"Screenshot failed due to FLAG_SECURE: {e}")
                    return False
            else:
                # Use secure screenshot method with scrcpy to bypass FLAG_SECURE
                # Generate a unique timestamped filename for this captcha screenshot
                timestamp = int(time.time())
                secure_screenshot_id = f"auth_screen_{timestamp}"
                final_path = os.path.join("screenshots", f"{secure_screenshot_id}.png")

                # Always force scrcpy mode for captcha screenshots to bypass FLAG_SECURE
                secure_path = automator.take_secure_screenshot(
                    final_path,
                    force_secure=True,  # Force scrcpy usage even if the automator would normally use ADB
                )

                if not secure_path:
                    logger.error("Secure screenshot failed even with scrcpy")
                    return False

                logger.info(f"Used scrcpy for secure screenshot at {secure_path}")

                # Store the screenshot ID for use in the response
                self.last_captcha_screenshot = secure_screenshot_id
                logger.info(f"Stored captcha screenshot ID: {secure_screenshot_id}")

                # No need to crop - we'll return the full screenshot for easier captcha viewing
                # We'll just save a copy as captcha.png for backward compatibility
                captcha_path = os.path.join("screenshots", "captcha.png")
                import shutil

                try:
                    shutil.copy(final_path, captcha_path)
                    logger.info(f"Copied full screenshot to {captcha_path} for backward compatibility")
                except Exception as e:
                    logger.warning(f"Error copying to captcha.png: {e}")

            # If we have a solution, use it
            if self.captcha_solution:
                logger.info("Using provided captcha solution...")
                captcha_input = self.driver.find_element(AppiumBy.CLASS_NAME, "android.widget.EditText")
                captcha_input.send_keys(self.captcha_solution)

                # Find and click submit button
                submit_button = self.driver.find_element(
                    AppiumBy.XPATH, "//android.widget.Button[@text='Submit']"
                )
                submit_button.click()

                # Wait briefly to see if it worked
                time.sleep(2)
                return True

            # No solution provided, let server handle it
            logger.info("No captcha solution provided - server will handle interaction")
            return False

        except Exception as e:
            logger.error(f"Error handling captcha: {e}")
            return False

    def _try_find_element(self, by, locator):
        """Helper method to safely find an element without raising exceptions."""
        try:
            return self.driver.find_element(by, locator)
        except:
            return None
