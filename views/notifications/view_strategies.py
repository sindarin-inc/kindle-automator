from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
NOTIFICATION_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[contains(@text, 'Allow') and contains(@text, 'to send you notifications')]"),
]
