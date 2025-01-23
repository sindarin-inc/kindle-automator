from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class AuthenticationHandler:
    def __init__(self, driver, email, password):
        self.driver = driver
        self.email = email
        self.password = password

    def sign_in(self):
        try:
            # Find and click sign in button
            sign_in_locator = (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button")
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(sign_in_locator)
            )
            self.driver.find_element(*sign_in_locator).click()

            # Handle email
            self._enter_email()

            # Handle password
            self._enter_password()

            # Verify login success
            return self._verify_login()
        except Exception as e:
            print(f"Authentication failed: {e}")
            return False

    def _enter_email(self):
        email_field_locator = (AppiumBy.ID, "com.amazon.kindle:id/email")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(email_field_locator)
        )
        email_field = self.driver.find_element(*email_field_locator)
        email_field.clear()
        email_field.send_keys(self.email)

        continue_button_locator = (AppiumBy.ID, "com.amazon.kindle:id/continue_button")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(continue_button_locator)
        )
        self.driver.find_element(*continue_button_locator).click()

    def _enter_password(self):
        password_field_locator = (AppiumBy.ID, "com.amazon.kindle:id/password")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(password_field_locator)
        )
        password_field = self.driver.find_element(*password_field_locator)
        password_field.clear()
        password_field.send_keys(self.password)

        sign_in_submit_locator = (AppiumBy.ID, "com.amazon.kindle:id/login_submit")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(sign_in_submit_locator)
        )
        self.driver.find_element(*sign_in_submit_locator).click()

    def _verify_login(self):
        try:
            library_locator = (AppiumBy.ID, "com.amazon.kindle:id/library_home_root")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(library_locator)
            )
            return True
        except Exception:
            return False
