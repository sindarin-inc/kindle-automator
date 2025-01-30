import logging

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)


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

            # Only wait a short time since dialog may auto-dismiss
            try:
                WebDriverWait(self.driver, 2).until(EC.presence_of_element_located(button_locator))
                self.driver.find_element(*button_locator).click()
                logger.info("Successfully handled notification permission dialog")
                return True
            except Exception as e:
                logger.info("Notification permission dialog not found - may have auto-dismissed")
                return True  # Return True since absence of dialog is not an error

        except Exception as e:
            logger.error(f"Error handling notifications permission: {e}")
            return False
