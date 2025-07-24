from appium.webdriver.common.appiumby import AppiumBy

# Dialog buttons
NOTIFICATION_DIALOG_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_allow_button"),
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_deny_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Allow']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Deny']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='ALLOW']"),
    (AppiumBy.XPATH, '//android.widget.Button[@text="DON\'T ALLOW"]'),
]
