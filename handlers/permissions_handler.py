from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class PermissionsHandler:
    def __init__(self, driver):
        self.driver = driver

    def handle_notifications_permission(self, should_allow=True):
        """Handle the notifications permission dialog"""
        try:
            # The buttons have standard Android resource IDs
            button_id = (
                "com.android.permissioncontroller:id/permission_allow_button"
                if should_allow
                else "com.android.permissioncontroller:id/permission_deny_button"
            )

            button_locator = (AppiumBy.ID, button_id)
            WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located(button_locator)
            )
            self.driver.find_element(*button_locator).click()
            return True
        except Exception as e:
            print(f"Failed to handle notifications permission: {e}")
            return False
