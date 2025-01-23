from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
NOTIFICATION_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"),
    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
]
