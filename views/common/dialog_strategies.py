from appium.webdriver.common.appiumby import AppiumBy

# System dialog detection strategies
NOTIFICATION_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"),
    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
]

# Common dialog buttons
DIALOG_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "android:id/button1"),  # Usually OK/Accept
    (AppiumBy.ID, "android:id/button2"),  # Usually Cancel/Deny
    (AppiumBy.XPATH, "//android.widget.Button[@text='OK']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Cancel']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Allow']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Deny']"),
]

# Error dialog identifiers
ERROR_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "android:id/alertTitle"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'error')]"),
]
