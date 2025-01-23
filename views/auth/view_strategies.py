from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
EMAIL_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@hint='Email or phone number']",
    ),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Email or phone number']"),
]

PASSWORD_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@password='true']",
    ),
    (AppiumBy.XPATH, "//android.widget.EditText[@password='true']"),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Amazon password']"),
]

ERROR_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'incorrect')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'incorrect')]"),
]
