from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from views.core.logger import logger
from views.core.strategies import AUTH_ERROR_STRATEGIES, SIGN_IN_ERROR_STRATEGIES
import time


class AuthenticationHandler:
    def __init__(self, driver, email, password):
        self.driver = driver
        self.email = email
        self.password = password

    def sign_in(self):
        try:
            # Handle email entry and continue
            email_error = self._enter_email(self.email)
            if email_error:
                logger.error(f"Email validation failed: {email_error}")
                return False

            # Handle password
            self._enter_password()

            # Verify login success
            return self._verify_login()
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def _enter_email(self, email: str) -> bool:
        """Enter email and click continue."""
        logger.info("Entering email...")

        # Find and enter email
        try:
            email_field = self.driver.find_element(
                AppiumBy.XPATH,
                "//android.widget.EditText[@hint='Email or phone number']",
            )
            email_field.clear()
            email_field.send_keys(email)
            logger.info("Successfully entered email")
        except Exception as e:
            logger.error(f"Failed to enter email: {e}")
            return False

        # Find and click continue button
        try:
            continue_button = self.driver.find_element(
                AppiumBy.XPATH, "//android.widget.Button[@text='Continue']"
            )
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
        logger.info("Entering password...")
        # Find password field using multiple strategies
        password_field = None
        strategies = [
            (AppiumBy.CLASS_NAME, "android.widget.EditText"),
            (AppiumBy.XPATH, "//android.widget.EditText[@hint='Amazon password']"),
            (AppiumBy.XPATH, "//android.widget.EditText[@password='true']"),
        ]

        for strategy, locator in strategies:
            try:
                logger.info(f"Trying to find password field with strategy: {strategy}")
                password_field = self.driver.find_element(strategy, locator)
                if password_field:
                    break
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue

        if not password_field:
            raise Exception("Could not find password field")

        # Enter password
        logger.info("Clearing password field...")
        password_field.clear()
        logger.info("Entering password...")
        password_field.send_keys(self.password)

        # Find and click sign in button
        logger.info("Looking for sign in button...")
        sign_in_strategies = [
            (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
            (AppiumBy.XPATH, "//android.widget.Button[@text='Sign-In']"),
            (AppiumBy.CLASS_NAME, "android.widget.Button"),
        ]

        sign_in_button = None
        for strategy, locator in sign_in_strategies:
            try:
                logger.info(f"Trying to find sign in button with strategy: {strategy}")
                button = self.driver.find_element(strategy, locator)
                if button and button.get_attribute("text") in ["Sign In", "Sign-In"]:
                    sign_in_button = button
                    break
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue

        if not sign_in_button:
            raise Exception("Could not find sign in button")

        logger.info("Clicking sign in button...")
        sign_in_button.click()

    def _verify_login(self):
        try:
            library_locator = (AppiumBy.ID, "com.amazon.kindle:id/library_home_root")
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located(library_locator))
            return True
        except Exception:
            return False

    def _check_for_errors(self):
        """Check for any error messages on the page and return them if found."""
        logger.info("Checking for error messages...")
        time.sleep(1)  # Allow time for error messages to appear

        for strategy in AUTH_ERROR_STRATEGIES:
            try:
                error_element = self.driver.find_element(*strategy)
                error_text = error_element.text.strip()
                if error_text:  # Only process if there's actual text
                    logger.info(f"Found error message: {error_text}")
                    return error_text
            except Exception as e:
                if "no such element" not in str(e):
                    logger.error(f"Error while checking for errors: {e}")
                continue  # Try next strategy if element not found

        # If we get here, no error messages were found
        logger.info("No error messages found, proceeding...")
        return None
