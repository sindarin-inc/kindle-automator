from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from views.core.logger import logger
from views.auth.view_strategies import (
    EMAIL_VIEW_IDENTIFIERS,
    PASSWORD_VIEW_IDENTIFIERS,
    ERROR_VIEW_IDENTIFIERS,
    LIBRARY_VIEW_VERIFICATION_STRATEGIES,
)
from views.auth.interaction_strategies import (
    EMAIL_FIELD_STRATEGIES,
    CONTINUE_BUTTON_STRATEGIES,
    PASSWORD_FIELD_STRATEGIES,
    PASSWORD_SIGN_IN_BUTTON_STRATEGIES,
    SIGN_IN_RADIO_BUTTON_STRATEGIES,
    AUTH_ERROR_STRATEGIES,
    SIGN_IN_ERROR_STRATEGIES,
)
import time
from selenium.common.exceptions import NoSuchElementException


class AuthenticationHandler:
    def __init__(self, driver, email, password):
        self.driver = driver
        self.email = email
        self.password = password

    def sign_in(self):
        try:
            # Check if we're on the password screen
            if self._is_password_screen():
                logger.info("Already on password screen, entering password...")
                self._enter_password()
                return self._verify_login()

            # Otherwise handle the full sign in flow
            # Check if we need to select the sign in radio button
            self._select_sign_in_if_needed()

            # Handle email entry and continue
            email_error = self._enter_email(self.email)
            if isinstance(email_error, str):  # Only treat string responses as errors
                logger.error(f"Email validation failed: {email_error}")
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
                        time.sleep(1)  # Wait for any animations
                    return
                except:
                    continue
        except Exception as e:
            logger.debug(f"No sign in radio button found: {e}")

    def _enter_email(self, email: str) -> bool:
        """Enter email and click continue."""
        logger.info("Entering email...")

        # Find and enter email
        try:
            email_field = None
            for strategy, locator in EMAIL_FIELD_STRATEGIES:
                try:
                    email_field = self.driver.find_element(strategy, locator)
                    if email_field:
                        break
                except Exception:
                    continue

            if not email_field:
                raise Exception("Could not find email field")

            email_field.clear()
            email_field.send_keys(email)
            logger.info("Successfully entered email")
        except Exception as e:
            logger.error(f"Failed to enter email: {e}")
            return False

        # Find and click continue button
        try:
            continue_button = None
            for strategy, locator in CONTINUE_BUTTON_STRATEGIES:
                try:
                    continue_button = self.driver.find_element(strategy, locator)
                    if continue_button:
                        break
                except Exception:
                    continue

            if not continue_button:
                raise Exception("Could not find continue button")

            continue_button.click()
            logger.info("Successfully clicked continue button")
        except Exception as e:
            logger.error(f"Failed to click continue button: {e}")
            return False

        # Check for errors
        time.sleep(1)  # Wait for error messages
        logger.info("Checking for error messages...")
        self.driver.page_source  # Dump page source for debugging

        for strategy in SIGN_IN_ERROR_STRATEGIES:
            try:
                error_element = self.driver.find_element(AppiumBy.XPATH, strategy)
                error_text = error_element.text.strip()
                if error_text:
                    logger.error(f"Found error message: {error_text}")
                    return error_text
            except:
                continue

        logger.info("No error messages found")
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
        time.sleep(1)  # Wait for error messages to appear
        logger.info("Checking for error messages...")

        for strategy in AUTH_ERROR_STRATEGIES:
            try:
                error_element = self.driver.find_element(*strategy)
                error_text = error_element.text.strip()
                if error_text:
                    logger.info(f"Found error message: {error_text}")
                    if "No account found with email address" in error_text:
                        return True
                    if "incorrect password" in error_text:
                        return True
            except NoSuchElementException:
                continue

        logger.info("No error messages found")
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
