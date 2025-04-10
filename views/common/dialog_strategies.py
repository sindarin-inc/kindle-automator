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
    (AppiumBy.XPATH, "//android.widget.Button[@text='Got it']"),
]

# Error dialog identifiers
ERROR_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "android:id/alertTitle"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'error')]"),
]

# Full screen dialog identifiers
FULLSCREEN_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Viewing full screen']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Got it']"),
    (AppiumBy.ID, "android:id/ok"),
]

# Dialog detection strategies for "App not responding" dialog
APP_NOT_RESPONDING_DIALOG_IDENTIFIERS = [
    # The title that says "Kindle isn't responding"
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/alertTitle' and contains(@text, 'Kindle isn')]",
    ),
    # The "Close app" button
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/aerr_close' and @text='Close app']"),
    # The "Wait" button
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/aerr_wait' and @text='Wait']"),
]

# Dialog interaction strategies
APP_NOT_RESPONDING_CLOSE_APP_BUTTON = (
    AppiumBy.XPATH,
    "//android.widget.Button[@resource-id='android:id/aerr_close' and @text='Close app']",
)
