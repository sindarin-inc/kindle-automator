from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from views.core.logger import logger
from views.auth.view_strategies import (
    EMAIL_VIEW_IDENTIFIERS,
    PASSWORD_VIEW_IDENTIFIERS,
    ERROR_VIEW_IDENTIFIERS,
    LIBRARY_VIEW_VERIFICATION_STRATEGIES,
    CAPTCHA_VIEW_IDENTIFIERS,
    CAPTCHA_REQUIRED_INDICATORS,
)
from views.auth.interaction_strategies import (
    EMAIL_FIELD_STRATEGIES,
    CONTINUE_BUTTON_STRATEGIES,
    PASSWORD_FIELD_STRATEGIES,
    PASSWORD_SIGN_IN_BUTTON_STRATEGIES,
    SIGN_IN_RADIO_BUTTON_STRATEGIES,
    AUTH_ERROR_STRATEGIES,
    SIGN_IN_ERROR_STRATEGIES,
    CAPTCHA_INPUT_FIELD,
    CAPTCHA_CONTINUE_BUTTON,
)
import time
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from PIL import Image
import os
import subprocess


class AuthenticationHandler:
    def __init__(self, driver, email, password, captcha_solution=None):
        self.driver = driver
        self.email = email
        self.password = password
        self.captcha_solution = captcha_solution
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def sign_in(self):
        try:
            # Check if we're on the password screen
            if self._is_password_screen():
                logger.info("Already on password screen, entering password...")
                self._enter_password()
                return self._verify_login()

            # Check for captcha first
            if self._is_captcha_screen():
                logger.info("Captcha detected!")
                if not self._handle_captcha():
                    logger.error("Failed to handle captcha")
                    return False

            # Otherwise handle the full sign in flow
            # Check if we need to select the sign in radio button
            self._select_sign_in_if_needed()

            # Handle email entry and continue
            email_result = self._enter_email(self.email)
            if email_result == "RESTART_AUTH":  # Check for special restart value
                logger.info("Restarting authentication process...")
                return False
            elif isinstance(email_result, str) or not email_result:  # Handle other error cases
                logger.error(f"Email validation failed: {email_result}")
                return False

            # Handle password
            self._enter_password()

            # Verify login success
            return self._verify_login()
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

    def _enter_email(self, email: str) -> bool:
        """Enter email and click continue."""
        logger.info("Entering email...")

        try:
            # Wait for and find email field
            email_field = WebDriverWait(self.driver, 10).until(
                lambda driver: next(
                    (
                        field
                        for strategy, locator in EMAIL_FIELD_STRATEGIES
                        if (field := self._try_find_element(strategy, locator))
                    ),
                    None,
                )
            )
            if not email_field:
                raise Exception("Could not find email field")

            email_field.clear()
            email_field.send_keys(email)
            logger.info("Successfully entered email")

            # Wait for and click continue button
            continue_button = WebDriverWait(self.driver, 10).until(
                lambda driver: next(
                    (
                        button
                        for strategy, locator in CONTINUE_BUTTON_STRATEGIES
                        if (button := self._try_find_element(strategy, locator))
                    ),
                    None,
                )
            )
            if not continue_button:
                raise Exception("Could not find continue button")

            continue_button.click()
            logger.info("Successfully clicked continue button")

            # Wait for either password page or error message
            logger.info("Waiting for password page or error message...")
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda driver: (
                        # Check for password page
                        any(
                            self._try_find_element(strategy, locator)
                            for strategy, locator in PASSWORD_VIEW_IDENTIFIERS
                        )
                        or
                        # Check for error message
                        any(
                            self._try_find_element(AppiumBy.XPATH, strategy)
                            for strategy in SIGN_IN_ERROR_STRATEGIES
                        )
                    )
                )

                # Now check which one we got
                for strategy in SIGN_IN_ERROR_STRATEGIES:
                    error = self._try_find_element(AppiumBy.XPATH, strategy)
                    if error and error.text.strip():
                        logger.error(f"Found error message: {error.text.strip()}")
                        # Close the dialog by clicking the back button
                        logger.info("Closing authentication dialog...")
                        self.driver.back()
                        time.sleep(2)  # Wait for dialog to close
                        return "RESTART_AUTH"

                # If we get here, we found the password page
                logger.info("Successfully transitioned to password page")
                return True

            except TimeoutException:
                logger.error("Timed out waiting for password page or error message")
                return False

        except Exception as e:
            logger.error(f"Failed during email entry process: {e}")
            return False

        return True

    def _enter_password(self):
        """Enter password into password field."""
        logger.info("Entering password...")
        try:
            # Find password field
            logger.info("Trying to find password field with strategy: xpath")
            password_field = self.driver.find_element(*PASSWORD_VIEW_IDENTIFIERS[0])

            # Clear and enter password
            logger.info("Clearing password field...")
            password_field.clear()
            logger.info("Entering password...")
            password_field.send_keys(self.password)

            # Look for sign in button
            logger.info("Looking for sign in button...")
            logger.info("Trying to find sign in button with strategy: xpath")
            sign_in_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, "//android.widget.Button[@text='Sign in']"))
            )

            # Click sign in button
            logger.info("Clicking sign in button...")
            sign_in_button.click()
            return True

        except Exception as e:
            logger.error(f"Error entering password: {e}")
            return False

    def _verify_login(self):
        """Verify successful login by waiting for library view to load."""
        try:
            logger.info("Verifying login success...")

            # Create a condition that will pass if ANY of our locators are found
            def any_library_element_present(driver):
                for by, locator in LIBRARY_VIEW_VERIFICATION_STRATEGIES:
                    try:
                        driver.find_element(by, locator)
                        logger.info(f"Found library element: {locator}")
                        return True
                    except:
                        continue
                return False

            # Wait for any library element to be present
            try:
                WebDriverWait(self.driver, 20).until(any_library_element_present)
                logger.info("Successfully verified library view")
                return True
            except Exception as e:
                # If we get here, log the page source to see what's visible
                logger.info("\n=== PAGE SOURCE AFTER TIMEOUT START ===")
                logger.info(self.driver.page_source)
                logger.info("=== PAGE SOURCE AFTER TIMEOUT END ===\n")
                logger.error("Could not verify library view loaded")
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
        """Check if we're on the password input screen"""
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

            # Require at least 3 indicators to be confident it's a captcha screen
            return indicators_found >= 3
        except Exception as e:
            logger.error(f"Error checking for captcha screen: {e}")
            return False

    def _handle_captcha(self):
        """Handle captcha if present by saving screenshot and waiting for manual input"""
        try:
            # Save screenshot of captcha
            screenshot_path = os.path.join(self.screenshots_dir, "captcha.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved captcha screenshot to {screenshot_path}")

            # Wait for manual captcha entry
            input("Please solve the captcha and press Enter to continue...")

            # Save another screenshot to verify captcha was entered
            screenshot_path = os.path.join(self.screenshots_dir, "captcha_entered.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved post-captcha screenshot to {screenshot_path}")

            return True
        except Exception as e:
            logger.error(f"Error handling captcha: {e}")
            return False

    def _try_find_element(self, by, locator):
        """Helper method to safely find an element without raising exceptions."""
        try:
            return self.driver.find_element(by, locator)
        except:
            return None
